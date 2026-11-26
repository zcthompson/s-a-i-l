"""Deterministic RVTools parsing, transactional inventory import and scoped reads."""

import hashlib
import io
import math
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime

import openpyxl
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models.customer_knowledge import STATUS_READY, CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import _wire
from backend.models.rvtools_import import RvToolsHost, RvToolsImport, RvToolsLicense, RvToolsVM
from backend.models.use_case import Customer, User
from backend.services import record_cleanup, sales_access
from backend.services.customer_knowledge_service import (
    create_customer_knowledge,
    delete_customer_knowledge,
)
from backend.services.customer_match import CustomerMatcher
from backend.services.membership_service import _audit
from backend.upload_size import read_upload_bytes

TECH_SOURCE_PREFIX = "rvtools import #"
NO_MATCH = "No matching customer name or alias"
HOST_TEXT = {
    "host_name": "Host", "datacenter": "Datacenter", "cluster": "Cluster",
    "config_status": "Config status", "cpu_model": "CPU Model", "evc_mode": "Current EVC",
    "vendor": "Vendor", "model": "Model", "service_tag": "Service tag",
}
HOST_INTS = {
    "cpu_mhz": ("Speed",), "sockets": ("# CPU",), "cores_per_socket": ("Cores per CPU",),
    "cores": ("# Cores",), "memory_mb": ("# Memory (MB)", "# Memory"),
    "nics": ("# NICs",), "hbas": ("# HBAs",), "vm_count": ("# VMs total", "# VMs"),
    "vcpu_count": ("# vCPUs",),
}
HOST_BOOLS = {
    "maintenance_mode": "in Maintenance Mode", "vmotion": "VMotion support",
    "storage_vmotion": "Storage VMotion support",
}
VM_TEXT = {
    "name": "VM", "power_state": "Powerstate", "host": "Host", "cluster": "Cluster",
    "datacenter": "Datacenter", "primary_ip": "Primary IP Address",
}
VM_INTS = {
    "cpus": ("CPUs",), "memory_mb": ("Memory (MB)", "Memory"), "disks": ("Disks",),
    "disk_capacity_mib": ("Total disk capacity MiB",),
}
# Ordered, explicit category rules: vCenter management, vSAN storage,
# vSphere/ESXi virtualization. Unrecognized licenses remain other.
LICENSE_CATEGORIES = (
    ("vsan", "storage"), ("vcenter", "management_tool"),
    ("vsphere", "virtualization"), ("esxi", "virtualization"),
)


def _text(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value).strip() or None


def _norm(value):
    return " ".join((value or "").casefold().split())


def _first(row, *headers):
    # These are documented aliases across RVTools releases, never positions.
    return next((row[h] for h in headers if h in row and _text(row[h]) is not None), None)


def _integer(value):
    try:
        number = float(str(value).replace(",", "").strip())
        return int(number) if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _boolean(value):
    value = _norm(_text(value))
    if value in {"true", "yes", "1"}:
        return True
    if value in {"false", "no", "0"}:
        return False
    return None


def _datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _rows(workbook, sheet, identity=None):
    if sheet not in workbook.sheetnames:
        return []
    iterator = workbook[sheet].iter_rows(values_only=True)
    header = next(iterator, ())
    names = [(index, _text(name)) for index, name in enumerate(header) if _text(name)]
    rows = []
    for values in iterator:
        if not any(_text(value) is not None for value in values):
            continue
        row = {name: values[index] if index < len(values) else None for index, name in names}
        # RVTools can append aggregate footer rows with an empty identity cell.
        # A genuinely absent column still maps to NULL, as required by the contract.
        if identity in row and _text(row[identity]) is None:
            continue
        rows.append(row)
    return rows


def _summary_metrics(hosts, vms):
    """Only present totals when every source row has a usable value."""
    metrics = {}
    coverage = {}
    for key, rows, field, scale in (
        ("total_cores", hosts, "cores", 1),
        ("total_memory_gb", hosts, "memory_mb", 1024),
        ("total_vcpus", vms, "cpus", 1),
        ("total_vm_memory_gb", vms, "memory_mb", 1024),
    ):
        values = [row.get(field) for row in rows]
        known = sum(value is not None and value >= 0 for value in values)
        coverage[key] = {"known": known, "total": len(values)}
        metrics[key] = (round(sum(values) / scale, 1) if scale != 1 else sum(values)) if values and known == len(values) else None
    states = [_norm(row.get("power_state")) for row in vms]
    known_states = {"poweredon", "poweredoff", "suspended"}
    known = sum(state in known_states for state in states)
    coverage["powered_on_vms"] = {"known": known, "total": len(states)}
    metrics["powered_on_vms"] = sum(state == "poweredon" for state in states) if states and known == len(states) else None
    metrics["coverage"] = coverage
    return metrics


