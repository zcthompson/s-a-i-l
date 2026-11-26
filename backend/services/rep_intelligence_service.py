"""Deterministic CSV observations, transactional writes and scoped history."""

import csv
import hashlib
import io
import math
import re
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy import or_

from backend.models.customer_technology import CustomerTechnology
from backend.models.rep_intelligence import RepIntelligenceImport, RepIntelligenceRow
from backend.models.use_case import Customer, User
from backend.services import record_cleanup, sales_access
from backend.services.customer_match import AMBIGUOUS, CustomerMatcher
from backend.services.intelligence_import_service import _norm, _text
from backend.services.membership_service import _audit
from backend.upload_size import read_upload_bytes

TEMPLATE_COLUMNS = (
    "customer_name", "technology_name", "hardware_software", "is_sale", "amount", "currency",
    "vendor", "version", "quantity", "notes",
)
REQUIRED_COLUMNS = TEMPLATE_COLUMNS[:2]
ISSUE_COLUMNS = (
    "row", "customer_name", "technology_name", "field", "reason_code", "severity", "message",
    "disposition",
)
TECH_SOURCE_PREFIX = "generic intelligence import #"
SCOPED_CUSTOMER_MESSAGE = "no matching accessible customer; row skipped"
CUSTOMER_SKIP_CODES = {"customer_unmatched", "customer_ambiguous", "customer_not_accessible"}
PURPOSE_LINES = {
    "yes": "rep-reported sale (not verified as installed or closed-won)",
    "no": "reported as part of the customer's environment (not a sale)",
    None: "environment vs. prospect status not recorded",
}
INVALID_MESSAGES = {
    "hardware_software": "hardware_software must be 'hardware' or 'software'; value omitted",
    "is_sale": "is_sale must be 'yes' or 'no'; value omitted",
    "amount": "amount must be a valid decimal; technology imported with amount unknown",
    "currency": ("currency must be a 3-letter code; omitted (amount retained but excluded "
                 "from comparable totals)"),
    "quantity": "quantity must be a whole number; value omitted",
}


def _csv_bytes(header, rows=()):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _csv_response(data, filename):
    # ASCII fallback plus RFC 5987 preserves Unicode without putting control
    # characters, quotes or path components into an HTTP header.
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    basename = "".join(char for char in basename if char >= " " and char != "\x7f")
    basename = basename or "import.csv"
    fallback = basename.encode("ascii", "replace").decode().replace('"', "_")
    return Response(data, media_type="text/csv", headers={
        "Content-Disposition": (f'attachment; filename="{fallback}"; '
                                f"filename*=UTF-8''{quote(basename, safe='')}"),
    })


def template():
    return _csv_response(_csv_bytes(TEMPLATE_COLUMNS), "sail-account-intelligence-template.csv")


def _parse(data):
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
        reader.fieldnames = [name.strip() for name in (reader.fieldnames or [])]
        missing = [name for name in REQUIRED_COLUMNS if name not in reader.fieldnames]
        if missing:
            raise HTTPException(422, f"Missing required columns: {', '.join(missing)}")
        rows = []
        for raw in reader:
            cells = [cell for value in raw.values()
                     for cell in (value if isinstance(value, list) else [value])]
            if any(_text(cell) for cell in cells):
                rows.append(raw)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise HTTPException(422, f"Invalid CSV: {exc}") from None
    if not rows:
        raise HTTPException(400, "File contains no data rows")
    return rows


def _issue(field, code, severity, message, disposition, **extra):
    return {"field": field, "code": code, "severity": severity, "message": message,
            "disposition": disposition, **extra}


