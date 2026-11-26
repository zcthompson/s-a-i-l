"""Allowlisted NetSuite parsing, reduction and transactional scoped imports.

Uploaded bytes and ignored columns never leave the parser's caller or enter
persistence, audit details or responses. Tests use synthetic report values.
"""

import csv
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePath

import openpyxl
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from backend.models.customer_technology import CustomerTechnology
from backend.models.netsuite_import import NetSuiteImport, NetSuiteImportNote, NetSuiteImportRow
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, User
from backend.services import sales_access
from backend.services.customer_alias_service import normalize_alias
from backend.services.customer_match import CustomerMatcher
from backend.services.membership_service import _audit
from backend.services.redhat_opportunity_service import (
    MAX_COLUMNS,
    MAX_ROWS,
    MAX_UNCOMPRESSED,
    _cell,
)
from backend.upload_size import MAX_UPLOAD_BYTES, read_upload_bytes

COLUMNS = {
    "end customer name": "customer_name",
    "subscription id": "subscription_id",
    "subscription name": "product",
    "subscription expiration date": "term_end",
    "detail type": "detail_type",
    "quantity": "quantity",
    "customer_detail_qty_uom": "uom",
    "contract period": "term",
    "contract period type": "term_type",
    "invoice date": "invoice_date",
    "subscription_status": "status",
    "notes": "notes", "memo": "notes", "comments": "notes",
}
REQUIRED = {"end customer name", "subscription name"}
SEAT_UOMS = {"license", "licenses", "licence", "licences", "seat", "seats", "user", "users"}
# Deliberately small, explicit evidence rules. Unknown products remain unknown.
VENDORS = (
    ("Microsoft", r"\b(microsoft|office 365|microsoft 365|m365|azure|exchange online|teams|power bi|dynamics 365)\b"),
    ("Adobe", r"\b(adobe|acrobat|creative cloud)\b"),
    ("AWS", r"\b(aws|amazon web services)\b"),
    ("Acronis", r"\bacronis\b"),
    ("Google", r"\bgoogle\b"),
)


def _date(value):
    if value is None:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
    raise HTTPException(422, "Report contains an invalid date")


def _quantity(value):
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", text):
        return None
    try:
        number = Decimal(text.replace(",", ""))
        return str(number) if number.is_finite() else None
    except InvalidOperation:
        return None


def _headers(values):
    return [str(value).strip().casefold() if value is not None else "" for value in values]


def _extract(records, header_row, headers):
    nonempty = [h for h in headers if h]
    if len(nonempty) != len(set(nonempty)):
        raise HTTPException(422, "Report contains duplicate column names")
    targets = [COLUMNS[h] for h in nonempty if h in COLUMNS]
    if len(targets) != len(set(targets)):
        raise HTTPException(422, "Report contains duplicate observation columns")
    rows = []
    for source_row, values in enumerate(records, header_row + 1):
        if source_row - header_row > MAX_ROWS or len(values) > MAX_COLUMNS:
            raise HTTPException(422, "Report exceeds the row or column limit")
        if not any(value is not None and str(value).strip() for value in values):
            continue
        row = dict.fromkeys(COLUMNS.values())
        row["source_row"] = source_row
        for index, header in enumerate(headers):
            if header not in COLUMNS or index >= len(values):
                continue
            key = COLUMNS[header]
            value = _cell(values[index])
            # An optional original observation is kept verbatim, including whitespace.
            row[key] = values[index] if key == "notes" and value is not None else value
        for key in ("customer_name", "subscription_id", "product", "uom", "term", "term_type", "status", "detail_type", "notes"):
            if row[key] is not None:
                row[key] = str(row[key])
        if row["customer_name"] is not None and len(row["customer_name"]) > 255:
            raise HTTPException(422, "Report contains an invalid customer name")
        row["invoice_date"] = _date(row["invoice_date"])
        row["term_end"] = _date(row["term_end"])
        row["quantity"] = _quantity(row["quantity"])
        limits = {"customer_name": 255, "subscription_id": 255, "product": 255,
                  "quantity": 64, "uom": 100, "term": 100, "term_type": 100,
                  "status": 100, "detail_type": 100}
        if any(row[key] is not None and len(row[key]) > limit for key, limit in limits.items()):
            raise HTTPException(422, "Report contains an overlong subscription field")
        rows.append(row)
    if not rows:
        raise HTTPException(422, "Report contains no subscription rows")
    return rows