def _stored_summary(db, batch):
    hosts = [{"cores": cores, "memory_mb": memory} for cores, memory in db.query(
        RvToolsHost.cores, RvToolsHost.memory_mb).filter_by(import_id=batch.id).all()]
    vms = [{"cpus": cpus, "memory_mb": memory, "power_state": power} for cpus, memory, power in db.query(
        RvToolsVM.cpus, RvToolsVM.memory_mb, RvToolsVM.power_state).filter_by(import_id=batch.id).all()]
    return {**(batch.summary or {}), **_summary_metrics(hosts, vms)}


def _parse_workbook(workbook):
    missing = [name for name in ("vHost", "vInfo") if name not in workbook.sheetnames]
    if missing:
        raise HTTPException(422, f"Missing required sheets: {', '.join(missing)}")
    hosts = []
    for row in _rows(workbook, "vHost", "Host"):
        match = re.search(r"ESXi (\d+\.\d+(?:\.\d+)?)", _text(row.get("ESX Version")) or "")
        hosts.append({
            **{attr: _text(row.get(header)) for attr, header in HOST_TEXT.items()},
            **{attr: _integer(_first(row, *headers)) for attr, headers in HOST_INTS.items()},
            **{attr: _boolean(row.get(header)) for attr, header in HOST_BOOLS.items()},
            "esxi_version": match.group(1) if match else None,
        })
    if not hosts:
        raise HTTPException(400, "RVTools report contains no vHost data rows")
    vms = []
    vcenter_version = None
    for row in _rows(workbook, "vInfo", "VM"):
        server_type = _text(row.get("VI SDK Server type"))
        if vcenter_version is None and server_type and "vcenter" in server_type.lower():
            vcenter_version = re.split(r"\s+build-", server_type, maxsplit=1, flags=re.I)[0]
        path = re.match(r"^\[([^\]]+)\]", _text(row.get("Path")) or "")
        vms.append({
            **{attr: _text(row.get(header)) for attr, header in VM_TEXT.items()},
            **{attr: _integer(_first(row, *headers)) for attr, headers in VM_INTS.items()},
            "guest_os": _text(_first(row, "OS according to the VMware Tools",
                                      "OS according to the configuration file")),
            "datastore": path.group(1) if path else None,
        })
    metadata = next(iter(_rows(workbook, "vMetaData")), {})
    clusters = [{
        "name": _text(row.get("Name")), "hosts": _integer(row.get("NumHosts")),
        "cpu_cores": _integer(row.get("NumCpuCores")),
        "cpu_threads": _integer(row.get("NumCpuThreads")),
        "memory_mb": _integer(_first(row, "TotalMemory (MB)", "TotalMemory")),
        "ha": _boolean(row.get("HA enabled")),
    } for row in _rows(workbook, "vCluster", "Name")]
    datastores = [{
        "name": _text(row.get("Name")), "type": _text(row.get("Type")),
        "capacity_mib": _integer(row.get("Capacity MiB")),
        "used_mib": _integer(row.get("In Use MiB")),
        "free_mib": _integer(row.get("Free MiB")),
        "host_count": _integer(row.get("# Hosts")),
    } for row in _rows(workbook, "vDatastore", "Name")]
    licenses = [{
        "name": _text(row.get("Name")), "cost_unit": _text(row.get("Cost Unit")),
        "total": _integer(row.get("Total")), "used": _integer(row.get("Used")),
        "expiration": _text(row.get("Expiration Date")), "features": _text(row.get("Features")),
    } for row in _rows(workbook, "vLicense", "Name")]
    datacenters = sorted({row["datacenter"] for row in hosts + vms if row["datacenter"]})
    return {
        "hosts": hosts, "vms": vms, "licenses": licenses,
        "rvtools_version": _text(metadata.get("RVTools version")),
        "collection_at": _datetime(metadata.get("xlsx creation datetime")),
        "vcenter": _text(metadata.get("Server")), "vcenter_version": vcenter_version,
        "host_count": len(hosts), "vm_count": len(vms),
        "datastore_count": len(datastores), "license_count": len(licenses),
        "datacenters": datacenters, "clusters": clusters, "datastores": datastores,
        "esxi_versions": sorted({row["esxi_version"] for row in hosts if row["esxi_version"]}),
        "guest_os_summary": dict(sorted(Counter(vm["guest_os"] for vm in vms
                                                if vm["guest_os"]).items())),
        "summary": {
            **_summary_metrics(hosts, vms),
            "datacenter_count": len(datacenters), "cluster_count": len(clusters),
        },
    }