def _validate_optional(row, raw):
    for field, choices in (("hardware_software", {"hardware", "software"}),
                           ("is_sale", {"yes", "no"})):
        value = _text(raw.get(field))
        if value is not None:
            if value.lower() in choices:
                setattr(row, field, value.lower())
            else:
                row.issues.append(_omitted(field, raw[field]))

    value = _text(raw.get("amount"))
    if value is not None:
        cleaned = value.replace("$", "").replace(",", "").strip()
        decimal = re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
                               cleaned)
        amount = float(cleaned) if decimal else None
        if amount is not None and math.isfinite(amount):
            row.amount = amount
        else:
            row.issues.append(_omitted("amount", raw["amount"]))

    value = _text(raw.get("currency"))
    if value is not None:
        if re.fullmatch(r"[A-Z]{3}", value.upper()):
            row.currency = value.upper()
        else:
            row.issues.append(_omitted("currency", raw["currency"]))

    value = _text(raw.get("quantity"))
    if value is not None:
        # SQLite INTEGER is signed 64-bit. Reject unrepresentable input as
        # a field issue instead of aborting otherwise valid observations.
        digits = value.lstrip("+").lstrip("0") or "0"
        if (re.fullmatch(r"\+?[0-9]+", value) and len(digits) <= 19
                and int(digits) <= 2**63 - 1):
            row.quantity = int(digits)
        else:
            row.issues.append(_omitted("quantity", raw["quantity"]))

    row.vendor = _text(raw.get("vendor"))
    row.version = _text(raw.get("version"))
    row.notes = raw.get("notes") if _text(raw.get("notes")) else None


def _omitted(field, value):
    return _issue(field, f"{field}_invalid", "warning", INVALID_MESSAGES[field],
                  "field_omitted", value=value)


def _technology(db, batch, row, existing, now):
    name = _text(row.technology_name_supplied)
    key = (row.customer_id, _norm(name))
    record = existing.get(key)
    if record is not None and not (record.source or "").startswith(TECH_SOURCE_PREFIX):
        row.technology_id = record.id
        row.issues.append(_issue(
            "technology_name", "technology_already_recorded", "info",
            f"technology already recorded (source: {record.source}) — existing record "
            "preserved; row associated with it", "associated",
        ))
        return
    if record is None:
        record = CustomerTechnology(customer_id=row.customer_id, name=name)
        db.add(record)
        existing[key] = record
        batch.technologies_created += 1
    else:
        batch.technologies_refreshed += 1
    # A blank field must not erase previously supplied evidence (sibling rows
    # or an earlier import): last *supplied* value wins, both within a file
    # and across re-uploads (the row records retain the per-row evidence).
    # category is NOT NULL, so a fresh record defaults to the unknown bucket.
    if row.hardware_software is not None:
        record.category = row.hardware_software
    elif record.category is None:
        record.category = "other"
    if row.vendor is not None:
        record.vendor = row.vendor
    if row.version is not None:
        record.version_edition = row.version
    if row.quantity is not None:
        record.quantity = row.quantity
    record.verification_state = "unverified"
    record.source = f"{TECH_SOURCE_PREFIX}{batch.id}"
    record.date_observed = now.date()
    record.notes = (f"Rep observation ({record.source}, row {row.source_row}) — "
                    f"{PURPOSE_LINES[row.is_sale]}")
    if row.notes is not None:
        record.notes += f"; original note: {row.notes}"
    db.flush()
    row.technology_id = record.id


def _audit_import(db, user, action, batch, request, extra=None):
    actor = db.query(User).filter(User.username == user["username"]).first()
    details = batch.to_dict()
    if extra:
        details.update(extra)
    _audit(db, actor, action, None, batch.id, details, request)