def parse(data, filename):
    """Parse .csv (UTF-8 BOM allowed) or .xlsx, discarding every other column.

    Errors are static messages: source values, filenames and headers are never
    interpolated. Blank customer names are retained for later skip reporting.
    """
    extension = PurePath(filename.replace("\\", "/")).suffix.lower()
    if extension not in {".csv", ".xlsx"}:
        raise HTTPException(422, "Select a .csv or .xlsx report")
    if not data:
        raise HTTPException(400, "Upload is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Upload exceeds the maximum size")
    try:
        if extension == ".csv":
            reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
            for number, values in enumerate(reader, 1):
                if len(values) > MAX_COLUMNS:
                    raise HTTPException(422, "Report exceeds the row or column limit")
                headers = _headers(values)
                if REQUIRED.issubset(headers):
                    return _extract(reader, number, headers)
                if number >= 10:
                    break
            raise HTTPException(422, "Report is missing required subscription headers")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED:
                raise HTTPException(413, "Workbook expands beyond the allowed size")
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            matches = []
            for sheet in workbook:
                if (sheet.max_column or 0) > MAX_COLUMNS or (sheet.max_row or 0) > MAX_ROWS + 10:
                    raise HTTPException(422, "Report exceeds the row or column limit")
                for number, values in enumerate(sheet.iter_rows(max_row=10, values_only=True), 1):
                    headers = _headers(values)
                    if REQUIRED.issubset(headers):
                        matches.append((sheet, number, headers))
            if len(matches) != 1:
                raise HTTPException(422, "Workbook must contain exactly one subscription report")
            sheet, number, headers = matches[0]
            return _extract(sheet.iter_rows(min_row=number + 1, values_only=True), number, headers)
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Unable to read the subscription report") from None


async def parse_upload(upload):
    """Use the shared bounded reader; return parsed allowlisted rows only."""
    return parse(await read_upload_bytes(upload), upload.filename or "")


def _product(row):
    name = re.sub(r"\s*\(NCE\b[^)]*\)\s*", " ", row["product"], flags=re.I).strip()
    # Remove only explicit terminal billing terms, never arbitrary product words.
    name = re.sub(r"\s*(?:[-–]\s*|\()(?:annual|monthly|yearly|\d+[- ]year)(?:\s+term)?\)?$", "", name, flags=re.I).strip()
    consumption = (row["detail_type"] or "").casefold() == "resource overusage" or bool(
        re.search(r"\b(?:azure|aws|amazon web services)\b.*\bplan\b", name, re.I))
    if consumption:
        if re.search(r"\bazure\b", name, re.I):
            return "Microsoft Azure (consumption)", "Microsoft", "cloud_platform", "public_cloud"
        if re.search(r"\b(?:aws|amazon web services)\b", name, re.I):
            return "AWS (consumption)", "AWS", "cloud_platform", "public_cloud"
        return None
    vendor = next((vendor for vendor, pattern in VENDORS if re.search(pattern, name, re.I)), None)
    licensed = (row["uom"] or "").casefold() in SEAT_UOMS
    return name, vendor, "software" if licensed else None, "saas" if licensed else None


def _event_order(row):
    return row["invoice_date"] or "", row["source_row"]


def _seats(events, latest, category):
    if category != "software" or (latest["status"] or "").casefold() != "active":
        return None
    eligible = [row for row in events if not any(
        word in (row["detail_type"] or "").casefold() for word in ("refund", "adjustment", "downgrade"))]
    if not eligible:
        return None
    row = max(eligible, key=_event_order)
    if (row["status"] or "").casefold() != "active" or (row["uom"] or "").casefold() not in SEAT_UOMS:
        return None
    number = Decimal(row["quantity"]) if row["quantity"] is not None else None
    if number is None or number < 0 or number != number.to_integral_value() or number > 2147483647:
        return None
    return int(number)


