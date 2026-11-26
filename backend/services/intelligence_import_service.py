"""Deterministic, transactional partner pipeline import and scoped reads."""

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session, load_only

from backend.models.customer_knowledge import STATUS_READY, CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.use_case import Customer, User
from backend.services import record_cleanup

# The matching normalization is the alias write-rules normalization
# (gap #6: NFKC + casefold + collapse) — imported, never duplicated.
from backend.services.customer_alias_service import normalize_alias as _norm
from backend.services.customer_knowledge_service import (
    create_customer_knowledge,
    delete_customer_knowledge,
)
from backend.services.customer_match import CustomerMatcher
from backend.services.membership_service import _audit
from backend.services.pipeline_read_model import (
    compare_pipeline_snapshots,
    pipeline_snapshot_history,
    renewal_attention_for_rows,
    summarize_pipeline_rows,
)
from backend.upload_size import read_upload_bytes

REQUIRED_COLUMNS = (
    "Customer Account", "Opportunity Name", "Opp Stage", "Est. ACV Line Amount (USD)",
    "Product Offering Group", "Close Date", "Partner Account", "FLAG - Growth / Risk",
)
STRING_COLUMNS = {
    "customer_account_name": "Customer Account",
    "opportunity_name": "Opportunity Name",
    "opportunity_number": "Opportunity Number",
    "opp_stage": "Opp Stage",
    "forecast_category": "Opportunity Forecast Category",
    "net_new_vs_renewal": "Net New Vs Renewal",
    "route_to_market": "Route to Market",
    "opportunity_channel": "Opportunity Channel",
    "partner_account": "Partner Account",
    "partner_tier": "Partner Tier",
    "product_offering_group": "Product Offering Group",
    "product_sku": "Product SKU",
    "product_description": "Product Description",
    "currency_code": "Opportunity Currency Code",
    "fiscal_quarter": "Fiscal Quarter",
    "growth_risk_flag": "FLAG - Growth / Risk",
    "deal_reg_approval_status": "Deal Registration Approval Status",
}
DATE_COLUMNS = {
    "close_date": "Close Date",
    "contract_start_date": "Original Contract Start Date",
    "contract_end_date": "Original Contract End Date",
    "current_contract_start_date": "Current Contract Start Date",
    "current_contract_end_date": "Current Contract End Date",
    "opp_create_date": "Opportunity Create Date",
}
MONEY_COLUMNS = {
    "est_acv_usd": "Est. ACV Line Amount (USD)",
    "est_tcv_usd": "Est. TCV Line Amount (USD)",
}

# Renewal rows record software/hardware the customer actually runs (they are
# renewing it), so each one also populates the customer's structured
# technology inventory (charter §21). Deterministic derivation only:
# the product name is the Product Offering Group (falling back to the
# Product Description), the category comes from an explicit table of the
# offering groups observed in partner pipeline reports ("other" fallback —
# never fabricated), vendor/quantity/versions stay unknown (NULL).
TECH_SOURCE_PREFIX = "pipeline import #"


def _tech_source(import_id):
    return f"{TECH_SOURCE_PREFIX}{import_id} (renewal)"


RENEWAL_CATEGORY_MAP = {
    "rhel": "operating_system",
    "openshift": "cloud_platform",
    "ansible": "automation_tool",
    "ai platforms": "ai_technology",
    "cloud infrastructure": "infrastructure",
    "application services": "other",
    "miscellaneous": "other",
    "consulting": "other",
    "lightwell network": "networking",
}


def _text(value):
    return (value or "").strip() or None


def _date(value):
    for fmt in ("%Y-%m-%d", "%b %d, %Y"):
        try:
            return datetime.strptime((value or "").strip(), fmt).date()
        except ValueError:
            pass
    return None


# Cells that mean "no amount" in partner exports — blank, never a warning.
BLANK_AMOUNTS = {"", "-", "\u2013", "\u2014", "n/a", "na", "none", "null"}
# Currency decoration stripped before parsing: $, the USD code, thousands
# separators and any whitespace (incl. non-breaking spaces).
AMOUNT_NOISE = re.compile(r"\$|usd|,|\s", re.IGNORECASE)