async def import_csv(db, upload, user, request=None):
    filename = upload.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")
    data = await read_upload_bytes(upload)
    raw_rows = _parse(data)
    now = datetime.now(UTC)
    batch = RepIntelligenceImport(
        file_name=filename, file_sha256=hashlib.sha256(data).hexdigest(), file_data=data,
        total_rows=len(raw_rows), imported_rows=0, imported_with_issues=0, skipped_rows=0,
        status="failed", technologies_created=0, technologies_refreshed=0,
        imported_by=user["username"], created_at=now,
    )
    try:
        # Part 14 import remediation: rows map to an existing customer by name
        # OR alias, case-insensitive (two fixed queries). A name that equals
        # more than one customer must not silently resolve to whichever
        # appears first — it is skipped as ambiguous.
        matcher = CustomerMatcher(db)
        db.add(batch)
        db.flush()
        existing = {}
        loaded_customers = set()
        for number, raw in enumerate(raw_rows, 1):
            row = RepIntelligenceRow(
                import_id=batch.id, source_row=number,
                customer_name_supplied=raw.get("customer_name"),
                technology_name_supplied=raw.get("technology_name"),
                status="skipped", issues=[], created_at=now,
            )
            for field in REQUIRED_COLUMNS:
                if not _text(raw.get(field)):
                    row.issues.append(_issue(field, f"{field}_required", "error",
                                             f"{field} is required", "row_skipped"))
            if not row.issues:
                customer, outcome = matcher.resolve(raw.get("customer_name"))
                code = message = None
                if customer is None and outcome == AMBIGUOUS:
                    code = "customer_ambiguous"
                    message = "customer name is ambiguous; row skipped"
                elif customer is None:
                    code, message = "customer_unmatched", SCOPED_CUSTOMER_MESSAGE
                elif not sales_access.can(user, db, sales_access.CAP_INTEL_UPLOADS,
                                          customer.id, section="intel_uploads"):
                    code, message = "customer_not_accessible", SCOPED_CUSTOMER_MESSAGE
                if code:
                    row.issues.append(_issue("customer_name", code, "error", message, "row_skipped"))
                else:
                    row.customer_id = customer.id
                    _validate_optional(row, raw)
                    if row.customer_id not in loaded_customers:
                        records = db.query(CustomerTechnology).filter_by(
                            customer_id=row.customer_id,
                        ).order_by(CustomerTechnology.id).all()
                        for record in records:
                            existing.setdefault((record.customer_id, _norm(record.name)), record)
                        loaded_customers.add(row.customer_id)
                    _technology(db, batch, row, existing, now)
                    has_warnings = any(issue["severity"] != "info" for issue in row.issues)
                    row.status = "imported_with_issues" if has_warnings else "imported"
                    batch.imported_rows += 1
                    batch.imported_with_issues += int(has_warnings)
            if row.status == "skipped":
                batch.skipped_rows += 1
            db.add(row)
        if batch.imported_rows:
            batch.status = ("completed_with_issues" if batch.skipped_rows or batch.imported_with_issues
                            else "completed")
        db.flush()
        _audit_import(db, user, "rep_intelligence_import.create", batch, request)
        response = _detail(db, batch, user)
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def _is_importer_or_admin(batch, user):
    return sales_access.is_unrestricted(user) or batch.imported_by == user["username"]


def _readable_customer_ids(db, user, customer_ids):
    if sales_access.is_unrestricted(user):
        return set(customer_ids)
    return {customer_id for customer_id in set(customer_ids)
            if sales_access.can(user, db, sales_access.CAP_READ, customer_id)}


def list_imports(db, user):
    query = db.query(RepIntelligenceImport)
    if not sales_access.is_unrestricted(user):
        # One query of distinct affected customers, never one lookup per row.
        affected = {cid for cid, in db.query(RepIntelligenceRow.customer_id).filter(
            RepIntelligenceRow.customer_id.isnot(None),
        ).distinct().all()}
        readable = _readable_customer_ids(db, user, affected)
        visible_ids = db.query(RepIntelligenceRow.import_id).filter(
            RepIntelligenceRow.customer_id.in_(readable),
        ).distinct()
        query = query.filter(or_(RepIntelligenceImport.imported_by == user["username"],
                                 RepIntelligenceImport.id.in_(visible_ids)))
    return [batch.to_dict() for batch in query.order_by(RepIntelligenceImport.id.desc()).all()]


def _get_import(db, import_id):
    batch = db.get(RepIntelligenceImport, import_id)
    if batch is None:
        raise HTTPException(404, "Import not found")
    return batch