def reduce_products(rows, matcher, scope=None, import_id=None, resolved_rows=None):
    """Match existing customers and reduce subscription events without DB writes.

    Latest invoice date wins, ties use source row. Missing dates sort before
    known dates. Every matched source row remains available for NS-04/NS-05;
    suggestions are read-only and never link a customer. Scope is enforced
    before any row contributes to a product.
    """
    matched, skipped = [], []
    groups = defaultdict(list)
    for row in rows:
        customer, method = (resolved_rows or {}).get(
            row["source_row"], (None, None))
        if method is None:
            customer, method = matcher.resolve(row["customer_name"] or "")
        if customer is None or (scope is not None and customer.id not in scope):
            skipped.append({**row, "reason": "No unambiguous accessible customer name or alias",
                            "suggestion": matcher.suggest(row["customer_name"] or "", scope)})
            continue
        if not row["subscription_id"] or not row["product"]:
            skipped.append({**row, "reason": "Missing subscription reference or product", "suggestion": None})
            continue
        matched_row = {**row, "customer_id": customer.id, "matched_by": method}
        matched.append(matched_row)
        groups[(customer.id, row["subscription_id"])].append(matched_row)
    products = {}
    rejected_rows = set()
    for (cid, subscription), events in groups.items():
        latest = max(events, key=_event_order)
        classification = _product(latest)
        if classification is None or not classification[0]:
            for row in events:
                rejected_rows.add(row["source_row"])
                skipped.append({**{key: value for key, value in row.items() if key not in {"customer_id", "matched_by"}},
                                "reason": "Consumption platform or product is unknown", "suggestion": None})
            continue
        name, vendor, category, deployment = classification
        key = cid, normalize_alias(name)
        quantity = _seats(events, latest, category)
        notes = "; ".join(text for text in (
            f"Subscription term: {' '.join(value for value in (latest['term'], latest['term_type']) if value)}"
            if latest["term"] or latest["term_type"] else None,
            f"Subscription term end: {latest['term_end']}" if latest["term_end"] else None,
        ) if text)
        active = (latest["status"] or "").casefold() == "active"
        if key not in products:
            products[key] = {"customer_id": cid, "name": name, "vendor": vendor, "category": category,
                             "deployment_model": deployment, "quantity": quantity,
                             "support_state": "under_support" if active else None,
                             "verification_state": "verified",
                             "source": f"NetSuite import #{import_id}" if import_id is not None else None,
                             "date_observed": latest["invoice_date"], "notes": notes or None,
                             "subscription_ids": [subscription], "source_rows": [r["source_row"] for r in events],
                             "_active_quantities": [quantity] if active else []}
        else:
            product = products[key]
            product["subscription_ids"].append(subscription)
            product["source_rows"].extend(r["source_row"] for r in events)
            if active:
                product["_active_quantities"].append(quantity)
            if category != product["category"]:
                product["category"] = None
                product["deployment_model"] = None
            if not active:
                product["support_state"] = None
            product["date_observed"] = max(filter(None, (product["date_observed"], latest["invoice_date"])), default=None)
            if notes and notes not in (product["notes"] or "").split("\n"):
                product["notes"] = "\n".join(filter(None, (product["notes"], notes)))
    for product in products.values():
        quantities = product.pop("_active_quantities")
        # Never present an incomplete sum as a verified total. Ended
        # subscriptions contribute no seats to the active inventory.
        total = sum(q for q in quantities if q is not None)
        product["quantity"] = (total if quantities and None not in quantities
                               and total <= 2147483647 else None)
    return {"products": list(products.values()),
            "matched_rows": [row for row in matched if row["source_row"] not in rejected_rows],
            "skipped": sorted(skipped, key=lambda row: row["source_row"])}


# Persistence consumes only parse()'s allowlisted rows. All helpers stage their
# writes on the caller's transaction; the public operations commit once.
TECH_SOURCE = "NetSuite import #"
COUNT_FIELDS = ("technologies_created", "technologies_refreshed", "technologies_associated",
                "risks_created", "risks_refreshed", "observations_created")
APPLIED = {"created", "refreshed", "associated"}