def _money(value):
    """Parse a USD amount cell → ``(amount | None, readable)``.

    Accepts ``$1,234.50``, ``USD 1,234``, ``1 234``, ``-1,234`` and accounting
    negatives ``(1,234)``; blank-like cells (``-``, ``N/A``, ``NaN``) are blank. An unreadable cell never blocks the import: the
    amount is recorded as unknown (NULL — the read model's coverage states
    already handle it) and the caller reports it as an amount warning.
    """
    text = (value or "").strip()
    if text.lower() in BLANK_AMOUNTS:
        return None, True
    text = AMOUNT_NOISE.sub("", text)
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    try:
        amount = float(text)
    except ValueError:
        return None, False
    if not math.isfinite(amount):
        # NaN/inf cells are how some exports write "no amount": blank.
        return None, True
    return -amount if negative else amount, True


def _parse(data):
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        header = reader.fieldnames or []
        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            raise HTTPException(422, f"Missing required columns: {', '.join(missing)}")
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(422, f"Invalid pipeline CSV: {exc}") from None
    if not rows:
        raise HTTPException(400, "Pipeline report contains no data rows")
    return header, rows


def _totals(rows, summary=None):
    summary = summary if summary is not None else summarize_pipeline_rows(rows)
    return {
        "line_count": summary["grain"]["line_count"],
        "deal_count": summary["grain"]["opportunity_count"],
        "open_deals": summary["stages"]["open"],
        "unknown_deals": summary["stages"]["unknown"],
        "growth": sum((row.growth_risk_flag or "").lower() == "growth" for row in rows),
        "risk": sum((row.growth_risk_flag or "").lower() == "risk" for row in rows),
        "est_acv_total": summary["amounts"]["acv"]["total"],
        "est_tcv_total": summary["amounts"]["tcv"]["total"],
        "amount_coverage": {key: amount["coverage"] for key, amount in summary["amounts"].items()},
    }


def _cell(value):
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _markdown(customer, batch, rows, technologies=None):
    summary = summarize_pipeline_rows(rows, batch)
    totals = _totals(rows, summary)
    stages = summary["stages"]
    amounts = {
        key: f"${value:,.2f}" if value is not None else "not recorded"
        for key, value in (("acv", totals["est_acv_total"]), ("tcv", totals["est_tcv_total"]))
    }
    products = Counter(row.product_offering_group for row in rows if row.product_offering_group)
    product_summary = ", ".join(f"{name} ({count})" for name, count in sorted(products.items()))
    partners = ", ".join(sorted({row.partner_account for row in rows if row.partner_account}))
    lines = [
        f"# Partner Pipeline Report — {customer.name}", "",
        f"Extracted from `{batch.file_name}` (intelligence import #{batch.id}, "
        f"{batch.created_at:%Y-%m-%d}) —",
        f"{len(rows)} of {batch.total_rows} report rows. Partner: {partners}.", "",
        "## Summary", "",
        f"- Opportunities: {totals['deal_count']} · Lines: {totals['line_count']} "
        f"(unidentified lines: {summary['grain']['unidentified_lines']})",
        f"- Stages: open {stages['open']}, won {stages['won']}, "
        f"lost {stages['lost']}, unknown {stages['unknown']}",
        f"- Est. ACV total: {amounts['acv']} · Est. TCV total: {amounts['tcv']}",
        f"- Amount coverage: ACV {totals['amount_coverage']['acv']}, "
        f"TCV {totals['amount_coverage']['tcv']}",
        f"- Products: {product_summary}",
        f"- Growth/Risk: growth {totals['growth']}, risk {totals['risk']}", "",
        "## Deals", "",
        "| Opportunity | Stage | Product | Est. ACV | Est. TCV | Close Date | Flag |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        cells = (
            f"{row.opportunity_name or ''} ({row.opportunity_number or ''})", row.opp_stage,
            row.product_offering_group,
            f"${row.est_acv_usd:,.0f}" if row.est_acv_usd is not None else "",
            f"${row.est_tcv_usd:,.0f}" if row.est_tcv_usd is not None else "",
            row.close_date.isoformat() if row.close_date else "", row.growth_risk_flag,
        )
        lines.append("| " + " | ".join(_cell(value) for value in cells) + " |")
    if technologies:
        lines.extend(["", "## Technologies recorded from renewal", ""])
        lines.extend(f"- {name}" for name in technologies)
    lines.extend([
        "", f"Source: partner pipeline report; see intelligence import #{batch.id} under",
        "Global Intelligence → Intelligence Import.", "",
    ])
    return "\n".join(lines)