def _detail(db, batch, user):
    rows = db.query(RepIntelligenceRow).filter_by(import_id=batch.id).order_by(
        RepIntelligenceRow.source_row, RepIntelligenceRow.id,
    ).all()
    affected = {row.customer_id for row in rows if row.customer_id is not None}
    readable = _readable_customer_ids(db, user, affected)
    can_manage = _is_importer_or_admin(batch, user)
    if not can_manage and not readable:
        raise HTTPException(404, "Import not found")
    names = dict(db.query(Customer.id, Customer.name).filter(
        Customer.id.in_(readable),
    ).all())
    serialized = []
    for row in rows:
        if row.customer_id is not None and row.customer_id not in readable:
            continue
        values = {**row.to_dict(), "customer_name": names.get(row.customer_id)}
        if row.customer_id is not None:
            # Part 14 (A5b): per-row disposition gains matched_by (additive).
            # Derived read-time: a row matched by name carries a norm-equal
            # supplied name; by A2 an alias can never norm-equal a customer
            # name, so legacy rows read back as "name" as they matched.
            # Skip rows (customer_id NULL) gain nothing — unchanged.
            name_norm = _norm(names.get(row.customer_id))
            values["matched_by"] = (
                "name" if _norm(row.customer_name_supplied) == name_norm else "alias"
            )
        if not can_manage and row.customer_id is None:
            values.update(customer_name_supplied=None)
        serialized.append(values)
    # The import warning count: rows skipped because the customer name did
    # not match a customer name or alias the importer can write to.
    unmatched_customer_rows = sum(
        any(issue["code"] in CUSTOMER_SKIP_CODES for issue in row.issues) for row in rows
    )
    return {
        **batch.to_dict(), "file_sha256": batch.file_sha256, "rows": serialized,
        "unmatched_customer_rows": unmatched_customer_rows,
        "matched": [{"customer_id": cid, "customer_name": names[cid]}
                    for cid in sorted(readable) if cid in names],
        "matched_out_of_scope": len(affected - readable),
        "affected_customer_ids": sorted(readable), "can_manage": can_manage,
    }


def get_import(db, import_id, user):
    return _detail(db, _get_import(db, import_id), user)


def _require_management(db, import_id, user, hide_invisible=False):
    batch = _get_import(db, import_id)
    if not _is_importer_or_admin(batch, user):
        if hide_invisible:
            # Management must match detail visibility before denying (404-first,
            # R4/Q7): an import the caller cannot see is the same 404 as a
            # missing one; a visible import keeps the exact 403.
            _detail(db, batch, user)
        raise HTTPException(403, "Only the importer or system admin may manage this import")
    return batch


def source(db, import_id, user):
    batch = _require_management(db, import_id, user, hide_invisible=True)
    return _csv_response(batch.file_data, batch.file_name)


def _formula_safe(value):
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r")) else value


def issues_csv(db, import_id, user):
    batch = _require_management(db, import_id, user, hide_invisible=True)
    report = []
    for row in _detail(db, batch, user)["rows"]:
        for issue in sorted(row["issues"], key=lambda item: item["field"]):
            values = (
                row["source_row"], row["customer_name_supplied"], row["technology_name_supplied"],
                issue["field"], issue["code"], issue["severity"], issue["message"],
                issue["disposition"],
            )
            report.append([_formula_safe(value) for value in values])
    return _csv_response(_csv_bytes(ISSUE_COLUMNS, report), f"import-{batch.id}-issues.csv")


def delete_import(db, import_id, user, request=None):
    batch = _require_management(db, import_id, user, hide_invisible=True)
    try:
        technologies = db.query(CustomerTechnology).filter(
            CustomerTechnology.source == f"{TECH_SOURCE_PREFIX}{batch.id}",
        )
        # Later imports can retain associations to these inventory ids. Keep
        # their evidence even with SQLite foreign-key enforcement disabled.
        technology_ids = [tid for tid, in technologies.with_entities(CustomerTechnology.id).all()]
        record_cleanup.technologies(db, technology_ids)
        deleted_technologies = technologies.delete(synchronize_session=False)
        deleted_rows = db.query(RepIntelligenceRow).filter_by(import_id=batch.id).delete(
            synchronize_session=False,
        )
        _audit_import(db, user, "rep_intelligence_import.delete", batch, request, {
            "deleted_rows": deleted_rows, "deleted_technologies": deleted_technologies,
        })
        db.delete(batch)
        db.commit()
        return {"detail": "Import deleted", "deleted_rows": deleted_rows,
                "deleted_technologies": deleted_technologies}
    except Exception:
        db.rollback()
        raise
