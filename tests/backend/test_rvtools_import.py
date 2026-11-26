"""RVTools contract: generated workbooks, scoped access and atomic lifecycle."""

import hashlib
import io
import json
import re
from datetime import date, datetime
from urllib.parse import quote
from zipfile import ZIP_STORED, ZipFile, ZipInfo

import openpyxl
import pytest
from backend.models.collaboration import AuditLog
from backend.models.customer_alias import CustomerAlias
from backend.models.customer_knowledge import CustomerKnowledge, CustomerKnowledgeItem
from backend.models.customer_technology import CustomerTechnology
from backend.models.rvtools_import import RvToolsHost, RvToolsImport, RvToolsLicense, RvToolsVM
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import rvtools_import_service as service
from backend.services.customer_knowledge_service import create_customer_knowledge

from tests.backend.common import _headers

BASE = "/api/rvtools-import/"
SENSITIVE = ["SECRET-LICENSE-KEY", "SECRET-SERIAL", "SECRET-UUID", "SECRET-BIOS-VENDOR",
             "SECRET-BIOS-VERSION", "SECRET-OEM", "SECRET-ASSIGNED-LICENSE", "SECRET-CUSTOM-PII"]
HOST_FIELDS = {
    "id", "host_name", "datacenter", "cluster", "config_status", "maintenance_mode", "cpu_model",
    "cpu_mhz", "sockets", "cores_per_socket", "cores", "memory_mb", "nics", "hbas", "vm_count",
    "vcpu_count", "vmotion", "storage_vmotion", "evc_mode", "esxi_version", "vendor", "model", "service_tag",
}
VM_FIELDS = {
    "id", "name", "power_state", "cpus", "memory_mb", "disks", "disk_capacity_mib", "guest_os",
    "host", "cluster", "datacenter", "datastore", "primary_ip",
}
LICENSE_FIELDS = {"id", "name", "cost_unit", "total", "used", "expiration", "features"}
DETAIL_FIELDS = {
    "import_id", "file_name", "created_at", "imported_by", "customer_id", "customer_name",
    "created_customer", "rvtools_version", "collection_at", "vcenter", "vcenter_version", "host_count",
    "vm_count", "datastore_count", "license_count", "datacenters", "esxi_versions", "clusters",
    "datastores", "guest_os_summary", "summary", "technologies", "hosts", "licenses", "vms",
    "vm_total", "vm_limit", "vm_offset",
}


