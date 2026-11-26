"""Import Red Hat account-level opportunity observations without creating customers."""

import hashlib
import io
import json
import math
import zipfile
from datetime import date, datetime
from pathlib import PurePath

import openpyxl
from fastapi import HTTPException
from sqlalchemy.orm import load_only

from backend.models.redhat_opportunity_import import RedHatOpportunityImport, RedHatOpportunityRow
from backend.models.use_case import Customer, User
from backend.services import sales_access
from backend.services.customer_access import read_or_404
from backend.services.customer_match import CustomerMatcher
from backend.services.membership_service import _audit
from backend.upload_size import read_upload_bytes

MAX_ROWS = 20000
MAX_COLUMNS = 200
MAX_UNCOMPRESSED = 100 * 1024 * 1024

OPPORTUNITY_TYPES = (
    ("rhel_clone_replace", "RHEL Clone Replace", ("RHEL CLONE?", "HAS COMPETITIVE LINUX"), {
        "Rocky Linux": ("ROCKY LINUX",), "Oracle Linux": ("ORACLE LINUX",), "Ubuntu": ("UBUNTU",),
        "CentOS": ("CENTOS",), "Amazon Linux 2": ("AMAZON LINUX 2",),
        "AlmaLinux": ("ALMALINUX",), "SUSE": ("SUSE",),
    }),
    ("openshift_virtualization", "OpenShift Virtualization", ("OCPV PLAY",), {
        "VMware Tanzu": ("TANZU ANY", "TANZU VMWARE TANZU", "TANZU SALT", "TANZU GEMFIRE",
                         "TANZU KUBERNETES GRID INTEGRATED", "TANZU APPLICATION SERVICE",
                         "TANZU SERVICE MESH", "TANZU CLOUDHEALTH"),
        "Nutanix": ("NUTANIX ANY",),
        "VMware": ("VMWARE ANY EX TANZU", "VMWARE ESXI", "VMWARE VSPHERE", "VMWARE VCENTER",
                   "VMWARE NSX", "VMWARE VSAN", "VMWARE VCF", "VMWARE VREALIZE ARIA"),
    }),
    ("ansible_network_automation", "Ansible Network Automation", ("NETWORKING PLAY",), {
        "Cisco": ("EOL MERAKI ANY", "EOL MERAKI MR", "EOL MERAKI MX", "EOL MERAKI MS",
                  "EOL CATALYST 2960", "EOL CATALYST 3650", "EOL NEXUS 9000", "EOL NEXUS 3000", "EOL CISCO NXOS"),
        "F5": ("EOL F5 BIGIP ANY", "EOL F5 ISERIES"),
        "Palo Alto Networks": ("EOL PAN CN SERIES", "EOL PAN PA3200", "EOL PAN GLOBALPROTECT",
                               "EOL PAN PRISMA ACCESS", "EOL PAN PANOS"),
    }),
)
OPPORTUNITY_FIELDS = frozenset(key for _, _, triggers, vendors in OPPORTUNITY_TYPES
                               for key in (*triggers, *(field for fields in vendors.values() for field in fields)))


def _yes(value):
    return value is True or (isinstance(value, str) and value.strip().lower() in {"y", "yes", "true", "1"}) or (
        isinstance(value, (int, float)) and value == 1)


def opportunity_cards(rows):
    cards = []
    for key, title, triggers, vendors in OPPORTUNITY_TYPES:
        seen_vendors, representatives = set(), set()
        active = False
        for row in rows:
            fields = json.loads(row.fields_json)
            positives = {vendor for vendor, names in vendors.items() if any(_yes(fields.get(name)) for name in names)}
            if positives or any(_yes(fields.get(name)) for name in triggers):
                active = True
                seen_vendors.update(positives)
                if row.redhat_owner and row.redhat_owner.strip():
                    representatives.add(row.redhat_owner.strip())
        if active:
            cards.append({"type": key, "title": title, "vendors": sorted(seen_vendors),
                          "redhat_representatives": sorted(representatives)})
    return cards


def _cell(value):
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        value = value.strip()
        return None if not value or value in {"#REF!", "#N/A", "#VALUE!", "#DIV/0!", "#NAME?", "#NUM!", "#NULL!"} else value
    return value if isinstance(value, (bool, int, float)) else str(value)


def parse_workbook(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_UNCOMPRESSED:
                raise HTTPException(413, "Workbook expands beyond the allowed size")
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        try:
            matches = []
            for sheet in workbook:
                if sheet.max_column > MAX_COLUMNS or sheet.max_row > MAX_ROWS + 10:
                    raise HTTPException(422, "Workbook exceeds the row or column limit")
                for row_number, row in enumerate(sheet.iter_rows(max_row=10, values_only=True), 1):
                    headers = [str(v).strip().upper() if v is not None else "" for v in row]
                    if "ACCOUNT NAME" in headers and "ACCOUNT OWNER" in headers:
                        matches.append((sheet, row_number, headers))
            if len(matches) != 1:
                raise HTTPException(422, "Workbook must contain one account report with ACCOUNT NAME and ACCOUNT OWNER headers")
            sheet, header_row, headers = matches[0]
            nonempty = [h for h in headers if h]
            if len(nonempty) != len(set(nonempty)):
                raise HTTPException(422, "Workbook contains duplicate column names")
            account_index, owner_index = headers.index("ACCOUNT NAME"), headers.index("ACCOUNT OWNER")
            rows = []
            for source_row, values in enumerate(sheet.iter_rows(min_row=header_row + 1, values_only=True), header_row + 1):
                account = _cell(values[account_index])
                if account is None:
                    continue
                if not isinstance(account, str) or len(account) > 255:
                    raise HTTPException(422, "Workbook contains an invalid account name")
                owner = _cell(values[owner_index])
                if owner is not None and (not isinstance(owner, str) or len(owner) > 255):
                    raise HTTPException(422, "Workbook contains an invalid Red Hat representative")
                fields = {header: _cell(values[i]) for i, header in enumerate(headers)
                          if header in OPPORTUNITY_FIELDS}
                rows.append((source_row, account, owner, fields))
            if not rows:
                raise HTTPException(422, "Workbook contains no account rows")
            return rows
        finally:
            workbook.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "Unable to read the opportunity workbook") from exc