def _authorize(db, user):
    if user is None:
        raise HTTPException(401, "Authentication required")
    if sales_access.effective_role(user) not in {"system_admin", "sales_manager"}:
        raise HTTPException(403, "Manager access required")
    return None if sales_access.effective_role(user) == "system_admin" else sales_access.customer_scope(user, db)


def _day(value):
    return date.fromisoformat(value) if value else None


def _raw(row):
    result = {key: getattr(row, key) for key in dict.fromkeys(COLUMNS.values())}
    for key in ("invoice_date", "term_end"):
        result[key] = result[key].isoformat() if result[key] else None
    return {**result, "source_row": row.source_row}


def _batch(db, user, batch_id, lock=False):
    query = db.query(NetSuiteImport).filter_by(id=batch_id)
    if lock:
        query = query.with_for_update()
    batch = query.first()
    if batch is None:
        raise HTTPException(404, "Import not found")
    if sales_access.effective_role(user) != "system_admin" and batch.imported_by != user["username"]:
        scope = sales_access.customer_scope(user, db)
        if not _visible_rows(db, batch, scope, CustomerMatcher(db), user):
            raise HTTPException(404, "Import not found")
    return batch


def _filter_rows(rows, scope, matcher, include_unmatched=False):
    if scope is None:
        return rows
    visible = []
    for row in rows:
        if row.customer_id is not None:
            if row.customer_id in scope:
                visible.append(row)
        elif row.disposition != "customer_deleted":
            customer, _ = matcher.resolve(row.customer_name or "")
            if (customer is not None and customer.id in scope) or (customer is None and include_unmatched):
                visible.append(row)
    return visible


def _visible_rows(db, batch, scope, matcher, user):
    rows = db.query(NetSuiteImportRow).filter_by(import_id=batch.id).order_by(NetSuiteImportRow.source_row).all()
    return _filter_rows(rows, scope, matcher, include_unmatched=batch.imported_by == user["username"])


def _summary(batch, rows, scope):
    # Counts are recomputed from visible evidence for scoped readers; do not
    # expose aggregate counts about customers whose access was later revoked.
    result = {"import_id": batch.id, "file_name": batch.file_name, "layout": batch.layout,
              "invoice_date": max((r.invoice_date.isoformat() for r in rows if r.invoice_date), default=None),
              "created_at": batch.created_at.isoformat(), "imported_by": batch.imported_by,
              "status": ("complete_with_skips" if any(r.disposition not in APPLIED for r in rows) else "complete"),
              "total_rows": len(rows),
              "matched_rows": sum(row.disposition in APPLIED for row in rows),
              "matched_accounts": len({r.customer_id for r in rows if r.disposition in APPLIED}),
              "skipped_rows": sum(row.disposition not in APPLIED for row in rows)}
    if scope is None:
        result.update({key: getattr(batch, key) for key in COUNT_FIELDS})
    else:
        for disposition, field in (("created", "technologies_created"), ("refreshed", "technologies_refreshed"),
                                   ("associated", "technologies_associated")):
            result[field] = len({r.technology_id for r in rows if r.disposition == disposition and r.technology_id})
        for field in ("risks_created", "risks_refreshed", "observations_created"):
            result[field] = sum(getattr(row, field) for row in rows)
    return result


def _serialize_row(row, scope, matcher):
    return {"id": row.id, **_raw(row), "customer_id": row.customer_id,
            "matched_by": row.matched_by, "vendor": row.vendor,
            "technology_id": row.technology_id, "risk_note_id": row.risk_note_id,
            "observation_note_id": row.observation_note_id,
            "disposition": row.disposition, "reason": row.reason,
            "suggestion": (matcher.suggest(row.customer_name or "", scope)
                           if row.disposition not in APPLIED and row.disposition != "customer_deleted" else None)}