def _xlsx(sheets):
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.active)
    workbook.properties.created = datetime(2026, 1, 2, 3, 4, 5)
    workbook.properties.modified = datetime(2026, 1, 2, 3, 4, 5)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    raw = io.BytesIO()
    workbook.save(raw)
    workbook.close()
    # ZIP member timestamps are fixed too; fixture bytes do not depend on
    # time. Members are re-written UNCOMPRESSED (ZIP_STORED), and
    # docProps/core.xml's dcterms:modified is normalized: openpyxl stamps
    # the wall-clock save time there (the properties.modified pin above is
    # overwritten at save time), so without this a pair of constructions
    # straddling a second boundary produced different bytes (the 2026-10-25
    # CI flake — two consecutive _xlsx() calls differing only in the
    # modified stamp). Fixture bytes must depend only on fixture content.
    result = io.BytesIO()
    with ZipFile(raw) as source, ZipFile(result, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name == "docProps/core.xml":
                data = re.sub(
                    rb"<dcterms:modified[^>]*>[^<]*</dcterms:modified>",
                    b'<dcterms:modified xsi:type="dcterms:W3CDTF">2026-01-02T03:04:05Z</dcterms:modified>',
                    data,
                )
            target.writestr(ZipInfo(name, (2026, 1, 2, 3, 4, 6)), data,
                            compress_type=ZIP_STORED)
    return result.getvalue()


@pytest.fixture()
def full_sheets():
    host_headers = [
        " Host ", "Datacenter", "Cluster", "Config status", "in Maintenance Mode", "CPU Model",
        "Speed", "# CPU", "Cores per CPU", "# Cores", "# Memory (MB)", "# NICs", "# HBAs",
        "# VMs total", "# vCPUs", "VMotion support", "Storage VMotion support", "Current EVC",
        "ESX Version", "Vendor", "Model", "Service tag", None, "Serial number", "UUID",
        "BIOS Vendor", "BIOS Version", "OEM specific string", "Assigned License(s)",
    ]
    host_a = [
        "esx-a", "DC-A", "Cluster-A", "green", False, "Xeon", 2400, 2, 8, 16, 65536, 4, 2, 2, 6,
        True, "true", "Broadwell", "VMware ESXi 6.7.0 build-20497097", "HPE", "ProLiant DL360 Gen10",
        "allowed-service-tag", "ignored", *SENSITIVE[1:7],
    ]
    host_b = host_a.copy()
    host_b[0] = "esx-b"
    host_b[4] = "yes"
    host_c = host_a.copy()
    host_c[0], host_c[1], host_c[2] = "esx-c", "DC-B", "Cluster-B"
    host_c[18:21] = ["VMware ESXi 8.0.3 build-100", "Dell", "PowerEdge R740"]
    vm_headers = [
        "VM", "Powerstate", "CPUs", "Memory (MB)", "Disks", "Total disk capacity MiB", "Host",
        "Cluster", "Datacenter", "Path", "Primary IP Address", "OS according to the VMware Tools",
        "OS according to the configuration file", "VI SDK Server type", "VM UUID",
    ]
    vm = [
        "vm-a", "poweredOn", 2, 4096, 1, 10240, "esx-a", "Cluster-A", "DC-A", "[DS-A] vm/vm.vmx",
        "10.0.0.1", "Linux", "Other configured OS", "VMware vCenter Server 7.0.3 build-22357613",
        SENSITIVE[2],
    ]
    vms = [vm]
    for name, tools, config, power in (
        ("vm-b", "", "Linux", "poweredOff"),
        ("vm-c", "Microsoft Windows Server 2022", "Other", "poweredOn"),
        ("vm-d", "Backup Appliance", "Other", "poweredOn"),
    ):
        row = vm.copy()
        row[0], row[1], row[11], row[12] = name, power, tools, config
        vms.append(row)
    return {
        "vHost": [host_headers, host_a, host_b, host_c], "vInfo": [vm_headers, *vms],
        "vMetaData": [["RVTools version", "xlsx creation datetime", "Server"],
                      ["4.4.5", datetime(2026, 9, 9, 15, 9, 23), "vc.example.test"]],
        "vCluster": [["Name", "NumHosts", "NumCpuCores", "NumCpuThreads", "TotalMemory (MB)", "HA enabled"],
                     ["Cluster-A", 2, 32, 64, 131072, True], ["Cluster-B", 1, 16, 32, 65536, False]],
        "vDatastore": [["Name", "Type", "Capacity MiB", "In Use MiB", "Free MiB", "# Hosts"],
                       ["DS-A", "VMFS", 102400, 40960, 61440, 3]],
        "vLicense": [["Name", "Cost Unit", "Total", "Used", "Expiration Date", "Features", "Key"],
                     ["vCenter Server 7 Standard", "instance", 1, 1, "Never", "Management;HA", SENSITIVE[0]],
                     ["VMware vSAN Advanced", "CPU", 6, 3, datetime(2027, 1, 2), "Storage|Dedup", SENSITIVE[0]],
                     ["VMware vSphere Enterprise", "CPU", 8, 6, "Expired", "Virtualization", SENSITIVE[0]]],
    }


@pytest.fixture()
def report(full_sheets):
    return _xlsx(full_sheets)


@pytest.fixture()
def world(db_session):
    alpha, beta, empty = (Customer(name=name) for name in ("Alpha Corp", "Beta Corp", "Empty Customer"))
    db_session.add_all([alpha, beta, empty])
    db_session.commit()
    return {"alpha": alpha, "beta": beta, "empty": empty}


def _user(db, role, grants=(), username=None, legacy_role="user"):
    user = User(username=username or f"rvtools_{role}", email=f"{username or role}@test.local",
                hashed_password="unused", display_name=role, department="Sales", is_admin=0,
                approved=1, is_active=1, sales_role=role, role=legacy_role)
    db.add(user)
    db.flush()
    for customer in grants:
        db.add(CustomerUser(user_id=user.id, customer_id=customer.id, role="member"))
    db.commit()
    return user


def _upload(client, report, target=None, headers=None, filename="report.xlsx"):
    return client.post(BASE, headers=_headers() if headers is None else headers,
                       files={"file": (filename, report, "application/octet-stream")},
                       data={"customer_name": "Alpha Corp"} if target is None else target)


def _panel(client, customer, headers=None):
    return client.get(f"/api/customers/{quote(customer.name, safe='')}/rvtools/",
                      headers=_headers() if headers is None else headers)


def test_full_workbook_detail_technologies_knowledge_and_audit(client, db_session, world, report):
    response = _upload(client, report)
    assert response.status_code == 201, response.text
    body = response.json()
    # The create response adds matched_by (how the target resolved).
    assert set(body) == DETAIL_FIELDS | {"matched_by"}
    assert body["matched_by"] == "name"
    assert body["customer_id"] == world["alpha"].id and not body["created_customer"]
    assert body["file_name"] == "report.xlsx" and body["imported_by"] == "admin"
    assert body["created_at"].endswith("+00:00")
    assert body["collection_at"] == "2026-09-09T15:09:23+00:00"
    assert body["rvtools_version"] == "4.4.5" and body["vcenter"] == "vc.example.test"
    assert body["vcenter_version"] == "VMware vCenter Server 7.0.3"
    assert [body[key] for key in ("host_count", "vm_count", "datastore_count", "license_count")] == [3, 4, 1, 3]
    assert body["datacenters"] == ["DC-A", "DC-B"]
    assert body["esxi_versions"] == ["6.7.0", "8.0.3"]
    assert {k: v for k, v in body["summary"].items() if k != "coverage"} == {"total_cores": 48, "total_memory_gb": 192.0, "total_vcpus": 8,
                               "total_vm_memory_gb": 16.0, "powered_on_vms": 3,
                               "datacenter_count": 2, "cluster_count": 2}
    assert body["guest_os_summary"] == {"Linux": 2, "Microsoft Windows Server 2022": 1, "Backup Appliance": 1}
    assert body["clusters"][0] == {"name": "Cluster-A", "hosts": 2, "cpu_cores": 32,
                                     "cpu_threads": 64, "memory_mb": 131072, "ha": True}
    assert body["datastores"] == [{"name": "DS-A", "type": "VMFS", "capacity_mib": 102400,
                                     "used_mib": 40960, "free_mib": 61440, "host_count": 3}]
    assert all(set(row) == HOST_FIELDS for row in body["hosts"])
    assert all(set(row) == VM_FIELDS for row in body["vms"])
    assert all(set(row) == LICENSE_FIELDS for row in body["licenses"])
    host = body["hosts"][0]
    assert [host[key] for key in ("host_name", "cpu_mhz", "sockets", "cores_per_socket", "cores",
                                   "memory_mb", "nics", "hbas", "vm_count", "vcpu_count")] == [
        "esx-a", 2400, 2, 8, 16, 65536, 4, 2, 2, 6,
    ]
    assert host["maintenance_mode"] is False and body["hosts"][1]["maintenance_mode"] is True
    assert host["vmotion"] is True and host["storage_vmotion"] is True
    assert body["vms"][0]["datastore"] == "DS-A" and body["vms"][1]["guest_os"] == "Linux"
    assert [row["expiration"] for row in body["licenses"]] == ["Never", "2027-01-02T00:00:00", "Expired"]
    batch = db_session.get(RvToolsImport, body["import_id"])
    assert batch.file_sha256 == hashlib.sha256(report).hexdigest() and batch.file_data == report
    techs = {row.name: row for row in db_session.query(CustomerTechnology).all()}
    assert body["technologies"] == sorted(techs) and len(techs) == 11
    for name, category, quantity in (
        ("VMware ESXi 6.7.0", "virtualization", 2), ("VMware ESXi 8.0.3", "virtualization", 1),
        ("VMware vCenter Server 7.0.3", "management_tool", 1),
        ("HPE ProLiant DL360 Gen10", "hardware", 2), ("Dell PowerEdge R740", "hardware", 1),
        ("vCenter Server 7 Standard", "management_tool", 1), ("VMware vSAN Advanced", "storage", 6),
        ("VMware vSphere Enterprise", "virtualization", 8), ("Linux", "operating_system", 2),
        ("Microsoft Windows Server 2022", "operating_system", 1), ("Backup Appliance", "other", 1),
    ):
        tech = techs[name]
        assert tech.category == category and tech.quantity == quantity
        assert tech.source == f"rvtools import #{batch.id}" and tech.verification_state == "verified"
        assert tech.date_observed == batch.created_at.date()
        assert "report.xlsx" in tech.notes and "2026-09-09" in tech.notes
    assert techs["VMware ESXi 6.7.0"].version_edition == "6.7.0"
    assert techs["VMware ESXi 6.7.0"].footprint == "2 hosts"
    assert techs["VMware vCenter Server 7.0.3"].version_edition == "7.0.3"
    assert techs["VMware vCenter Server 7.0.3"].footprint == "vc.example.test"
    assert techs["HPE ProLiant DL360 Gen10"].vendor == "HPE"
    assert "expiration: Never; features: Management" in techs["vCenter Server 7 Standard"].notes
    assert "Dedup" not in techs["VMware vSAN Advanced"].notes
    doc = db_session.query(CustomerKnowledge).one()
    assert doc.knowledge_type == "rvtools_report" and doc.knowledge_category == "infrastructure"
    # The knowledge document stores the sanitized Markdown (never the
    # original workbook bytes); the original is retained only on the import
    # row (batch.file_data == report, asserted above).
    assert doc.file_name == "report.xlsx.rvtools.md"
    assert doc.file_data == doc.normalized_content.encode("utf-8")
    assert doc.classification == f"rvtools_import:{batch.id}"
    assert doc.processor == "rvtools-import" and doc.processing_status == "READY" and doc.processed == 1
    assert doc.ingestion_status == "ready" and doc.enrichment_status == "NOT_RUN"
    assert doc.extracted_text is None and doc.normalized_format == "markdown"
    assert doc.original_content_type == "text/markdown"
    assert doc.original_storage_path == f"database:customer_knowledge.file_data:{doc.id}"
    for section in ("Overview", "Clusters", "Hosts", "Datastores", "Licenses", "Guest OS counts", "Technologies recorded"):
        assert f"## {section}" in doc.normalized_content
    assert "Storage\\|Dedup" in doc.normalized_content
    hosts = db_session.query(RvToolsHost).order_by(RvToolsHost.id).all()
    licenses = db_session.query(RvToolsLicense).order_by(RvToolsLicense.id).all()
    assert doc.normalized_content == service._markdown(world["alpha"], batch, hosts, licenses, sorted(techs))
    audit = db_session.query(AuditLog).filter_by(action="rvtools_import.create").one()
    assert audit.username == "admin" and audit.target_id == batch.id
    assert audit.customer_id == world["alpha"].id
    assert json.loads(audit.details) == {
        "import_id": batch.id, "file_name": "report.xlsx", "host_count": 3, "vm_count": 4,
        "datastore_count": 1, "license_count": 3, "technologies_created": 11, "technologies_refreshed": 0,
    }
    detail = client.get(f"{BASE}{batch.id}/", headers=_headers())
    # The stored detail is the create response minus the create-only matched_by.
    assert detail.status_code == 200 and detail.json() == {
        key: value for key, value in body.items() if key != "matched_by"}


def test_minimal_workbook_leaves_unknowns_null_and_optional_blocks_empty(client, db_session, world):
    data = _xlsx({"vHost": [["Host"], ["bare-host"]], "vInfo": [["VM"], ["bare-vm"]]})
    response = _upload(client, data, filename="MINIMAL.XLSM")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["hosts"] == [{key: (body["hosts"][0]["id"] if key == "id" else
                                    "bare-host" if key == "host_name" else None) for key in HOST_FIELDS}]
    assert body["vms"] == [{key: (body["vms"][0]["id"] if key == "id" else
                                  "bare-vm" if key == "name" else None) for key in VM_FIELDS}]
    for key in ("clusters", "datastores", "licenses", "esxi_versions", "datacenters", "technologies"):
        assert body[key] == []
    for key in ("rvtools_version", "collection_at", "vcenter", "vcenter_version"):
        assert body[key] is None
    assert body["guest_os_summary"] == {}
    assert body["summary"]["total_cores"] is None
    assert body["summary"]["total_memory_gb"] is None
    assert body["summary"]["total_vcpus"] is None
    assert body["summary"]["powered_on_vms"] is None
    assert body["summary"]["coverage"]["total_cores"] == {"known": 0, "total": 1}
    assert db_session.query(CustomerTechnology).count() == 0


def test_partial_and_legacy_summaries_use_all_retained_rows(client, db_session, world):
    data = _xlsx({
        "vHost": [["Host", "# Cores", "# Memory"], ["host-a", 0, 1024], ["host-b", None, 1024]],
        "vInfo": [["VM", "CPUs", "Memory", "Powerstate"], ["vm-a", 0, 0, "poweredOn"], ["vm-b", None, 0, None]],
    })
    body = _upload(client, data).json()
    batch = db_session.get(RvToolsImport, body["import_id"])
    # Simulate the old persisted aggregate, which counted missing values as zero.
    batch.summary = {"total_cores": 0, "total_vcpus": 0, "powered_on_vms": 1,
                     "datacenter_count": 0, "cluster_count": 0}
    db_session.commit()
    detail = client.get(f'{BASE}{batch.id}/?vm_limit=1', headers=_headers("admin")).json()
    panel = _panel(client, world["alpha"]).json()
    for summary in (detail["summary"], panel["summary"]):
        assert summary["total_cores"] is None
        assert summary["coverage"]["total_cores"] == {"known": 1, "total": 2}
        assert summary["total_vcpus"] is None
        assert summary["powered_on_vms"] is None
        assert summary["total_memory_gb"] == 2.0
        assert summary["total_vm_memory_gb"] == 0.0
    assert len(detail["vms"]) == 1


def test_legacy_knowledge_totals_suppressed_but_original_retained(client, db_session, world):
    body = _upload(client, _xlsx({"vHost": [["Host"], ["bare-host"]], "vInfo": [["VM"], ["bare-vm"]]})).json()
    doc = db_session.query(CustomerKnowledge).filter_by(classification=f'rvtools_import:{body["import_id"]}').one()
    original = b'# RVTools Report\n- total_cores: 0\n- powered_on_vms: 0\n- cluster_count: 1\n'
    doc.processor_version = None
    doc.normalized_content = original.decode()
    doc.file_data = original
    db_session.add(CustomerKnowledgeItem(customer_id=doc.customer_id, source_knowledge_id=doc.id,
                                         kind="customer_fact", name="Reported cores", provenance="derived"))
    db_session.commit()
    content = client.get(f'/api/customer-knowledge/{doc.id}/content', headers=_headers("admin"))
    assert content.status_code == 200
    assert 'total_cores: unavailable (legacy total' in content.json()["normalized_content"]
    assert 'powered_on_vms: unavailable (legacy total' in doc.knowledge_text
    assert '- cluster_count: 1' in doc.knowledge_text
    download = client.get(f'/api/customer-knowledge/{doc.id}/download', headers=_headers("admin"))
    assert download.content == original
    assert 'Legacy RVTools totals may be incomplete' in download.headers['warning']
    assert db_session.get(CustomerKnowledge, doc.id).normalized_content == original.decode()
    items = client.get(f'/api/customer-knowledge/{doc.id}/items', headers=_headers("admin"))
    assert items.status_code == 200 and items.json()[0]["legacy_rvtools_source"] is True


def test_custom_columns_reordering_and_real_export_header_aliases(client, db_session, world, full_sheets):
    for sheet, old, new in (("vHost", "# Memory (MB)", "# Memory"),
                            ("vInfo", "Memory (MB)", "Memory"),
                            ("vCluster", "TotalMemory (MB)", "TotalMemory")):
        headers = full_sheets[sheet][0]
        headers[headers.index(old)] = new
    for sheet in ("vInfo", "vHost"):
        rows = full_sheets[sheet]
        rows[0][:0] = ["Assignment Group", "IT Manager"]
        for row in rows[1:]:
            row[:0] = [SENSITIVE[-1], SENSITIVE[-1]]
        full_sheets[sheet] = [list(reversed(row)) for row in rows]
    response = _upload(client, _xlsx(full_sheets))
    assert response.status_code == 201, response.text
    assert response.json()["summary"]["total_memory_gb"] == 192.0
    assert response.json()["summary"]["total_vm_memory_gb"] == 16.0
    assert response.json()["clusters"][0]["memory_mb"] == 131072
    assert response.json()["hosts"][0]["host_name"] == "esx-a"
    assert response.json()["vms"][0]["name"] == "vm-a"
    assert SENSITIVE[-1] not in response.text


def test_aggregate_footers_and_blank_rows_are_not_inventory(client, db_session, world, full_sheets):
    for name in ("vHost", "vInfo", "vCluster", "vDatastore", "vLicense"):
        full_sheets[name].extend([[None] * len(full_sheets[name][0]), [None, "Aggregate footer"]])
    response = _upload(client, _xlsx(full_sheets))
    assert response.status_code == 201, response.text
    body = response.json()
    assert [body[key] for key in ("host_count", "vm_count", "datastore_count", "license_count")] == [3, 4, 1, 3]
    assert body["summary"]["cluster_count"] == 2
    assert body["summary"]["total_memory_gb"] == 192.0


def test_missing_identity_column_still_maps_to_null(client, db_session, world):
    response = _upload(client, _xlsx({"vHost": [["Vendor"], ["HPE"]], "vInfo": [["CPUs"], [4]]}))
    assert response.status_code == 201
    assert response.json()["hosts"][0]["host_name"] is None
    assert response.json()["vms"][0]["name"] is None


@pytest.mark.parametrize("missing", [("vHost",), ("vInfo",), ("vHost", "vInfo")])
def test_missing_required_sheets(client, db_session, world, missing):
    data = _xlsx({name: [["Header"]] for name in ("vHost", "vInfo", "other") if name not in missing})
    response = _upload(client, data)
    assert response.status_code == 422
    assert all(name in response.json()["detail"] for name in missing)
    assert db_session.query(RvToolsImport).count() == 0


@pytest.mark.parametrize("data,filename,status,message", [
    (_xlsx({"vHost": [["Host"]], "vInfo": [["VM"]]}), "empty.xlsx", 400, "no vHost data rows"),
    (b"csv", "bad.csv", 400, ".xlsx or .xlsm"),
    (b"old excel", "bad.xls", 400, ".xlsx or .xlsm"),
    (b"not a ZIP", "corrupt.xlsx", 422, "Invalid RVTools workbook"),
    (b"", "empty.xlsx", 400, "Upload is empty"),
])
def test_bad_upload_is_atomic(client, db_session, world, data, filename, status, message):
    response = _upload(client, data, filename=filename)
    assert response.status_code == status and message in response.json()["detail"]
    assert db_session.query(Customer).count() == 3
    assert db_session.query(RvToolsImport).count() == 0
    assert db_session.query(CustomerKnowledge).count() == 0


def test_upload_limit(client, db_session, world, report, monkeypatch):
    monkeypatch.setattr("backend.upload_size.MAX_UPLOAD_BYTES", 32)
    assert _upload(client, report).status_code == 413
    assert db_session.query(RvToolsImport).count() == 0


# the target is an
# EXISTING customer's name or alias; imports never create a customer. The
# removed new_customer_name field is ignored like any unknown form field.
@pytest.mark.parametrize("target", [{}, {"customer_name": "   "}, {"new_customer_name": "Temp"}])
def test_blank_target_is_422_and_creates_nothing(client, db_session, world, report, target):
    response = _upload(client, report, target)
    assert response.status_code == 422
    assert response.json()["detail"] == "Provide a customer name or alias"
    assert db_session.query(Customer).count() == 3
    assert db_session.query(RvToolsImport).count() == 0


@pytest.mark.parametrize("name,matched_by", [
    ("Alpha Corp", "name"), ("alpha corp", "name"), ("  ALPHA\t CORP ", "name"),
    ("Alpha Holdings", "alias"), ("alpha   HOLDINGS", "alias"),
])
def test_target_matches_name_or_alias_case_insensitively(client, db_session, world, report,
                                                         name, matched_by):
    db_session.add(CustomerAlias(customer_id=world["alpha"].id, alias="Alpha Holdings",
                                 alias_norm="alpha holdings", created_by="admin"))
    db_session.commit()
    response = _upload(client, report, {"customer_name": name})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["customer_id"] == world["alpha"].id and body["customer_name"] == "Alpha Corp"
    assert body["matched_by"] == matched_by and body["created_customer"] is False
    assert db_session.query(Customer).count() == 3


@pytest.mark.parametrize("name", ["Unknown", "Alpha Corp LLC"])
def test_unmatched_target_refuses_file_and_creates_nothing(client, db_session, world, report, name):
    response = _upload(client, report, {"customer_name": name})
    assert response.status_code == 404
    assert response.json()["detail"] == "No matching customer name or alias"
    assert db_session.query(Customer).count() == 3
    assert db_session.query(RvToolsImport).count() == 0
    assert db_session.query(CustomerKnowledge).count() == 0


def test_ambiguous_target_refuses_file(client, db_session, world, report):
    # Defensive: names and aliases are unique by rule; a name that is one
    # customer's and another customer's alias must not pick either.
    db_session.add(CustomerAlias(customer_id=world["beta"].id, alias="Alpha Corp",
                                 alias_norm="alpha corp", created_by="admin"))
    db_session.commit()
    response = _upload(client, report, {"customer_name": "Alpha Corp"})
    assert response.status_code == 404
    assert response.json()["detail"] == "No matching customer name or alias"
    assert db_session.query(RvToolsImport).count() == 0


def test_scope_gates_target_detail_delete_and_customer_read(client, db_session, world, report):
    manager = _user(db_session, "sales_manager", [world["alpha"]])
    headers = _headers(manager.username)
    beta = _upload(client, report, {"customer_name": world["beta"].name}).json()
    alpha = _upload(client, report, headers=headers)
    assert alpha.status_code == 201
    assert _upload(client, report, {"customer_name": world["beta"].name}, headers).status_code == 404
    assert client.get(f"{BASE}{beta['import_id']}/", headers=headers).status_code == 404
    assert client.delete(f"{BASE}{beta['import_id']}/", headers=headers).status_code == 404
    assert _panel(client, world["beta"], headers).status_code == 404
    assert _panel(client, world["alpha"], headers).status_code == 200
    rep = _user(db_session, "rep", [world["alpha"]])
    rep_headers = _headers(rep.username)
    # Import list/detail are manager-gated (the Global Intelligence surface);
    # the customer panel stays open to any caller authorized for the account.
    assert client.get(BASE, headers=rep_headers).status_code == 403
    assert client.get(f"{BASE}{alpha.json()['import_id']}/", headers=rep_headers).status_code == 403
    assert client.get(f"{BASE}{beta['import_id']}/", headers=rep_headers).status_code == 403
    assert _panel(client, world["alpha"], rep_headers).status_code == 200
    assert client.get("/api/customers/Unknown/rvtools/", headers=headers).status_code == 404
    assert client.get(f"{BASE}9999/", headers=headers).status_code == 404
    assert client.delete(f"{BASE}9999/", headers=headers).status_code == 404


@pytest.mark.parametrize("role", ["sales_manager"])
def test_existing_target_requires_explicit_junction_even_for_global_read_role(client, db_session, world, report, role):
    user = _user(db_session, role)
    headers = _headers(user.username)
    assert _upload(client, report, headers=headers).status_code == 404
    assert db_session.query(RvToolsImport).count() == 0
    db_session.add(CustomerUser(customer_id=world["alpha"].id, user_id=user.id, role="member"))
    db_session.commit()
    assert _upload(client, report, headers=headers).status_code == 201


def test_sales_admin_middleware_block_on_mutations(client, db_session, world, report):
    # the sales_admin content block now covers
    # /api/rvtools-import — every mutating verb 403s at the middleware
    # (before the route), regardless of junction grants.
    user = _user(db_session, "sales_admin")
    headers = _headers(user.username)
    assert _upload(client, report, headers=headers).status_code == 403
    assert _upload(client, report, {"customer_name": "Alpha Holdings"}, headers).status_code == 403
    assert client.delete(f"{BASE}9999/", headers=headers).status_code == 403


@pytest.mark.parametrize("role", ["rep", "auditor", "inside_sales", "sales_ops", "ps_admin"])
def test_mutations_require_manager(client, db_session, world, report, role):
    user = _user(db_session, role, [world["alpha"]], legacy_role="ps_admin" if role == "ps_admin" else "user")
    import_id = _upload(client, report).json()["import_id"]
    headers = _headers(user.username)
    assert _upload(client, report, headers=headers).status_code == 403
    assert _upload(client, report, {"customer_name": "alpha corp"}, headers).status_code == 403
    assert client.get(BASE, headers=headers).status_code == 403
    assert client.get(f"{BASE}{import_id}/", headers=headers).status_code == 403
    assert client.delete(f"{BASE}{import_id}/", headers=headers).status_code == 403


def test_all_routes_require_auth(client, db_session, world, report):
    assert _upload(client, report, headers={}).status_code == 401
    assert client.get(BASE).status_code == 401
    assert client.get(f"{BASE}1/").status_code == 401
    assert client.delete(f"{BASE}1/").status_code == 401
    assert _panel(client, world["alpha"], {}).status_code == 401


def test_refresh_updates_quantities_deduplicates_and_preserves_manual(client, db_session, world, full_sheets):
    manual = CustomerTechnology(customer_id=world["alpha"].id, name=" linux ", category="other",
                                source="discovery call", notes="Keep me", quantity=99,
                                verification_state="unverified")
    db_session.add(manual)
    db_session.commit()
    first = _upload(client, _xlsx(full_sheets)).json()
    assert "Linux" not in first["technologies"]
    before_ids = {row.name: row.id for row in db_session.query(CustomerTechnology).all()}
    full_sheets["vHost"].append(full_sheets["vHost"][1].copy())
    full_sheets["vInfo"].append(full_sheets["vInfo"][1].copy())
    full_sheets["vLicense"][2][2] = 12
    second = _upload(client, _xlsx(full_sheets)).json()
    db_session.expire_all()
    techs = {row.name: row for row in db_session.query(CustomerTechnology).all()}
    assert len(techs) == 11 and before_ids == {name: row.id for name, row in techs.items()}
    assert techs["VMware ESXi 6.7.0"].quantity == 3
    assert techs["HPE ProLiant DL360 Gen10"].quantity == 3
    assert techs["VMware vSAN Advanced"].quantity == 12
    assert techs[" linux "].quantity == 99 and techs[" linux "].notes == "Keep me"
    assert techs[" linux "].source == "discovery call" and techs[" linux "].verification_state == "unverified"
    assert all(row.source == f"rvtools import #{second['import_id']}" for name, row in techs.items() if name != " linux ")
    audit = db_session.query(AuditLog).filter_by(action="rvtools_import.create").order_by(AuditLog.id.desc()).first()
    assert json.loads(audit.details)["technologies_created"] == 0
    assert json.loads(audit.details)["technologies_refreshed"] == 10
    assert client.get(f"{BASE}{first['import_id']}/", headers=_headers()).json()["technologies"] == []
    assert client.delete(f"{BASE}{first['import_id']}/", headers=_headers()).json()["deleted_technologies"] == 0
    assert client.delete(f"{BASE}{second['import_id']}/", headers=_headers()).json()["deleted_technologies"] == 10
    db_session.expire_all()
    assert db_session.query(CustomerTechnology).one().id == manual.id


def test_delete_exact_cascade_knowledge_items_audit_and_other_imports(client, db_session, world, report):
    first = _upload(client, report).json()
    second = _upload(client, report, {"customer_name": world["beta"].name}).json()
    document = db_session.query(CustomerKnowledge).filter_by(classification=f"rvtools_import:{first['import_id']}").one()
    db_session.add(CustomerKnowledgeItem(customer_id=world["alpha"].id, source_knowledge_id=document.id,
                                         kind="technology", name="Extracted item"))
    db_session.add(CustomerTechnology(customer_id=world["alpha"].id, name="Keep exact source suffix",
                                      category="other", source=f"rvtools import #{first['import_id']} extra"))
    db_session.add(CustomerTechnology(customer_id=world["alpha"].id, name="Manual", category="other", source="manual"))
    db_session.commit()
    unrelated_doc = create_customer_knowledge(db_session, world["alpha"].id, "notes", "keep.md", b"keep")
    response = client.delete(f"{BASE}{first['import_id']}/", headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"detail": "Import deleted", "deleted_hosts": 3, "deleted_vms": 4,
                                "deleted_licenses": 3, "deleted_knowledge": 1, "deleted_technologies": 11,
                                "temp_customer_kept": True}
    db_session.expire_all()
    assert db_session.get(RvToolsImport, first["import_id"]) is None
    assert db_session.get(RvToolsImport, second["import_id"]) is not None
    assert db_session.query(RvToolsHost).count() == 3
    assert db_session.query(RvToolsVM).count() == 4
    assert db_session.query(RvToolsLicense).count() == 3
    assert db_session.query(CustomerKnowledgeItem).count() == 0
    assert db_session.query(CustomerKnowledge).count() == 2
    assert db_session.get(CustomerKnowledge, unrelated_doc.id) is not None
    assert db_session.query(CustomerTechnology).count() == 13
    assert db_session.query(Customer).count() == 3
    audits = db_session.query(AuditLog).filter(AuditLog.action.like("rvtools_import.%")).all()
    assert len(audits) == 3
    audit = next(row for row in audits if row.action == "rvtools_import.delete")
    assert json.loads(audit.details)["deleted_technologies"] == 11 and audit.target_id == first["import_id"]


def test_pii_never_extracted_or_rendered_original_workbooks_retained(client, db_session, world, full_sheets):
    full_sheets["vInfo"][0].extend(["IT Manager", "BIOS Date"])
    for row in full_sheets["vInfo"][1:]:
        row.extend([SENSITIVE[-1], SENSITIVE[4]])
    report = _xlsx(full_sheets)
    with ZipFile(io.BytesIO(report)) as archive:
        original_xml = b"".join(archive.read(name) for name in archive.namelist())
    assert all(marker.encode() in original_xml for marker in SENSITIVE)
    response = _upload(client, report)
    assert response.status_code == 201
    rendered = response.text + _panel(client, world["alpha"]).text + client.get(BASE, headers=_headers()).text
    extracted = []
    for model in (RvToolsImport, RvToolsHost, RvToolsVM, RvToolsLicense, CustomerTechnology, CustomerKnowledge, AuditLog):
        for row in db_session.query(model).all():
            for column in model.__table__.columns:
                value = getattr(row, column.name)
                if column.name == "file_data":
                    # The retained original workbook lives ONLY on the import
                    # row (provenance; no API serves it). The knowledge
                    # document holds sanitized Markdown, never the bytes.
                    if isinstance(row, RvToolsImport):
                        assert value == report
                    else:
                        assert value != report
                else:
                    extracted.append(str(value))
    assert all(marker not in rendered + "\n".join(extracted) for marker in SENSITIVE)


@pytest.mark.parametrize("limit,offset,expected_limit,expected_offset,names", [
    (1, 1, 1, 1, ["vm-b"]), (0, -10, 1, 0, ["vm-a"]),
    (9999, 0, 500, 0, ["vm-a", "vm-b", "vm-c", "vm-d"]), (2, 999, 2, 999, []),
])
def test_vm_pagination_clamps(client, db_session, world, report, limit, offset, expected_limit, expected_offset, names):
    body = _upload(client, report).json()
    result = client.get(f"{BASE}{body['import_id']}/?vm_limit={limit}&vm_offset={offset}", headers=_headers()).json()
    assert result["vm_limit"] == expected_limit and result["vm_offset"] == expected_offset
    assert result["vm_total"] == 4 and [row["name"] for row in result["vms"]] == names
    assert len(result["hosts"]) == 3 and len(result["licenses"]) == 3


def test_post_default_vm_page_has_100_rows(client, db_session, world, full_sheets):
    full_sheets["vInfo"] = [full_sheets["vInfo"][0]] + [full_sheets["vInfo"][1]] * 105
    response = _upload(client, _xlsx(full_sheets))
    assert response.status_code == 201
    assert len(response.json()["vms"]) == 100 and response.json()["vm_total"] == 105
    assert response.json()["vm_limit"] == 100 and response.json()["vm_offset"] == 0


def test_history_is_manager_scoped_newest_first_and_panel_latest(client, db_session, world, report):
    manager = _user(db_session, "sales_manager", [world["alpha"]])
    headers = _headers(manager.username)
    first = _upload(client, report).json()
    other = _upload(client, report, headers=headers).json()
    beta = _upload(client, report, {"customer_name": world["beta"].name}).json()
    listing = client.get(BASE, headers=_headers()).json()
    assert [row["import_id"] for row in listing] == [beta["import_id"], other["import_id"], first["import_id"]]
    assert set(listing[0]) == {"import_id", "file_name", "customer_id", "customer_name", "created_customer",
                               "host_count", "vm_count", "vcenter", "vcenter_version", "esxi_versions",
                               "created_at", "imported_by"}
    # A non-admin manager sees only imports for customers in their scope.
    assert [row["import_id"] for row in client.get(BASE, headers=headers).json()] == [other["import_id"], first["import_id"]]
    panel = _panel(client, world["alpha"], headers).json()
    assert set(panel) == {"customer_name", "import_id", "source_file", "imported_at", "rvtools_version",
                           "vcenter", "vcenter_version", "esxi_versions", "host_count", "vm_count",
                           "datastore_count", "license_count", "datacenters", "clusters",
                           "hosts_preview", "guest_os_summary", "technologies", "summary"}
    assert panel["import_id"] == other["import_id"] and panel["source_file"] == "report.xlsx"
    assert panel["imported_at"] == other["created_at"] and panel["technologies"] == other["technologies"]
    assert len(panel["hosts_preview"]) == 3
    assert client.delete(f"{BASE}{other['import_id']}/", headers=_headers()).status_code == 200
    assert _panel(client, world["alpha"]).json()["import_id"] == first["import_id"]
    assert _panel(client, world["empty"]).json()["import_id"] is None
    assert _panel(client, world["empty"]).json()["technologies"] == []
    assert set(_panel(client, world["empty"]).json()["summary"]) == set(panel["summary"])


@pytest.mark.parametrize("operation", ["create", "delete"])
def test_failure_after_knowledge_helper_commits_rolls_back_everything(client, db_session, world, report, monkeypatch, operation):
    body = _upload(client, report).json() if operation == "delete" else None

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(service, "_audit_import", fail_audit)
    with pytest.raises(RuntimeError, match="audit failure"):
        if operation == "create":
            _upload(client, report)
        else:
            client.delete(f"{BASE}{body['import_id']}/", headers=_headers())
    db_session.expire_all()
    expected = operation == "delete"
    assert db_session.query(RvToolsImport).count() == int(expected)
    assert db_session.query(RvToolsHost).count() == 3 * expected
    assert db_session.query(RvToolsVM).count() == 4 * expected
    assert db_session.query(RvToolsLicense).count() == 3 * expected
    assert db_session.query(CustomerTechnology).count() == 11 * expected
    assert db_session.query(CustomerKnowledge).count() == int(expected)
    assert db_session.query(CustomerUser).count() == 0
    assert db_session.query(Customer).count() == 3
    assert db_session.query(AuditLog).count() == int(expected)


def test_duplicate_licenses_null_numbers_and_unknown_category(client, db_session, world, full_sheets):
    full_sheets["vLicense"].extend([
        [" VMware vSAN Advanced ", "CPU", 2, 1, "Never", "Storage", SENSITIVE[0]],
        ["Mystery product", None, None, None, None, None, SENSITIVE[0]],
        ["ESXi Enterprise", "CPU", 4, 2, "Never", "Compute", SENSITIVE[0]],
    ])
    response = _upload(client, _xlsx(full_sheets))
    assert response.status_code == 201
    techs = {row.name: row for row in db_session.query(CustomerTechnology).all()}
    assert techs["VMware vSAN Advanced"].quantity == 8
    assert techs["Mystery product"].category == "other" and techs["Mystery product"].quantity is None
    assert techs["ESXi Enterprise"].category == "virtualization"


def test_unknown_cells_and_absent_guest_os_stay_unknown(client, db_session, world):
    report = _xlsx({
        "vHost": [["Host", "Speed", "# Memory", "in Maintenance Mode", "ESX Version"],
                  ["h", "not numeric", "NaN", "unknown", "unparseable version"]],
        "vInfo": [["VM", "Path", "OS according to the VMware Tools"], ["v", "no brackets", None]],
    })
    response = _upload(client, report)
    assert response.status_code == 201
    host, vm = response.json()["hosts"][0], response.json()["vms"][0]
    assert host["cpu_mhz"] is None and host["memory_mb"] is None and host["maintenance_mode"] is None
    assert host["esxi_version"] is None and vm["datastore"] is None and vm["guest_os"] is None
    assert response.json()["technologies"] == []


# Golden bytes of the full_sheets fixture as built by _xlsx(). Members are
# ZIP_STORED and the core.xml modified-stamp is normalized, so the bytes
# are exact input-XML bytes — pinned here so any cross-environment drift
# (openpyxl version, timestamp handling) fails loud and diffable instead of
# flaking the two-construction comparison (2026-10-25: openpyxl stamps
# dcterms:modified with the wall clock at save time — two constructions
# straddling a second boundary differ).
FIXED_FIXTURE_SHA256 = "dea5c6c910e9e89d520938a751e9272230d83b40ec5ab787d717d06e83d72514"


def test_fixed_fixture_and_datetime_helpers(full_sheets):
    assert _xlsx(full_sheets) == _xlsx(full_sheets)
    assert hashlib.sha256(_xlsx(full_sheets)).hexdigest() == FIXED_FIXTURE_SHA256
    assert service._datetime("2026-09-09T15:09:23") == datetime(2026, 9, 9, 15, 9, 23)
    assert service._datetime(date(2026, 9, 9)) == datetime(2026, 9, 9)
    assert service._datetime("unknown") is None