def parse_workbook(data):
    """Only return allowlisted fields; workbook errors never echo cell contents."""
    try:
        with io.BytesIO(data) as stream:
            workbook = openpyxl.load_workbook(stream, read_only=True, data_only=True)
            try:
                return _parse_workbook(workbook)
            finally:
                workbook.close()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Invalid RVTools workbook") from None


def _tech_source(import_id):
    return f"{TECH_SOURCE_PREFIX}{import_id}"


def _technology_specs(batch, hosts, licenses):
    collection = _wire(batch.collection_at) or "unknown"
    base_notes = f"File: {batch.file_name}; collection: {collection}"
    specs = []

    def add(name, category, quantity, count_label, **extra):
        specs.append({"name": name, "category": category, "quantity": quantity,
                      "notes": f"{base_notes}; {count_label}", **extra})

    for version in batch.esxi_versions:
        count = sum(host.esxi_version == version for host in hosts)
        add(f"VMware ESXi {version}", "virtualization", count, f"{count} hosts",
            vendor="VMware", version_edition=version, footprint=f"{count} hosts")
    if batch.vcenter_version:
        version = re.search(r"vCenter Server\s+(\d+(?:\.\d+)*)", batch.vcenter_version, re.I)
        add(batch.vcenter_version, "management_tool", 1, "1 vCenter", vendor="VMware",
            version_edition=version.group(1) if version else None, footprint=batch.vcenter)
    hardware = Counter((host.vendor, host.model) for host in hosts if host.vendor or host.model)
    for (vendor, model), count in sorted(hardware.items(), key=lambda item: (
        item[0][0] or "", item[0][1] or "",
    )):
        name = model if model and vendor and _norm(model).startswith(_norm(vendor)) else " ".join(
            part for part in (vendor, model) if part
        )
        add(name, "hardware", count, f"{count} hosts", vendor=vendor, footprint=f"{count} hosts")
    grouped = defaultdict(list)
    for license in licenses:
        if license.name:
            grouped[_norm(license.name)].append(license)
    for key, rows in sorted(grouped.items()):
        totals = [row.total for row in rows if row.total is not None]
        quantity = sum(totals) if totals else None
        category = next((category for token, category in LICENSE_CATEGORIES if token in key), "other")
        details = []
        for row in rows:
            first_feature = re.split(r"[;|\r\n]", row.features or "", maxsplit=1)[0]
            details.append(f"expiration: {row.expiration or 'unknown'}; features: {first_feature}")
        add(rows[0].name, category, quantity,
            f"{len(rows)} license rows; total: {quantity}; {'; '.join(details)}")
    for os_name, count in sorted(batch.guest_os_summary.items()):
        category = "operating_system" if re.search(
            r"windows|linux|solaris|unix|vmware|netware|photon|esxi", os_name, re.I,
        ) else "other"
        add(os_name, category, count, f"{count} VMs", footprint=f"{count} VMs")
    return specs