async def import_workbook(db, upload, user, request=None):
    name = PurePath((upload.filename or "").replace("\\", "/")).name
    if not name.lower().endswith(".xlsx"):
        raise HTTPException(422, "Select an .xlsx workbook")
    data = await read_upload_bytes(upload)
    rows = parse_workbook(data)
    matcher = CustomerMatcher(db)
    scope = None if sales_access.is_unrestricted(user) else sales_access.customer_scope(user, db)
    matched, skipped = [], []
    for source_row, account, owner, fields in rows:
        customer, method = matcher.resolve(account)
        if customer is None or (scope is not None and customer.id not in scope):
            suggestion = matcher.suggest(account, scope)
            skipped.append({"source_row": source_row, "account": account,
                            "reason": "No unambiguous accessible customer name or alias",
                            "suggestion": suggestion})
            continue
        matched.append((source_row, account, owner, fields, customer.id, method))
    batch = RedHatOpportunityImport(file_name=name[:255], file_sha256=hashlib.sha256(data).hexdigest(),
        file_data=data, imported_by=user["username"], total_rows=len(rows), matched_rows=len(matched),
        matched_accounts=len({r[4] for r in matched}), unmatched_json=json.dumps(skipped, ensure_ascii=False))
    try:
        db.add(batch)
        db.flush()
        db.add_all([RedHatOpportunityRow(import_id=batch.id, customer_id=cid, source_row=source_row,
            source_account=account, redhat_owner=owner, matched_by=method,
            fields_json=json.dumps(fields, ensure_ascii=False))
            for source_row, account, owner, fields, cid, method in matched])
        actor = db.query(User).filter_by(username=user["username"]).first()
        _audit(db, actor, "redhat_opportunity.import", None, batch.id,
               {"total_rows": len(rows), "matched_rows": len(matched), "matched_accounts": batch.matched_accounts}, request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"import_id": batch.id, "total_rows": len(rows), "matched_rows": len(matched),
            "matched_accounts": batch.matched_accounts, "skipped": skipped}


def history(db, user):
    query = db.query(RedHatOpportunityImport).options(load_only(
        RedHatOpportunityImport.id, RedHatOpportunityImport.file_name, RedHatOpportunityImport.created_at,
        RedHatOpportunityImport.imported_by, RedHatOpportunityImport.total_rows,
        RedHatOpportunityImport.matched_rows, RedHatOpportunityImport.matched_accounts))
    if not sales_access.is_unrestricted(user):
        query = query.filter(RedHatOpportunityImport.imported_by == user["username"])
    return [{"import_id": batch.id, "file_name": batch.file_name, "created_at": batch.created_at.isoformat(),
             "imported_by": batch.imported_by, "total_rows": batch.total_rows,
             "matched_rows": batch.matched_rows, "matched_accounts": batch.matched_accounts}
            for batch in query.order_by(RedHatOpportunityImport.id.desc()).limit(100).all()]


def unmatched_report(db, user, batch_id):
    batch = db.query(RedHatOpportunityImport).options(load_only(
        RedHatOpportunityImport.id, RedHatOpportunityImport.imported_by,
        RedHatOpportunityImport.unmatched_json)).filter_by(id=batch_id).first()
    if batch is None or (not sales_access.is_unrestricted(user) and batch.imported_by != user["username"]):
        raise HTTPException(404, "Import not found")
    rows = json.loads(batch.unmatched_json)
    scope = None if sales_access.is_unrestricted(user) else sales_access.customer_scope(user, db)
    ids = {row["suggestion"]["customer_id"] for row in rows if row.get("suggestion")}
    names = dict(db.query(Customer.id, Customer.name).filter(Customer.id.in_(ids)).all()) if ids else {}
    for row in rows:
        suggestion = row.get("suggestion")
        if suggestion:
            cid = suggestion["customer_id"]
            if cid not in names or (scope is not None and cid not in scope):
                row["suggestion"] = None
            else:
                suggestion["customer_name"] = names[cid]
    return rows


def customer_report(db, user, customer_id):
    customer = read_or_404(db, user, customer_id)
    batch_id = db.query(RedHatOpportunityRow.import_id).filter_by(customer_id=customer_id).order_by(
        RedHatOpportunityRow.import_id.desc()).limit(1).scalar()
    if batch_id is None:
        return {"import": None, "matched_account": customer.name, "opportunities": []}
    batch = db.query(RedHatOpportunityImport.id, RedHatOpportunityImport.file_name,
                     RedHatOpportunityImport.created_at).filter_by(id=batch_id).one()
    rows = db.query(RedHatOpportunityRow).filter_by(customer_id=customer_id, import_id=batch_id).order_by(
        RedHatOpportunityRow.source_row, RedHatOpportunityRow.id).all()
    return {"import": {"import_id": batch.id, "file_name": batch.file_name,
                       "created_at": batch.created_at.isoformat()},
            "matched_account": customer.name, "opportunities": opportunity_cards(rows)}