def _risk_specs(events):
    latest = max(events, key=_event_order)
    risks = []
    if (latest["status"] or "").casefold() == "terminated":
        risks.append(("terminated", "Possible risk: subscription terminated",
                      "The imported subscription status is Terminated. Confirm the customer's current service needs."))
    term = " ".join(filter(None, (latest["term"], latest["term_type"]))).casefold()
    annual = bool(re.search(r"\b(annual|annually|year|years|yearly|multi-year|multiyear)\b", term))
    if not annual and (latest["term_type"] or "").casefold() in {"month", "months"}:
        try:
            annual = Decimal(latest["term"] or "0") >= 12
        except InvalidOperation:
            pass
    if annual and latest["term_end"] and latest["invoice_date"]:
        days = (_day(latest["term_end"]) - _day(latest["invoice_date"])).days
        if 0 <= days <= 90:
            risks.append(("term_ending", "Possible risk: subscription term ending",
                          f"An annual or multi-year subscription term ends on {latest['term_end']}, "
                          "within 90 days of the invoice date. Confirm renewal plans; this is not vendor end-of-support."))
    if any((row["detail_type"] or "").casefold() == "resource downgrade" for row in events):
        risks.append(("downgrade", "Possible risk: subscription seat reduction",
                      "The import contains a Resource Downgrade event. Confirm the reason for the reduction."))
    return latest, risks


def _not_older(invoice, batch_id, previous_date, previous_source):
    """Invoice date orders evidence; batch ID breaks same-date import ties.

    Re-matching an older batch must not replace a later correction for the
    same invoice date. A batch may still refresh its own results after aliases
    or scope grants have changed.
    """
    if previous_date is not None:
        if invoice is None:
            return False
        if invoice != previous_date:
            return invoice > previous_date
    elif invoice is not None:
        return True
    match = re.fullmatch(re.escape(TECH_SOURCE) + r"(\d+)", previous_source or "")
    return match is None or batch_id >= int(match.group(1))


def _note(db, batch, cid, subscription, kind, title, content, invoice, technology, user):
    key = db.query(NetSuiteImportNote).filter_by(customer_id=cid, subscription_id=subscription, kind=kind).first()
    note = db.get(SalesNote, key.note_id) if key and key.note_id else None
    is_risk = not kind.startswith("observation:")
    category, verification = ("risk", "inferred") if is_risk else ("account_observation", "verified")
    newer = key is None or _not_older(invoice, batch.id, key.invoice_date, note.source if note else None)
    created = note is None
    outcome = None
    if created:
        note = SalesNote(customer_id=cid, category=category, verification_state=verification,
                         title=title, content=content, author=user["username"])
        db.add(note)
        db.flush()
        if key is None:
            key = NetSuiteImportNote(customer_id=cid, subscription_id=subscription, kind=kind)
            db.add(key)
        key.note_id = note.id
    # Never overwrite a note reclassified/claimed by a human or another source.
    owned = created or ((note.source or "").startswith(TECH_SOURCE)
                        and note.category == category and note.verification_state == verification)
    if owned and (created or newer):
        note.content, note.title = content, title
        note.source, note.note_date = f"{TECH_SOURCE}{batch.id}", invoice
        note.related_technologies = [technology]
        key.invoice_date = invoice
        if is_risk:
            field = "risks_created" if created else "risks_refreshed"
            setattr(batch, field, getattr(batch, field) + 1)
            outcome = field
        elif created:
            batch.observations_created += 1
            outcome = "observations_created"
    db.flush()
    return note.id, outcome


def _technology(db, batch, product, existing):
    key = product["customer_id"], normalize_alias(product["name"])
    matches = existing.get(key, [])
    # Duplicate inventory names are ambiguous; never overwrite one arbitrarily.
    if len(matches) > 1:
        return None, "Ambiguous existing technology"
    record = matches[0] if matches else None
    if record is not None and not (record.source or "").startswith(TECH_SOURCE):
        batch.technologies_associated += 1
        return record, "associated"
    if product["category"] is None:
        return None, "Product category is unknown"
    observed = _day(product["date_observed"])
    if record is not None and not _not_older(observed, batch.id, record.date_observed, record.source):
        batch.technologies_associated += 1
        return record, "associated"
    created = record is None
    if created:
        record = CustomerTechnology(customer_id=product["customer_id"], name=product["name"])
        db.add(record)
        existing[key] = [record]
    for field in ("vendor", "category", "deployment_model", "quantity", "support_state", "verification_state", "source", "notes"):
        setattr(record, field, product[field])
    record.date_observed = observed
    # Vendor EOL, criticality, lifecycle and all other fields remain untouched.
    field = "technologies_created" if created else "technologies_refreshed"
    setattr(batch, field, getattr(batch, field) + 1)
    db.flush()
    return record, "created" if created else "refreshed"