def _technology_rows(db, batch, hosts, licenses):
    existing = {}
    # A manual row takes precedence even if legacy duplicates already exist.
    for record in db.query(CustomerTechnology).filter_by(customer_id=batch.customer_id).order_by(
        CustomerTechnology.id,
    ).all():
        key = _norm(record.name)
        if key not in existing or not (record.source or "").startswith(TECH_SOURCE_PREFIX):
            existing[key] = record
    created = refreshed = 0
    seen = set()
    for spec in _technology_specs(batch, hosts, licenses):
        key = _norm(spec["name"])
        if key in seen:
            continue
        seen.add(key)
        record = existing.get(key)
        if record is not None and not (record.source or "").startswith(TECH_SOURCE_PREFIX):
            continue
        if record is None:
            record = CustomerTechnology(customer_id=batch.customer_id)
            db.add(record)
            created += 1
        else:
            refreshed += 1
        # Refresh the complete derived footprint as well as its provenance.
        for attr in ("name", "category", "quantity", "vendor", "version_edition", "footprint", "notes"):
            setattr(record, attr, spec.get(attr))
        record.source = _tech_source(batch.id)
        record.date_observed = batch.created_at.date()
        record.verification_state = "verified"
    db.flush()
    return created, refreshed, _technologies(db, batch)


def _technologies(db, batch):
    return sorted({name for (name,) in db.query(CustomerTechnology.name).filter(
        CustomerTechnology.customer_id == batch.customer_id,
        CustomerTechnology.source == _tech_source(batch.id),
    ).all()})


def _cell(value):
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _markdown(customer, batch, hosts, licenses, technologies):
    lines = [
        f"# RVTools Report — {_cell(customer.name)}", "",
        f"Source: {_cell(batch.file_name)}; RVTools import #{batch.id}; "
        f"collection: {_wire(batch.collection_at) or 'unknown'}", "",
        "## Overview", "",
        f"- Hosts: {batch.host_count}; VMs: {batch.vm_count}; "
        f"datastores: {batch.datastore_count}; licenses: {batch.license_count}",
        f"- vCenter: {_cell(batch.vcenter)}; version: {_cell(batch.vcenter_version)}",
        f"- ESXi versions: {', '.join(batch.esxi_versions)}",
    ]
    lines.extend(f"- {key}: {value if value is not None else 'unavailable (incomplete source data)'}"
                 for key, value in batch.summary.items() if key != "coverage")

    def table(title, headers, rows):
        lines.extend(["", f"## {title}", "", "| " + " | ".join(headers) + " |",
                      "|" + "|".join("---" for _ in headers) + "|"])
        lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)

    table("Clusters", ["Name", "Hosts", "CPU cores", "CPU threads", "Memory MB", "HA"],
          (row.values() for row in batch.clusters))
    table("Hosts", ["Name", "Datacenter", "Cluster", "Model", "CPU", "Cores", "RAM MB", "VMs", "ESXi"],
          ((h.host_name, h.datacenter, h.cluster, h.model, h.cpu_model, h.cores, h.memory_mb,
            h.vm_count, h.esxi_version) for h in hosts))
    table("Datastores", ["Name", "Type", "Capacity MiB", "Used MiB", "Free MiB", "Hosts"],
          (row.values() for row in batch.datastores))
    table("Licenses", ["Name", "Cost unit", "Total", "Used", "Expiration", "Features"],
          ((row.name, row.cost_unit, row.total, row.used, row.expiration, row.features) for row in licenses))
    table("Guest OS counts", ["OS", "VMs"], sorted(batch.guest_os_summary.items()))
    lines.extend(["", "## Technologies recorded", "", *[f"- {_cell(name)}" for name in technologies], ""])
    return "\n".join(lines)


def _customer(db, name, customer_ids):
    customer = db.query(Customer).filter(Customer.name == name).first()
    if customer is None or (customer_ids is not None and customer.id not in customer_ids):
        raise HTTPException(404, "Customer not found")
    return customer


def _target(db, user, customer_name):
    """Resolve the import target to an EXISTING customer by name or alias.

    Part 14 import remediation (operator rules 2026-11-01): the target is a
    customer name OR alias, case-insensitive; imports never create a customer
    (the former new-temporary-customer path is removed). A workbook is one
    customer, so a target that does not resolve refuses the file — missing,
    ambiguous and out-of-scope are the same 404 (no existence oracle).
    """
    customer, matched_by = CustomerMatcher(db).resolve(customer_name)
    # Central CAP_INTEL_UPLOADS write basis (Part 13 DV wave — DV11, ruling
    # R1): scope via customer_scope (404-first), then the intel-upload
    # capability gate — aligned with the rep-intelligence path.
    if customer is None or (user.get("is_admin") != 1
                            and customer.id not in sales_access.customer_scope(user, db)):
        raise HTTPException(404, NO_MATCH)
    if not sales_access.can(user, db, sales_access.CAP_INTEL_UPLOADS, customer.id,
                            section="intel_uploads"):
        raise HTTPException(403, "Not authorized to modify this customer")
    return customer, matched_by


