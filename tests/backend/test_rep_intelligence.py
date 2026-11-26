"""Generic intelligence import contract using synthetic accounts only."""

import csv
import hashlib
import io
import json

import pytest
from backend.models.account_membership import AccountMembership
from backend.models.collaboration import AuditLog
from backend.models.customer_technology import CustomerTechnology
from backend.models.rep_intelligence import RepIntelligenceImport, RepIntelligenceRow
from backend.models.sales_access import SalesReporting
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import rep_intelligence_service as service

from tests.backend.common import _headers

BASE = "/api/rep-intelligence/"
HEADER = (
    "customer_name", "technology_name", "hardware_software", "is_sale", "amount", "currency",
    "vendor", "version", "quantity", "notes",
)
ISSUE_HEADER = (
    "row", "customer_name", "technology_name", "field", "reason_code", "severity", "message",
    "disposition",
)


def _csv(rows, header=HEADER):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=header, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _row(**overrides):
    return {"customer_name": "Acme Testing Corp", "technology_name": "Synthetic Platform",
            **overrides}


def _upload(client, data, username="admin", filename="observations.csv", headers=None):
    return client.post(BASE, headers=_headers(username) if headers is None else headers,
                       files={"file": (filename, data, "text/csv")})


def _import(client, rows, username="admin", header=HEADER):
    response = _upload(client, _csv(rows, header), username)
    assert response.status_code == 201, response.text
    return response.json()


def _detail(client, import_id, username="admin"):
    response = client.get(f"{BASE}{import_id}/", headers=_headers(username))
    assert response.status_code == 200, response.text
    return response.json()