def _subset_csv(header, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _is_renewal(value):
    """Renewal rows (e.g. 'Renewal') record software/hardware the customer
    runs; 'New'/'Net New' rows do not. Blank is not a renewal."""
    return "renew" in (value or "").lower()


def _renewal_notes(rows, filename):
    first = rows[0]
    parts = ["Renewal record"]
    opportunity = " ".join(p for p in (first.opportunity_name, first.opportunity_number) if p)
    if opportunity:
        parts.append(f"opportunity {opportunity}")
    if first.product_description and first.product_description != first.product_offering_group:
        parts.append(f"product: {first.product_description}")
    if len(rows) > 1:
        parts.append(f"{len(rows)} renewal line items")
    parts.append(filename)
    return "; ".join(parts)


def _technology_rows(db, customer_id, rows, batch_id, filename, now):
    """Deterministically upsert the customer's technology inventory from this
    customer's renewal rows. Creates one record per distinct product (Product
    Offering Group, falling back to Product Description); an existing
    import-generated record is refreshed (latest renewal evidence); any other
    existing record (manual/seeded) is left untouched. Returns
    (created_count, refreshed_count, names)."""
    by_name = {}
    for row in rows:
        if not _is_renewal(row.net_new_vs_renewal):
            continue
        product = row.product_offering_group or row.product_description
        if not product:
            continue
        by_name.setdefault(_norm(product), []).append(row)
    if not by_name:
        return 0, 0, []
    existing = {
        _norm(record.name): record
        for record in db.query(CustomerTechnology).filter(
            CustomerTechnology.customer_id == customer_id,
        ).all()
    }
    source = _tech_source(batch_id)
    created = refreshed = 0
    names = []
    for key, product_rows in by_name.items():
        name = product_rows[0].product_offering_group or product_rows[0].product_description
        record = existing.get(key)
        if record is not None:
            if (record.source or "").startswith(TECH_SOURCE_PREFIX):
                record.source = source
                record.date_observed = now.date()
                record.notes = _renewal_notes(product_rows, filename)
                refreshed += 1
                names.append(record.name)
            continue
        db.add(CustomerTechnology(
            customer_id=customer_id, name=name,
            category=RENEWAL_CATEGORY_MAP.get(key, "other"),
            source=source, date_observed=now.date(),
            verification_state="verified",
            notes=_renewal_notes(product_rows, filename),
        ))
        created += 1
        names.append(name)
    return created, refreshed, names


def _import_technologies(db, batch_id, customer_ids):
    """Sorted unique technology names a batch currently owns for its customers."""
    rows = db.query(CustomerTechnology.customer_id, CustomerTechnology.name).filter(
        CustomerTechnology.source == _tech_source(batch_id),
        CustomerTechnology.customer_id.in_(customer_ids),
    ).all()
    grouped = defaultdict(list)
    for customer_id, name in rows:
        grouped[customer_id].append(name)
    return {customer_id: sorted(set(names)) for customer_id, names in grouped.items()}


def _audit_import(db, user, action, batch, request, extra=None):
    actor = db.query(User).filter(User.username == user["username"]).first()
    details = {
        "import_id": batch.id, "file_name": batch.file_name, "total_rows": batch.total_rows,
        "matched_accounts": batch.matched_accounts, "matched_rows": batch.matched_rows,
        "unmatched_accounts": batch.unmatched_accounts,
    }
    if extra:
        details.update(extra)
    _audit(db, actor, action, None, batch.id, details, request)


async def import_pipeline(db, upload, user, request=None):
    filename = upload.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv pipeline reports are accepted")
    data = await read_upload_bytes(upload)
    header, raw_rows = _parse(data)
    # Part 14 import remediation (operator rules 2026-11-01): each row maps to
    # an existing customer by name OR alias, case-insensitive (two fixed
    # queries); a row that does not resolve to exactly one customer is
    # skipped and reported — it never blocks the file, never creates a
    # customer. No suffix/fuzzy matching.
    matcher = CustomerMatcher(db)
    matched = defaultdict(list)
    extracts = defaultdict(list)
    unmatched = Counter()
    amount_issues = []
    for source_row, raw in enumerate(raw_rows, 1):
        account = _text(raw.get("Customer Account"))
        customer, outcome = matcher.resolve(account)
        if customer is None:
            unmatched[(account or "(blank)", outcome)] += 1
            continue
        values = {attr: _text(raw.get(column)) for attr, column in STRING_COLUMNS.items()}
        values.update({attr: _date(raw.get(column)) for attr, column in DATE_COLUMNS.items()})
        for attr, column in MONEY_COLUMNS.items():
            values[attr], readable = _money(raw.get(column))
            if not readable:
                amount_issues.append({"source_row": source_row, "customer_id": customer.id,
                                      "column": column, "value": (raw.get(column) or "")[:64]})
        matched[customer.id].append(PartnerPipeline(
            customer_id=customer.id, source_row=source_row, **values,
        ))
        extracts[customer.id].append(raw)
    report = [{"account_name": name, "row_count": count, "reason": reason}
              for (name, reason), count in sorted(unmatched.items(),
                                                  key=lambda item: (-item[1], item[0]))]
    now = datetime.now(UTC)
    batch = IntelligenceImport(
        file_name=filename, file_sha256=hashlib.sha256(data).hexdigest(), file_data=data,
        total_rows=len(raw_rows), matched_accounts=len(matched),
        matched_rows=sum(len(rows) for rows in matched.values()),
        unmatched_accounts=len(unmatched), unmatched_report=json.dumps(report),
        amount_issues=json.dumps(amount_issues), imported_by=user["username"], created_at=now,
    )
    try:
        db.add(batch)
        db.flush()
        by_id = matcher.by_id
        tech_created_total = tech_refreshed_total = 0
        for customer_id, rows in matched.items():
            for row in rows:
                row.import_id = batch.id
                row.created_at = now
            db.add_all(rows)
            db.flush()
            tech_created, tech_refreshed, tech_names = _technology_rows(
                db, customer_id, rows, batch.id, filename, now,
            )
            tech_created_total += tech_created
            tech_refreshed_total += tech_refreshed
            # The existing knowledge CRUD helpers commit internally. A separate
            # session on this connection confines those commits to savepoints;
            # the outer import transaction remains the sole durable commit.
            with Session(bind=db.connection(), join_transaction_mode="create_savepoint") as knowledge_db:
                record = create_customer_knowledge(
                    knowledge_db, customer_id, "pipeline_report", filename,
                    _subset_csv(header, extracts[customer_id]), knowledge_category="opportunities",
                )
                record.normalized_content = _markdown(
                    by_id[customer_id], batch, rows, technologies=tech_names,
                )
                record.processing_status = STATUS_READY
                record.processed = 1
                record.processor = "pipeline-import"
                record.processed_at = now
                record.ingested_at = now
                record.ingestion_status = "ready"
                record.classification = f"pipeline_import:{batch.id}"
                knowledge_db.commit()
        _audit_import(db, user, "intelligence_import.create", batch, request, extra={
            "technologies_created": tech_created_total,
            "technologies_refreshed": tech_refreshed_total,
            "skipped_rows": batch.total_rows - batch.matched_rows,
            "amount_issues": len(amount_issues),
        })
        from backend.services import sales_access
        # A-1 re-recon ruling (2026-11-01, R1 continuation): the create
        # response uses the same central READ scope as GET /{id}/ so the
        # same batch shows identical numbers on both.
        customer_ids = None if sales_access.is_unrestricted(user) else sales_access.customer_scope(user, db)
        response = _detail(db, batch, customer_ids)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def list_imports(db):
    return [batch.to_dict() for batch in db.query(IntelligenceImport).order_by(
        IntelligenceImport.id.desc(),
    ).all()]


def _get_import(db, import_id):
    batch = db.get(IntelligenceImport, import_id)
    if batch is None:
        raise HTTPException(404, "Import not found")
    return batch


def _detail(db, batch, customer_ids=None, include_rows=False):
    query = db.query(PartnerPipeline).filter(PartnerPipeline.import_id == batch.id)
    if customer_ids is not None:
        query = query.filter(PartnerPipeline.customer_id.in_(customer_ids))
    rows = query.order_by(PartnerPipeline.source_row, PartnerPipeline.id).all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.customer_id].append(row)
    names = dict(db.query(Customer.id, Customer.name).filter(Customer.id.in_(grouped)).all())
    documents = dict(db.query(CustomerKnowledge.customer_id, CustomerKnowledge.id).filter(
        CustomerKnowledge.classification == f"pipeline_import:{batch.id}",
        CustomerKnowledge.customer_id.in_(grouped),
    ).all())
    technologies = _import_technologies(db, batch.id, grouped)
    matched = []
    for customer_id, account_rows in grouped.items():
        totals = _totals(account_rows)
        # Part 14: how the rows matched — derived read-time from the raw
        # supplied names. A row matched by name carries a norm-equal customer
        # name; an alias never norm-equals a customer name, so legacy rows
        # (pre-alias) read back as "name" exactly as they matched.
        # ``supplied_names`` lists every spelling the file used for this
        # account (an account fed by both its name and an alias shows both).
        name_norm = _norm(names[customer_id])
        supplied = Counter(row.customer_account_name for row in account_rows)
        supplied_names = [
            {"name": name, "row_count": count,
             "matched_by": "name" if _norm(name) == name_norm else "alias"}
            for name, count in sorted(supplied.items(), key=lambda item: (-item[1], item[0]))
        ]
        matched_by_name = any(item["matched_by"] == "name" for item in supplied_names)
        matched.append({
            "customer_name": names[customer_id], "customer_id": customer_id,
            "account_name": account_rows[0].customer_account_name, "row_count": len(account_rows),
            "knowledge_id": documents.get(customer_id),
            "matched_by": "name" if matched_by_name else "alias",
            "supplied_names": supplied_names,
            "est_acv_total": totals["est_acv_total"], "est_tcv_total": totals["est_tcv_total"],
            "amount_coverage": totals["amount_coverage"],
            "technologies": technologies.get(customer_id, []),
        })
    response = {
        **batch.to_dict(), "file_sha256": batch.file_sha256,
        "matched": sorted(matched, key=lambda item: (-item["row_count"], item["customer_name"])),
        # Legacy batches (pre-remediation) carry no reason: they read "unmatched".
        "unmatched": [{**entry, "reason": entry.get("reason", "unmatched")}
                      for entry in json.loads(batch.unmatched_report)],
        # Unreadable amount cells on imported rows, in scope only (the cell
        # value is account data).
        "amount_issues": [
            {key: issue[key] for key in ("source_row", "column", "value")}
            for issue in json.loads(batch.amount_issues or "[]")
            if issue["customer_id"] in grouped
        ],
        "visible_customer_count": len(grouped),
    }
    if include_rows:
        response.update(pipeline_rows=[row.to_dict() for row in rows],
                        matched_out_of_scope=(0 if customer_ids is None
                                              else batch.matched_accounts - len(grouped)))
    return response