def _audit_import(db, user, action, batch, request, extra=None):
    actor = db.query(User).filter(User.username == user["username"]).first()
    _audit(db, actor, action, batch.customer_id, batch.id, {
        "import_id": batch.id, "file_name": batch.file_name,
        "host_count": batch.host_count, "vm_count": batch.vm_count,
        "datastore_count": batch.datastore_count, "license_count": batch.license_count,
        **(extra or {}),
    }, request)


async def import_rvtools(db, upload, user, customer_name=None, request=None):
    if not _text(customer_name):
        raise HTTPException(422, "Provide a customer name or alias")
    filename = upload.filename or ""
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Only .xlsx or .xlsm RVTools reports are accepted")
    data = await read_upload_bytes(upload)
    parsed = parse_workbook(data)
    host_values, vm_values, license_values = (parsed.pop(key) for key in ("hosts", "vms", "licenses"))
    now = datetime.now(UTC)
    try:
        customer, matched_by = _target(db, user, customer_name)
        batch = RvToolsImport(
            customer_id=customer.id, file_name=filename, file_sha256=hashlib.sha256(data).hexdigest(),
            file_data=data, imported_by=user["username"], created_at=now,
            created_customer=False, **parsed,
        )
        db.add(batch)
        db.flush()
        hosts = [RvToolsHost(import_id=batch.id, created_at=now, **row) for row in host_values]
        vms = [RvToolsVM(import_id=batch.id, created_at=now, **row) for row in vm_values]
        licenses = [RvToolsLicense(import_id=batch.id, created_at=now, **row) for row in license_values]
        db.add_all(hosts + vms + licenses)
        db.flush()
        created, refreshed, technologies = _technology_rows(db, batch, hosts, licenses)
        # D4 reconciliation: the original workbook (license keys, serial
        # numbers, UUIDs, BIOS strings) is retained ONLY on
        # rvtools_imports.file_data — a provenance column no API serves.
        # The knowledge document stores the sanitized Markdown rendering
        # (never the original bytes), so its /download cannot leak keys.
        markdown = _markdown(customer, batch, hosts, licenses, technologies)
        customer_id = customer.id
        # CRUD commits are confined to savepoints on the outer transaction.
        with Session(bind=db.connection(), join_transaction_mode="create_savepoint") as knowledge_db:
            document = create_customer_knowledge(
                knowledge_db, customer_id, "rvtools_report", filename + ".rvtools.md",
                markdown.encode("utf-8"),
                knowledge_category="infrastructure",
            )
            document.normalized_content = markdown
            document.processing_status = STATUS_READY
            document.processed = 1
            document.processor = "rvtools-import"
            document.processor_version = "rvtools-summary/2"
            document.processed_at = now
            document.ingested_at = now
            document.ingestion_status = "ready"
            document.classification = f"rvtools_import:{batch.id}"
            knowledge_db.commit()
        _audit_import(db, user, "rvtools_import.create", batch, request, {
            "technologies_created": created, "technologies_refreshed": refreshed,
        })
        response = {**_detail(db, batch), "matched_by": matched_by}
        db.commit()
        return response
    except Exception:
        db.rollback()
        raise


def _get_import(db, import_id, customer_ids=None):
    batch = db.get(RvToolsImport, import_id)
    if batch is None or (customer_ids is not None and batch.customer_id not in customer_ids):
        raise HTTPException(404, "Import not found")
    return batch


def _detail(db, batch, vm_limit=100, vm_offset=0):
    vm_limit = max(1, min(vm_limit, 500))
    vm_offset = max(0, vm_offset)
    hosts = db.query(RvToolsHost).filter_by(import_id=batch.id).order_by(RvToolsHost.id).all()
    licenses = db.query(RvToolsLicense).filter_by(import_id=batch.id).order_by(RvToolsLicense.id).all()
    vms = db.query(RvToolsVM).filter_by(import_id=batch.id).order_by(RvToolsVM.id).offset(
        vm_offset,
    ).limit(vm_limit).all()
    return {
        **batch.to_dict(), "summary": _stored_summary(db, batch), "customer_name": db.get(Customer, batch.customer_id).name,
        "technologies": _technologies(db, batch), "hosts": [host.to_dict() for host in hosts],
        "licenses": [license.to_dict() for license in licenses], "vms": [vm.to_dict() for vm in vms],
        "vm_total": batch.vm_count, "vm_limit": vm_limit, "vm_offset": vm_offset,
    }