def _user(db, username, *, sales_role=None, role="user"):
    user = User(
        username=username, email=f"{username}@test.local", hashed_password="unused",
        display_name=username, department="Sales", is_admin=0, approved=1, is_active=1,
        sales_role=sales_role, role=role,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture()
def world(db_session):
    acme = Customer(name="Acme Testing Corp")
    globex = Customer(name="Globex Widgets LLC")
    unassigned = Customer(name="Unassigned Testing Corp")
    db_session.add_all([acme, globex, unassigned])
    db_session.flush()
    rep_a = _user(db_session, "intel_rep_a", sales_role="rep")
    rep_b = _user(db_session, "intel_rep_b", sales_role="rep")
    owner = _user(db_session, "intel_owner", sales_role="rep")
    observer = _user(db_session, "intel_observer", sales_role="rep")
    manager = _user(db_session, "intel_manager", sales_role="sales_manager")
    auditor = _user(db_session, "intel_auditor", sales_role="auditor")
    ps_admin = _user(db_session, "intel_ps_admin", role="ps_admin")
    sales_admin = _user(db_session, "intel_sales_admin", sales_role="sales_admin")
    _user(db_session, "intel_outsider", sales_role="rep")
    db_session.add_all([
        CustomerUser(customer_id=acme.id, user_id=rep_a.id, role="member"),
        AccountMembership(customer_id=acme.id, user_id=rep_a.id, role="inside_sales",
                          section_grants={"intel_uploads": "contribute"}),
        CustomerUser(customer_id=globex.id, user_id=rep_b.id, role="owner"),
        CustomerUser(customer_id=acme.id, user_id=owner.id, role="owner"),
        CustomerUser(customer_id=acme.id, user_id=observer.id, role="member"),
        CustomerUser(customer_id=acme.id, user_id=auditor.id, role="owner"),
        CustomerUser(customer_id=acme.id, user_id=ps_admin.id, role="owner"),
        CustomerUser(customer_id=acme.id, user_id=sales_admin.id, role="owner"),
        SalesReporting(rep_user_id=owner.id, manager_user_id=manager.id),
    ])
    db_session.commit()
    return {"acme": acme, "globex": globex, "unassigned": unassigned, "rep_a": rep_a,
            "rep_b": rep_b, "owner": owner, "observer": observer, "manager": manager}


def _assert_counts(body, *, total, imported, with_issues, skipped, status):
    assert {key: body[key] for key in (
        "total_rows", "imported_rows", "imported_with_issues", "skipped_rows", "status",
    )} == {"total_rows": total, "imported_rows": imported, "imported_with_issues": with_issues,
          "skipped_rows": skipped, "status": status}
    assert body["total_rows"] == body["imported_rows"] + body["skipped_rows"]
    assert sum(row["status"] == "imported_with_issues" for row in body["rows"]) == with_issues


def test_template_is_authenticated_header_only_csv(client, db_session):
    response = client.get(f"{BASE}template/", headers=_headers())
    assert response.status_code == 200
    assert list(csv.reader(io.StringIO(response.text))) == [list(HEADER)]
    assert response.headers["content-type"].startswith("text/csv")
    assert 'filename="sail-account-intelligence-template.csv"' in response.headers[
        "content-disposition"
    ]
    assert client.get(f"{BASE}template/").status_code == 401


@pytest.mark.parametrize("category,is_sale,purpose", [
    ("hardware", "yes", "rep-reported sale (not verified as installed or closed-won)"),
    ("software", "no", "reported as part of the customer's environment (not a sale)"),
    (None, None, "environment vs. prospect status not recorded"),
])
def test_clean_upload_creates_unverified_technology_and_audit(
    client, db_session, world, category, is_sale, purpose,
):
    raw = _row(hardware_software=category, is_sale=is_sale, amount="$1,234.50", currency=" usd ",
               vendor=" Synthetic Vendor ", version=" v1 ", quantity="2",
               notes="  original context\nsecond line  ")
    data = _csv([raw])
    response = _upload(client, data, filename="OBSERVATIONS.CSV")
    assert response.status_code == 201, response.text
    body = response.json()
    _assert_counts(body, total=1, imported=1, with_issues=0, skipped=0, status="completed")
    assert body["technologies_created"] == 1 and body["technologies_refreshed"] == 0
    assert body["can_manage"] is True and body["imported_by"] == "admin"
    assert body["created_at"].endswith("+00:00")
    assert body["matched"] == [{"customer_id": world["acme"].id,
                                "customer_name": world["acme"].name}]
    assert body["affected_customer_ids"] == [world["acme"].id]
    row = body["rows"][0]
    assert row["source_row"] == 1 and row["status"] == "imported" and row["issues"] == []
    assert row["amount"] == 1234.5 and row["currency"] == "USD"
    assert row["notes"] == raw["notes"]
    batch = db_session.get(RepIntelligenceImport, body["import_id"])
    assert batch.file_name == "OBSERVATIONS.CSV" and batch.file_data == data
    assert batch.file_sha256 == body["file_sha256"] == hashlib.sha256(data).hexdigest()
    tech = db_session.query(CustomerTechnology).one()
    assert tech.id == row["technology_id"] and tech.customer_id == world["acme"].id
    assert tech.name == "Synthetic Platform" and tech.category == (category or "other")
    assert tech.verification_state == "unverified"
    assert tech.source == f"generic intelligence import #{batch.id}"
    assert tech.date_observed == batch.created_at.date()
    assert (tech.vendor, tech.version_edition, tech.quantity) == ("Synthetic Vendor", "v1", 2)
    assert tech.notes == (f"Rep observation (generic intelligence import #{batch.id}, row 1) — "
                          f"{purpose}; original note: {raw['notes']}")
    audit = db_session.query(AuditLog).filter_by(action="rep_intelligence_import.create").one()
    details = json.loads(audit.details)
    assert audit.username == "admin" and audit.target_id == batch.id and audit.customer_id is None
    for key in ("import_id", "file_name", "total_rows", "imported_rows", "imported_with_issues",
                "skipped_rows", "status", "technologies_created", "technologies_refreshed"):
        assert details[key] == body[key]
    assert _detail(client, batch.id)["rows"] == body["rows"]


def test_missing_identities_skip_only_their_rows_and_never_create_customers(client, db_session, world):
    body = _import(client, [_row(customer_name="  "), _row(technology_name=""),
                            _row(customer_name="", technology_name="", notes="identity omitted"),
                            _row()])
    _assert_counts(body, total=4, imported=1, with_issues=0, skipped=3,
                   status="completed_with_issues")
    for row, fields in zip(body["rows"][:3], [("customer_name",), ("technology_name",),
                                            ("customer_name", "technology_name")], strict=True):
        assert row["customer_id"] is None and row["technology_id"] is None
        assert row["issues"] == [
            {"field": field, "code": f"{field}_required", "severity": "error",
             "message": f"{field} is required", "disposition": "row_skipped"} for field in fields
        ]
    assert db_session.query(Customer).count() == 3
    assert db_session.query(CustomerTechnology).count() == 1


def test_missing_required_cell_is_a_row_issue(client, db_session, world):
    response = _upload(client, b"customer_name,technology_name\nAcme Testing Corp\n")
    assert response.status_code == 201
    row = response.json()["rows"][0]
    assert row["technology_name_supplied"] is None
    assert row["issues"][0]["code"] == "technology_name_required"


def test_matching_is_exact_normalized_and_scoped(client, db_session, world):
    db_session.add_all([Customer(name="Duplicate Testing Corp"),
                        Customer(name="  DUPLICATE   Testing Corp ")])
    db_session.commit()
    body = _import(client, [
        _row(customer_name="  aCME   Testing\tCORP  "),
        _row(customer_name="No Such Testing Corp"),
        _row(customer_name="duplicate testing corp"),
        _row(customer_name=world["globex"].name),
        _row(customer_name="Acme Testing"),
    ], "intel_rep_a")
    _assert_counts(body, total=5, imported=1, with_issues=0, skipped=4,
                   status="completed_with_issues")
    rows = body["rows"]
    assert rows[0]["customer_id"] == world["acme"].id
    assert rows[0]["customer_name_supplied"] == "  aCME   Testing\tCORP  "
    assert [row["issues"][0]["code"] for row in rows[1:]] == [
        "customer_unmatched", "customer_ambiguous", "customer_not_accessible", "customer_unmatched",
    ]
    assert rows[1]["issues"][0]["message"] == rows[3]["issues"][0]["message"] == (
        "no matching accessible customer; row skipped"
    )
    assert rows[2]["issues"][0]["message"] == "customer name is ambiguous; row skipped"
    assert all(row["customer_id"] is None for row in rows[1:])
    assert db_session.query(Customer).count() == 5


@pytest.mark.parametrize("minimal", [False, True])
def test_optional_missing_columns_and_blanks_stay_unknown(client, db_session, world, minimal):
    header = HEADER[:2] if minimal else HEADER
    body = _import(client, [_row()], header=header)
    _assert_counts(body, total=1, imported=1, with_issues=0, skipped=0, status="completed")
    for field in HEADER[2:]:
        assert body["rows"][0][field] is None
    tech = db_session.query(CustomerTechnology).one()
    assert tech.category == "other" and tech.vendor is None and tech.version_edition is None
    assert tech.quantity is None and "status not recorded" in tech.notes


@pytest.mark.parametrize("field,value", [
    ("hardware_software", "appliance"), ("is_sale", "maybe"),
    ("amount", "invalid"), ("amount", "NaN"), ("amount", "inf"), ("amount", "-Infinity"),
    ("amount", "1e999"), ("amount", "$"), ("amount", "1_000"),
    ("currency", "US"), ("currency", "US1"),
    ("quantity", "-1"), ("quantity", "1.5"), ("quantity", "many"),
    ("quantity", "9223372036854775808"),
])
def test_invalid_optional_field_is_omitted_and_other_facts_import(
    client, db_session, world, field, value,
):
    raw = _row(hardware_software=" HaRdWaRe ", is_sale=" YES ", amount="42.50",
               currency="usd", quantity="3", vendor=" Synthetic Vendor ",
               version=" Release 2 ", notes="=original context")
    raw[field] = value
    body = _import(client, [raw])
    _assert_counts(body, total=1, imported=1, with_issues=1, skipped=0,
                   status="completed_with_issues")
    row = body["rows"][0]
    assert row[field] is None
    assert row["issues"] == [{
        "field": field, "code": f"{field}_invalid", "severity": "warning",
        "message": service.INVALID_MESSAGES[field], "disposition": "field_omitted", "value": value,
    }]
    expected = {"hardware_software": "hardware", "is_sale": "yes", "amount": 42.5,
                "currency": "USD", "quantity": 3, "vendor": "Synthetic Vendor",
                "version": "Release 2", "notes": "=original context"}
    for name, expected_value in expected.items():
        if name != field:
            assert row[name] == expected_value
    tech = db_session.query(CustomerTechnology).one()
    assert tech.category == ("other" if field == "hardware_software" else "hardware")
    assert tech.verification_state == "unverified" and tech.vendor == "Synthetic Vendor"


@pytest.mark.parametrize("amount,quantity", [("0", "0"), ("$1,234.50", "002"),
                                            ("-12.5", "+2"), ("1.5e2", "2")])
def test_recorded_zero_and_valid_numeric_values(client, db_session, world, amount, quantity):
    body = _import(client, [_row(amount=amount, quantity=quantity, currency="eur",
                                hardware_software="SOFTWARE", is_sale="NO")])
    row = body["rows"][0]
    assert row["amount"] == float(amount.replace("$", "").replace(",", ""))
    assert row["quantity"] == int(quantity) and row["currency"] == "EUR"
    assert row["hardware_software"] == "software" and row["is_sale"] == "no"
    assert row["issues"] == []


def test_multiple_invalid_fields_all_persist_with_successful_rows(client, db_session, world):
    body = _import(client, [
        _row(technology_name="Clean Platform"),
        _row(customer_name="Missing Testing Corp"), _row(technology_name=""),
        _row(technology_name="Unknown Amount", amount="bad"),
        _row(technology_name="Several Issues", hardware_software="bad", is_sale="bad", amount="bad",
             currency="bad!", quantity="bad", notes=" context retained "),
    ])
    _assert_counts(body, total=5, imported=3, with_issues=2, skipped=2,
                   status="completed_with_issues")
    assert body["technologies_created"] == 3
    db_session.expire_all()
    persisted = db_session.query(RepIntelligenceRow).order_by(RepIntelligenceRow.source_row).all()
    assert [row.issues for row in persisted] == [row["issues"] for row in body["rows"]]
    assert len(persisted[-1].issues) == 5 and persisted[3].amount is None
    assert _detail(client, body["import_id"])["rows"] == body["rows"]


@pytest.mark.parametrize("source", [None, "manual", "seeded", "pipeline import #7 (renewal)",
                                   "rvtools import #8"])
def test_other_source_technology_is_completely_preserved_and_associated(
    client, db_session, world, source,
):
    tech = CustomerTechnology(
        customer_id=world["acme"].id, name=" Synthetic   Platform ", category="management_tool",
        vendor="Original Vendor", version_edition="original", quantity=9, source=source,
        verification_state="verified", notes="Original notes", purpose="Original purpose",
    )
    db_session.add(tech)
    db_session.commit()
    original = tech.to_dict()
    body = _import(client, [_row(technology_name="synthetic platform", hardware_software="hardware",
                                vendor="New Vendor", version="new", quantity="2")])
    _assert_counts(body, total=1, imported=1, with_issues=0, skipped=0, status="completed")
    row = body["rows"][0]
    assert row["technology_id"] == tech.id and row["status"] == "imported"
    assert row["issues"] == [{
        "field": "technology_name", "code": "technology_already_recorded", "severity": "info",
        "message": (f"technology already recorded (source: {source}) — existing record preserved; "
                    "row associated with it"), "disposition": "associated",
    }]
    assert body["technologies_created"] == 0 and body["technologies_refreshed"] == 0
    db_session.refresh(tech)
    assert tech.to_dict() == original
    report = client.get(f"{BASE}{body['import_id']}/issues.csv/", headers=_headers())
    assert list(csv.DictReader(io.StringIO(report.text)))[0]["severity"] == "info"


def test_duplicate_rows_and_reupload_refresh_in_file_order_and_move_ownership(client, db_session, world):
    rows = [_row(hardware_software="hardware", vendor="First Vendor", version="first", quantity="2"),
            _row(technology_name=" synthetic   platform ", hardware_software="software",
                 is_sale="yes", vendor="Last Vendor", version="last", quantity="0", notes="last note")]
    first = _import(client, rows)
    assert first["technologies_created"] == 1 and first["technologies_refreshed"] == 1
    assert len(first["rows"]) == 2 and first["imported_rows"] == 2
    assert len({row["technology_id"] for row in first["rows"]}) == 1
    second = _import(client, rows)
    assert second["technologies_created"] == 0 and second["technologies_refreshed"] == 2
    assert second["total_rows"] == second["imported_rows"] == 2
    tech = db_session.query(CustomerTechnology).one()
    assert tech.category == "software" and tech.vendor == "Last Vendor"
    assert tech.version_edition == "last" and tech.quantity == 0
    assert tech.source == f"generic intelligence import #{second['import_id']}"
    assert tech.notes == (f"Rep observation ({tech.source}, row 2) — "
                          "rep-reported sale (not verified as installed or closed-won); "
                          "original note: last note")
    response = client.delete(f"{BASE}{first['import_id']}/", headers=_headers())
    assert response.status_code == 200
    assert response.json()["deleted_rows"] == 2 and response.json()["deleted_technologies"] == 0
    assert db_session.query(CustomerTechnology).count() == 1
    assert db_session.query(RepIntelligenceRow).count() == 2
    assert _detail(client, second["import_id"])["rows"] == second["rows"]


def test_reupload_preserves_previously_supplied_facts_and_resets_verification(client, db_session, world):
    """Re-upload semantics: the rep file is cumulative evidence — a later
    file that is silent about a fact does not erase what an earlier file
    supplied (last *supplied* value wins); provenance (source,
    verification_state) is re-derived from the current batch."""
    first = _import(client, [_row(vendor="Known Vendor", version="1", quantity="4",
                                  hardware_software="hardware", is_sale="no")])
    tech = db_session.query(CustomerTechnology).one()
    tech.verification_state = "verified"
    db_session.commit()
    second = _import(client, [_row()])
    db_session.refresh(tech)
    assert second["rows"][0]["technology_id"] == first["rows"][0]["technology_id"]
    assert (tech.vendor, tech.version_edition, tech.quantity) == ("Known Vendor", "1", 4)
    assert tech.category == "hardware" and tech.verification_state == "unverified"
    assert tech.source == f"generic intelligence import #{second['import_id']}"
    assert "status not recorded" in tech.notes


@pytest.mark.parametrize("data,filename,status,message", [
    (b"customer_name\nAcme Testing Corp\n", "report.csv", 422, "technology_name"),
    (b"technology_name\nSynthetic Platform\n", "report.csv", 422, "customer_name"),
    (b"unknown\nvalue\n", "report.csv", 422, "customer_name, technology_name"),
    (b'customer_name,technology_name\n"unfinished,platform', "report.csv", 422, "Invalid CSV:"),
    (b"customer_name,technology_name\n\xff,platform\n", "report.csv", 422, "Invalid CSV:"),
    (_csv([]), "report.csv", 400, "File contains no data rows"),
    (_csv([_row()]), "report.xlsx", 400, "Only .csv files are accepted"),
    (b"", "report.csv", 400, "Upload is empty"),
])
def test_structural_failure_has_no_writes(client, db_session, world, data, filename, status, message):
    response = _upload(client, data, filename=filename)
    assert response.status_code == status, response.text
    assert message in response.json()["detail"]
    assert db_session.query(RepIntelligenceImport).count() == 0
    assert db_session.query(RepIntelligenceRow).count() == 0
    assert db_session.query(CustomerTechnology).count() == 0
    assert db_session.query(AuditLog).filter_by(action="rep_intelligence_import.create").count() == 0
    assert db_session.query(Customer).count() == 3


def test_upload_uses_shared_size_limit(client, db_session, world, monkeypatch):
    import backend.upload_size as upload_size

    monkeypatch.setattr(upload_size, "MAX_UPLOAD_BYTES", 32)
    response = _upload(client, _csv([_row()]))
    assert response.status_code == 413
    assert db_session.query(RepIntelligenceImport).count() == 0


def test_bom_trimmed_headers_unknown_columns_blank_rows_and_multiline(client, db_session, world):
    data = (b"\xef\xbb\xbf" + _csv([
        {}, _row(notes="Line one\nLine two", technology_name="First Platform"), {},
        _row(technology_name="Second Platform"), {},
    ], HEADER + ("ignored",)))
    data = data.replace(b"customer_name,technology_name", b" customer_name , technology_name ", 1)
    response = _upload(client, data)
    assert response.status_code == 201, response.text
    body = response.json()
    _assert_counts(body, total=2, imported=2, with_issues=0, skipped=0, status="completed")
    assert [row["source_row"] for row in body["rows"]] == [1, 2]
    assert body["rows"][0]["notes"] == "Line one\nLine two"


def test_all_skipped_batch_is_retained_as_failed(client, db_session, world):
    body = _import(client, [_row(customer_name="Missing Testing Corp"), _row(technology_name="")])
    _assert_counts(body, total=2, imported=0, with_issues=0, skipped=2, status="failed")
    assert db_session.get(RepIntelligenceImport, body["import_id"]) is not None
    assert _detail(client, body["import_id"])["rows"] == body["rows"]
    assert client.get(BASE, headers=_headers()).json()[0]["status"] == "failed"


@pytest.mark.parametrize("username,expected", [
    ("intel_rep_a", 1), ("intel_owner", 1), ("intel_manager", 1), ("admin", 2),
    ("intel_observer", 0), ("intel_ps_admin", 0),
    ("intel_outsider", 0),
])
def test_upload_authorizes_every_row_for_any_authenticated_role(
    client, db_session, world, username, expected,
):
    body = _import(client, [_row(), _row(customer_name=world["globex"].name)], username)
    assert body["imported_rows"] == expected
    assert body["skipped_rows"] == 2 - expected
    for row in body["rows"]:
        if row["status"] == "skipped":
            assert row["issues"][0]["code"] == "customer_not_accessible"
    assert body["can_manage"] is True
    assert db_session.query(CustomerTechnology).count() == expected


def test_sales_admin_write_block_applies_to_generic_import(client, db_session, world):
    """The app-wide sales_admin content block
    covers the generic import surface — mutating verbs 403 at the middleware
    before per-row authorization runs (the old 0-rows-imported behavior is
    superseded)."""
    data = _csv([_row()])
    uploaded = client.post(BASE, headers=_headers("intel_sales_admin"),
                           files={"file": ("observations.csv", data, "text/csv")})
    assert uploaded.status_code == 403
    assert uploaded.json()["detail"] == "Sales admin cannot modify account content"
    batch = _import(client, [_row()])
    deleted = client.delete(f"{BASE}{batch['import_id']}/", headers=_headers("intel_sales_admin"))
    assert deleted.status_code == 403


def test_auditor_write_block_applies_to_generic_import(client, db_session, world):
    """App-wide RBAC invariant: auditors are read-only everywhere (and the
    central policy denies every write capability for them), so the generic
    import's mutating surfaces 403 before per-row authorization runs — the
    same behavior as every other write endpoint. Read access is unaffected."""
    data = _csv([_row()])
    uploaded = client.post(BASE, headers=_headers("intel_auditor"),
                           files={"file": ("observations.csv", data, "text/csv")})
    assert uploaded.status_code == 403
    batch = _import(client, [_row()])
    deleted = client.delete(f"{BASE}{batch['import_id']}/", headers=_headers("intel_auditor"))
    assert deleted.status_code == 403
    detail = client.get(f"{BASE}{batch['import_id']}/", headers=_headers("intel_auditor"))
    assert detail.status_code == 200
    assert db_session.query(RepIntelligenceImport).count() == 1


def test_gated_inside_sales_requires_intel_uploads_grant(client, db_session, world):
    inside = _user(db_session, "intel_inside", sales_role="inside_sales")
    membership = AccountMembership(customer_id=world["acme"].id, user_id=inside.id,
                                   role="inside_sales", section_grants={"notes": "contribute"})
    db_session.add(membership)
    db_session.commit()
    first = _import(client, [_row()], "intel_inside")
    assert first["status"] == "failed"
    membership.section_grants = {"intel_uploads": "contribute"}
    db_session.commit()
    second = _import(client, [_row()], "intel_inside")
    assert second["status"] == "completed"


def test_history_visibility_and_detail_customer_redaction(client, db_session, world):
    private = _import(client, [_row(customer_name=world["globex"].name)], "intel_rep_b")
    shared = _import(client, [_row(), _row(customer_name=world["globex"].name),
                              _row(customer_name="Missing Testing Corp")])
    own_failed = _import(client, [_row(customer_name=world["globex"].name)], "intel_rep_a")
    visible = client.get(BASE, headers=_headers("intel_rep_a")).json()
    assert [entry["import_id"] for entry in visible] == [own_failed["import_id"], shared["import_id"]]
    assert set(visible[0]) == {"import_id", "file_name", "created_at", "imported_by", "total_rows",
                               "imported_rows", "imported_with_issues", "skipped_rows", "status",
                               "technologies_created", "technologies_refreshed"}
    assert len(client.get(BASE, headers=_headers()).json()) == 3
    assert client.get(BASE, headers=_headers("intel_outsider")).json() == []
    for import_id in (private["import_id"], 99999):
        response = client.get(f"{BASE}{import_id}/", headers=_headers("intel_rep_a"))
        assert response.status_code == 404 and response.json() == {"detail": "Import not found"}
    body = _detail(client, shared["import_id"], "intel_rep_a")
    assert body["can_manage"] is False
    assert body["matched"] == [{"customer_id": world["acme"].id,
                                "customer_name": world["acme"].name}]
    assert body["affected_customer_ids"] == [world["acme"].id]
    assert body["matched_out_of_scope"] == 1
    assert len(body["rows"]) == 2
    assert body["rows"][0]["customer_name_supplied"] == world["acme"].name
    assert body["rows"][1]["customer_name_supplied"] is None
    full = _detail(client, shared["import_id"])
    assert full["rows"][1]["customer_name_supplied"] == world["globex"].name
    assert full["rows"][2]["customer_name_supplied"] == "Missing Testing Corp"
    own = _detail(client, own_failed["import_id"], "intel_rep_a")
    assert own["can_manage"] is True
    assert own["rows"][0]["customer_name_supplied"] == world["globex"].name


@pytest.mark.parametrize("action", ["source", "issues", "delete"])
def test_management_is_restricted_to_importer_or_admin(client, db_session, world, action):
    body = _import(client, [_row()], "intel_owner")
    url = f"{BASE}{body['import_id']}/" + {"source": "source/", "issues": "issues.csv/",
                                         "delete": ""}[action]
    call = client.delete if action == "delete" else client.get
    denied = call(url, headers=_headers("intel_observer"))
    assert denied.status_code == 403
    assert call(url, headers=_headers("intel_owner")).status_code == 200
    if action != "delete":
        assert call(url, headers=_headers()).status_code == 200
    else:
        another = _import(client, [_row()], "intel_owner")
        assert client.delete(f"{BASE}{another['import_id']}/", headers=_headers()).status_code == 200


def test_delete_hidden_batch_is_404_and_missing_resources_are_404(client, db_session, world):
    body = _import(client, [_row(customer_name=world["globex"].name)], "intel_rep_b")
    assert client.delete(f"{BASE}{body['import_id']}/", headers=_headers("intel_rep_a")).status_code == 404
    for suffix in ("", "source/", "issues.csv/"):
        assert client.get(f"{BASE}99999/{suffix}", headers=_headers()).status_code == 404


@pytest.mark.parametrize("suffix", ["source/", "issues.csv/"])
def test_hidden_batch_source_and_issues_are_404_first(client, db_session, world, suffix):
    # an import the caller cannot see is the same 404
    # as a missing one; a visible import keeps the exact management 403.
    hidden = _import(client, [_row(customer_name=world["globex"].name)], "intel_rep_b")
    out_of_scope = client.get(f"{BASE}{hidden['import_id']}/{suffix}", headers=_headers("intel_rep_a"))
    missing = client.get(f"{BASE}99999/{suffix}", headers=_headers("intel_rep_a"))
    assert out_of_scope.status_code == missing.status_code == 404
    assert out_of_scope.json() == missing.json()
    visible = _import(client, [_row()], "intel_owner")
    denied = client.get(f"{BASE}{visible['import_id']}/{suffix}", headers=_headers("intel_observer"))
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Only the importer or system admin may manage this import"


def test_delete_by_importer_reverts_only_exact_owned_tech_and_audits(client, db_session, world):
    manual = CustomerTechnology(customer_id=world["acme"].id, name="Manual Platform",
                                category="software", source="manual", notes="preserved")
    adjacent = CustomerTechnology(customer_id=world["acme"].id, name="Other Batch Platform",
                                  category="hardware", source="generic intelligence import #10")
    db_session.add_all([manual, adjacent])
    db_session.commit()
    body = _import(client, [_row(), _row(technology_name="Manual Platform"),
                            _row(customer_name="Missing Testing Corp")], "intel_owner")
    response = client.delete(f"{BASE}{body['import_id']}/", headers=_headers("intel_owner"))
    assert response.status_code == 200, response.text
    assert response.json() == {"detail": "Import deleted", "deleted_rows": 3,
                               "deleted_technologies": 1}
    db_session.expire_all()
    assert db_session.get(RepIntelligenceImport, body["import_id"]) is None
    assert db_session.query(RepIntelligenceRow).count() == 0
    assert {tech.name for tech in db_session.query(CustomerTechnology)} == {
        "Manual Platform", "Other Batch Platform",
    }
    audit = db_session.query(AuditLog).filter_by(action="rep_intelligence_import.delete").one()
    assert audit.username == "intel_owner" and audit.target_id == body["import_id"]
    assert json.loads(audit.details)["deleted_rows"] == 3
    assert json.loads(audit.details)["deleted_technologies"] == 1


def test_delete_current_owner_keeps_older_batch_evidence_without_dangling_fk(client, db_session, world):
    first = _import(client, [_row()])
    second = _import(client, [_row()])
    response = client.delete(f"{BASE}{second['import_id']}/", headers=_headers())
    assert response.status_code == 200 and response.json()["deleted_technologies"] == 1
    remaining = _detail(client, first["import_id"])
    assert len(remaining["rows"]) == 1 and remaining["rows"][0]["technology_id"] is None
    assert remaining["rows"][0]["technology_name_supplied"] == "Synthetic Platform"


def test_source_preserves_bytes_and_sanitizes_filename(client, db_session, world):
    data = _csv([_row()])
    response = _upload(client, data, filename="../../nested/observations.csv")
    assert response.status_code == 201
    download = client.get(f"{BASE}{response.json()['import_id']}/source/", headers=_headers())
    assert download.status_code == 200 and download.content == data
    assert 'filename="observations.csv"' in download.headers["content-disposition"]
    assert "../" not in download.headers["content-disposition"]
    assert download.headers["content-type"].startswith("text/csv")


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_issues_csv_is_formula_safe_and_notes_stay_verbatim(client, db_session, world, prefix):
    name = prefix + "Formula Testing Corp"
    customer = Customer(name=name)
    db_session.add(customer)
    db_session.commit()
    note = "=SUM(1,2)"
    body = _import(client, [_row(customer_name=name, technology_name=prefix + "Platform",
                                currency="invalid!", amount="invalid!", notes=note)])
    assert body["rows"][0]["notes"] == note
    response = client.get(f"{BASE}{body['import_id']}/issues.csv/", headers=_headers())
    assert response.status_code == 200
    reader = csv.DictReader(io.StringIO(response.text, newline=""))
    assert reader.fieldnames == list(ISSUE_HEADER)
    rows = list(reader)
    assert [row["field"] for row in rows] == ["amount", "currency"]
    for row in rows:
        assert row["customer_name"] == "'" + name
        assert row["technology_name"] == "'" + prefix + "Platform"
    assert f'filename="import-{body["import_id"]}-issues.csv"' in response.headers[
        "content-disposition"
    ]
    assert client.get(f"{BASE}{body['import_id']}/issues.csv/", headers=_headers()).content == (
        response.content
    )


def test_no_issue_report_is_header_only(client, db_session, world):
    body = _import(client, [_row()])
    response = client.get(f"{BASE}{body['import_id']}/issues.csv/", headers=_headers())
    assert response.status_code == 200
    assert list(csv.reader(io.StringIO(response.text))) == [list(ISSUE_HEADER)]


def test_unexpected_import_failure_rolls_back_everything(client, db_session, world, monkeypatch):
    real_technology = service._technology
    calls = 0

    def fail_later(*args, **kwargs):
        nonlocal calls
        calls += 1
        real_technology(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("synthetic infrastructure failure")

    monkeypatch.setattr(service, "_technology", fail_later)
    with pytest.raises(RuntimeError, match="synthetic infrastructure failure"):
        _upload(client, _csv([_row(), _row(technology_name="Second Platform")]))
    db_session.expire_all()
    assert db_session.query(RepIntelligenceImport).count() == 0
    assert db_session.query(RepIntelligenceRow).count() == 0
    assert db_session.query(CustomerTechnology).count() == 0
    assert db_session.query(AuditLog).filter_by(action="rep_intelligence_import.create").count() == 0


def test_audit_failure_rolls_back_delete(client, db_session, world, monkeypatch):
    body = _import(client, [_row()])

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(service, "_audit_import", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        client.delete(f"{BASE}{body['import_id']}/", headers=_headers())
    db_session.expire_all()
    assert db_session.get(RepIntelligenceImport, body["import_id"]) is not None
    assert db_session.query(RepIntelligenceRow).one().technology_id == body["rows"][0]["technology_id"]
    assert db_session.query(CustomerTechnology).count() == 1
    assert db_session.query(AuditLog).filter_by(action="rep_intelligence_import.delete").count() == 0


@pytest.mark.parametrize("method,suffix", [
    ("get", ""), ("get", "1/"), ("get", "1/source/"), ("get", "1/issues.csv/"), ("delete", "1/"),
])
def test_history_and_management_require_authentication(client, db_session, world, method, suffix):
    assert getattr(client, method)(BASE + suffix).status_code == 401


def test_upload_requires_authentication(client, db_session, world):
    assert _upload(client, _csv([_row()]), headers={}).status_code == 401


def test_revoked_importer_detail_and_source(client, db_session, world):
    body = _import(client, [_row()], "intel_owner")
    import_id = body["import_id"]
    db_session.query(CustomerUser).filter_by(user_id=world["owner"].id, customer_id=world["acme"].id).delete()
    db_session.commit()
    revoked = _detail(client, import_id, "intel_owner")
    assert revoked["can_manage"] is True
    assert revoked["rows"] == revoked["matched"] == revoked["affected_customer_ids"] == []
    assert revoked["matched_out_of_scope"] == 1
    admin = _detail(client, import_id)
    assert admin["rows"][0]["customer_name"] == world["acme"].name
    assert client.get(f"{BASE}{import_id}/source/", headers=_headers("intel_owner")).status_code == 200