def _apply(db, batch, stored, user, scope):
    matcher = CustomerMatcher(db)
    pinned = {row.source_row: (matcher.by_id.get(row.customer_id), row.matched_by or "name")
              for row in stored if row.disposition in APPLIED and row.customer_id is not None}
    raw = [_raw(row) for row in stored if row.disposition != "customer_deleted"]
    reduced = reduce_products(raw, matcher, scope, batch.id, resolved_rows=pinned)
    by_row = {row.source_row: row for row in stored}
    cids = sorted({p["customer_id"] for p in reduced["products"]})
    # Stable customer locks serialize cross-batch technology/note upserts on PG;
    # the batch insert/update already reserves SQLite's single writer.
    if cids:
        db.query(Customer).filter(Customer.id.in_(cids)).order_by(Customer.id).with_for_update().all()
    existing = defaultdict(list)
    for tech in db.query(CustomerTechnology).filter(CustomerTechnology.customer_id.in_(cids)).order_by(CustomerTechnology.id):
        existing[(tech.customer_id, normalize_alias(tech.name))].append(tech)
    for key in COUNT_FIELDS:
        setattr(batch, key, 0)
    for row in stored:
        row.risks_created = row.risks_refreshed = row.observations_created = 0
    for row in reduced["skipped"]:
        stage = by_row[row["source_row"]]
        if stage.disposition in APPLIED:
            continue
        stage.disposition, stage.reason = "skipped", row["reason"]
    matched = {row["source_row"]: row for row in reduced["matched_rows"]}
    for product in reduced["products"]:
        technology, disposition = _technology(db, batch, product, existing)
        events = [matched[number] for number in product["source_rows"]]
        for event in events:
            stage = by_row[event["source_row"]]
            stage.customer_id, stage.matched_by = event["customer_id"], event["matched_by"]
            stage.vendor = product["vendor"]
            stage.technology_id = technology.id if technology else None
            stage.disposition = disposition if technology else "skipped"
            stage.reason = None if technology else disposition
        if technology is None:
            continue
        subscriptions = defaultdict(list)
        for event in events:
            subscriptions[event["subscription_id"]].append(event)
        for subscription, subscription_events in subscriptions.items():
            latest, specs = _risk_specs(subscription_events)
            note_ids = []
            for kind, title, content in specs:
                note_id, outcome = _note(db, batch, product["customer_id"], subscription, kind,
                                         title, content, _day(latest["invoice_date"]), technology, user)
                note_ids.append(note_id)
                if outcome:
                    anchor = by_row[latest["source_row"]]
                    setattr(anchor, outcome, getattr(anchor, outcome) + 1)
            for event in subscription_events:
                stage = by_row[event["source_row"]]
                stage.risk_note_id = note_ids[0] if note_ids else stage.risk_note_id
                if event["notes"] is not None:
                    kind = "observation:" + hashlib.sha256(event["notes"].encode()).hexdigest()
                    note_id, outcome = _note(db, batch, product["customer_id"], subscription, kind,
                        "Imported subscription observation", event["notes"], _day(event["invoice_date"]), technology, user)
                    stage.observation_note_id = note_id
                    if outcome:
                        setattr(stage, outcome, getattr(stage, outcome) + 1)
    db.flush()
    all_rows = db.query(NetSuiteImportRow).filter_by(import_id=batch.id).all()
    batch.total_rows = len(all_rows)
    batch.matched_rows = sum(r.disposition in APPLIED for r in all_rows)
    batch.matched_accounts = len({r.customer_id for r in all_rows if r.disposition in APPLIED})
    batch.skipped_rows = batch.total_rows - batch.matched_rows
    batch.status = "complete_with_skips" if batch.skipped_rows else "complete"


def _audit_batch(db, user, batch, action, request):
    actor = db.query(User).filter_by(username=user["username"]).first()
    _audit(db, actor, action, None, batch.id,
           {"total_rows": batch.total_rows, "matched_rows": batch.matched_rows,
            "matched_accounts": batch.matched_accounts, "skipped_rows": batch.skipped_rows,
            **{key: getattr(batch, key) for key in COUNT_FIELDS}}, request)