def get_import(db, import_id, customer_ids=None, vm_limit=100, vm_offset=0):
    return _detail(db, _get_import(db, import_id, customer_ids), vm_limit, vm_offset)


def list_imports(db, customer_ids=None):
    query = db.query(RvToolsImport)
    if customer_ids is not None:
        query = query.filter(RvToolsImport.customer_id.in_(customer_ids))
    batches = query.order_by(RvToolsImport.id.desc()).all()
    # ONE batched customer-name lookup (re-recon A-7 — was one query per
    # batch, partially masked by the identity map).
    names = {
        c.id: c.name
        for c in db.query(Customer).filter(
            Customer.id.in_({batch.customer_id for batch in batches})
        )
    } if batches else {}
    rows = []
    for batch in batches:
        fields = batch.to_dict()
        rows.append({key: fields[key] for key in (
            "import_id", "file_name", "customer_id", "created_customer", "host_count", "vm_count",
            "vcenter", "vcenter_version", "esxi_versions", "created_at", "imported_by",
        )} | {"customer_name": names.get(batch.customer_id)})
    return rows


def delete_import(db, import_id, user, customer_ids=None, request=None):
    batch = _get_import(db, import_id, customer_ids)
    try:
        counts = {}
        for key, model in (("hosts", RvToolsHost), ("vms", RvToolsVM), ("licenses", RvToolsLicense)):
            counts[f"deleted_{key}"] = db.query(model).filter_by(import_id=batch.id).delete(
                synchronize_session=False,
            )
        technologies = db.query(CustomerTechnology).filter(
            CustomerTechnology.customer_id == batch.customer_id,
            CustomerTechnology.source == _tech_source(batch.id),
        )
        record_cleanup.technologies(db, [tid for tid, in technologies.with_entities(CustomerTechnology.id)])
        counts["deleted_technologies"] = technologies.delete(synchronize_session=False)
        documents = db.query(CustomerKnowledge).filter(
            CustomerKnowledge.customer_id == batch.customer_id,
            CustomerKnowledge.classification == f"rvtools_import:{batch.id}",
        ).all()
        with Session(bind=db.connection(), join_transaction_mode="create_savepoint") as knowledge_db:
            for document in documents:
                delete_customer_knowledge(knowledge_db, document.id, document.customer_id)
        counts["deleted_knowledge"] = len(documents)
        _audit_import(db, user, "rvtools_import.delete", batch, request, counts)
        db.delete(batch)
        db.commit()
        return {"detail": "Import deleted", **counts, "temp_customer_kept": True}
    except Exception:
        db.rollback()
        raise


def customer_rvtools(db, name, customer_ids=None):
    customer = _customer(db, name, customer_ids)
    batch = db.query(RvToolsImport).filter_by(customer_id=customer.id).order_by(
        RvToolsImport.id.desc(),
    ).first()
    fields = batch.to_dict() if batch else {}
    # An authorized customer with no import gets the dashboard empty state.
    hosts_preview = [host.to_dict() for host in db.query(RvToolsHost).filter_by(
        import_id=batch.id,
    ).order_by(RvToolsHost.id).limit(10).all()] if batch else []
    return {
        "customer_name": customer.name, "import_id": batch.id if batch else None,
        "source_file": batch.file_name if batch else None,
        "imported_at": _wire(batch.created_at) if batch else None,
        **{key: fields.get(key) for key in ("rvtools_version", "vcenter", "vcenter_version")},
        **{key: fields.get(key, 0) for key in ("host_count", "vm_count", "datastore_count", "license_count")},
        **{key: fields.get(key, []) for key in ("esxi_versions", "datacenters", "clusters")},
        "hosts_preview": hosts_preview,
        "guest_os_summary": fields.get("guest_os_summary", {}),
        "summary": _stored_summary(db, batch) if batch else {
            **_summary_metrics([], []),
            "datacenter_count": 0, "cluster_count": 0,
        },
        "technologies": _technologies(db, batch) if batch else [],
    }