def get_import(db, import_id, customer_ids=None):
    return _detail(db, _get_import(db, import_id), customer_ids, include_rows=True)


def delete_import(db, import_id, user, request=None):
    batch = _get_import(db, import_id)
    try:
        # Explicit deletion also works on runtime SQLite connections with FK
        # enforcement disabled; the schema retains ON DELETE CASCADE as well.
        deleted_rows = db.query(PartnerPipeline).filter(
            PartnerPipeline.import_id == batch.id,
        ).delete(synchronize_session=False)
        # Technology records this import created (or refreshed) carry its
        # exact source string; manual/seeded records are never touched.
        technologies = db.query(CustomerTechnology).filter(
            CustomerTechnology.source == _tech_source(batch.id),
        )
        record_cleanup.technologies(db, [tid for tid, in technologies.with_entities(CustomerTechnology.id)])
        deleted_tech = technologies.delete(synchronize_session=False)
        documents = db.query(CustomerKnowledge).filter(
            CustomerKnowledge.classification == f"pipeline_import:{batch.id}",
        ).all()
        with Session(bind=db.connection(), join_transaction_mode="create_savepoint") as knowledge_db:
            for document in documents:
                delete_customer_knowledge(knowledge_db, document.id, document.customer_id)
        _audit_import(db, user, "intelligence_import.delete", batch, request,
                      extra={"deleted_technologies": deleted_tech})
        db.delete(batch)
        db.commit()
        return {"detail": "Import deleted", "deleted_rows": deleted_rows,
                "deleted_knowledge": len(documents), "deleted_technologies": deleted_tech}
    except Exception:
        db.rollback()
        raise