async def import_file(db, upload, user, request=None):
    scope = _authorize(db, user)
    data = await read_upload_bytes(upload)
    rows = parse(data, upload.filename or "")
    digest = hashlib.sha256(data).hexdigest()
    existing = db.query(NetSuiteImport).filter_by(file_sha256=digest).first()
    if existing is not None:
        return detail(db, user, _batch(db, user, existing.id).id)
    name = PurePath((upload.filename or "").replace("\\", "/")).name
    batch = NetSuiteImport(file_name=name[:255], file_sha256=digest, layout=PurePath(name).suffix.lower()[1:],
                          invoice_date=max((_day(r["invoice_date"]) for r in rows if r["invoice_date"]), default=None),
                          imported_by=user["username"])
    try:
        db.add(batch)
        db.flush()
        stored = [NetSuiteImportRow(import_id=batch.id, **{key: (_day(value) if key in {"term_end", "invoice_date"} else value)
                  for key, value in row.items()}) for row in rows]
        db.add_all(stored)
        db.flush()
        _apply(db, batch, stored, user, scope)
        _audit_batch(db, user, batch, "netsuite_import.create", request)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(NetSuiteImport).filter_by(file_sha256=digest).first()
        if existing is not None:
            return detail(db, user, _batch(db, user, existing.id).id)
        raise
    except Exception:
        db.rollback()
        raise
    return detail(db, user, batch.id)


def detail(db, user, batch_id):
    scope = _authorize(db, user)
    batch = _batch(db, user, batch_id)
    matcher = CustomerMatcher(db)
    rows = _visible_rows(db, batch, scope, matcher, user)
    result = _summary(batch, rows, scope)
    result["rows"] = [_serialize_row(row, scope, matcher) for row in rows]
    cids = {r.customer_id for r in rows if r.customer_id is not None}
    subscriptions = {(r.customer_id, r.subscription_id) for r in rows if r.customer_id is not None}
    keys = [key for key in db.query(NetSuiteImportNote).filter(NetSuiteImportNote.customer_id.in_(cids))
            if (key.customer_id, key.subscription_id) in subscriptions and key.note_id is not None]
    result["risk_notes"] = [{"customer_id": key.customer_id, "subscription_id": key.subscription_id,
                             "kind": key.kind, "note_id": key.note_id} for key in keys
                            if not key.kind.startswith("observation:")]
    result["risks"] = len(result["risk_notes"])
    result["skipped"] = [row for row in result["rows"] if row["disposition"] not in APPLIED]
    return result


def history(db, user):
    scope = _authorize(db, user)
    # Stage access is shared by customer scope, so two managers can reuse one
    # distributor export without exposing each other's customers/unmatched rows.
    batches = db.query(NetSuiteImport).order_by(NetSuiteImport.id.desc()).limit(100).all()
    matcher = CustomerMatcher(db)
    grouped = defaultdict(list)
    for row in db.query(NetSuiteImportRow).filter(NetSuiteImportRow.import_id.in_([b.id for b in batches])):
        grouped[row.import_id].append(row)
    result = []
    for batch in batches:
        own = batch.imported_by == user["username"]
        rows = _filter_rows(grouped[batch.id], scope, matcher, include_unmatched=own)
        if scope is None or own or rows:
            result.append(_summary(batch, rows, scope))
    return result


def unmatched(db, user, batch_id):
    return detail(db, user, batch_id)["skipped"]


def rematch(db, user, batch_id, request=None):
    scope = _authorize(db, user)
    try:
        batch = _batch(db, user, batch_id, lock=True)
        # UPDATE acquires SQLite's writer reservation before reading staging;
        # PostgreSQL holds the batch row lock until the single final commit.
        db.query(NetSuiteImport).filter_by(id=batch.id).update({NetSuiteImport.status: NetSuiteImport.status}, synchronize_session=False)
        stored = _visible_rows(db, batch, scope, CustomerMatcher(db), user)
        _apply(db, batch, stored, user, scope)
        _audit_batch(db, user, batch, "netsuite_import.rematch", request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return detail(db, user, batch.id)