def customer_pipeline(db, name, customer_ids=None, compare_with=None):
    customer = db.query(Customer).filter(Customer.name == name).first()
    if customer is None or (customer_ids is not None and customer.id not in customer_ids):
        raise HTTPException(404, "Customer not found")
    history = pipeline_snapshot_history(db, customer.id)
    import_id = history[0]["import_id"] if history else None
    if compare_with is not None:
        # Parse here, after the route's unchanged 401/404 authorization gates.
        # A FastAPI int query annotation would reject malformed input with 422.
        if isinstance(compare_with, str):
            try:
                compare_with = int(compare_with)
            except ValueError:
                raise HTTPException(400, "Invalid comparison snapshot") from None
        if (not isinstance(compare_with, int) or import_id is None or compare_with == import_id
                or compare_with not in {entry["import_id"] for entry in history}):
            raise HTTPException(400, "Invalid comparison snapshot")
    selected_ids = [import_id] + ([compare_with] if compare_with is not None else [])
    batches = {batch.id: batch for batch in db.query(IntelligenceImport).options(load_only(
        IntelligenceImport.id, IntelligenceImport.file_name,
        IntelligenceImport.created_at, IntelligenceImport.imported_by,
    )).filter(IntelligenceImport.id.in_(selected_ids)).all()} if import_id else {}
    batch = batches.get(import_id)
    all_rows = db.query(PartnerPipeline).filter(
        PartnerPipeline.customer_id == customer.id, PartnerPipeline.import_id.in_(selected_ids),
    ).order_by(PartnerPipeline.import_id, PartnerPipeline.source_row, PartnerPipeline.id).all() if batch else []
    rows = [row for row in all_rows if row.import_id == import_id]
    summary = summarize_pipeline_rows(rows, batch)
    renewals = renewal_attention_for_rows(rows, as_of=summary["as_of"])
    if batch:
        renewals["snapshot"] = {key: history[0][key] for key in ("import_id", "source_file", "imported_at")}
    technologies = [
        name for (name,) in db.query(CustomerTechnology.name).filter(
            CustomerTechnology.customer_id == customer.id,
            CustomerTechnology.source == _tech_source(import_id),
        ).all()
    ] if import_id else []
    # Preserve the legacy timestamp spelling (+00:00), including naive DB dates.
    imported_at = (batch.created_at.replace(tzinfo=UTC).isoformat()
                   if batch and batch.created_at.tzinfo is None else
                   batch.created_at.isoformat() if batch else None)
    response = {
        "customer_name": customer.name, "import_id": import_id,
        "source_file": batch.file_name if batch else None,
        "imported_at": imported_at,
        "rows": [row.to_dict() for row in rows], "totals": _totals(rows, summary),
        "technologies": sorted(set(technologies)), "summary": summary,
        "history": history, "renewals": renewals,
    }
    if compare_with is not None:
        response["comparison"] = compare_pipeline_snapshots(
            [row for row in all_rows if row.import_id == compare_with], rows,
            batches[compare_with], batch, as_of=summary["as_of"],
        )
    return response
