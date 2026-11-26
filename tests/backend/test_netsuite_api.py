"""NetSuite persistence, rematch, scope, privacy and risk acceptance (synthetic)."""

import json
from datetime import date

import pytest
from backend.models.collaboration import AuditLog
from backend.models.customer_alias import CustomerAlias
from backend.models.customer_technology import CustomerTechnology
from backend.models.netsuite_import import NetSuiteImport, NetSuiteImportNote, NetSuiteImportRow
from backend.models.sales_access import SalesReporting
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import netsuite_import_service as service
from backend.services import record_cleanup
from backend.services.customers_service import delete_customer_with_use_cases
from sqlalchemy import select

from tests.backend.test_customer_contacts import headers
from tests.backend.test_netsuite_import import HEADERS, line, report

BASE = "/api/netsuite-import/"


def upload(client, rows, username="admin", extra_headers=None, extension="csv"):
    data = report(rows, extension, HEADERS + (extra_headers or []))
    return client.post(BASE, headers=headers(username), files={"file": ("synthetic." + extension, data)})


@pytest.fixture
def customer(db_session):
    customer = Customer(name="Synthetic Customer")
    db_session.add(customer)
    db_session.commit()
    return customer


def test_write_risks_observations_and_duplicate_hash(client, db_session, customer):
    rows = [line(end="2026-10-30") + ["Exact original note  "],
            line(end="2026-10-30", detail="Resource Downgrade", quantity=-1) + ["Exact original note  "],
            line(subscription="ended", status="Terminated", end="2026-11-30"),
            line(subscription="monthly", term="1", end="2026-10-30")]
    response = upload(client, rows, extra_headers=["Notes"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["matched_rows"] == 4 and result["matched_accounts"] == 1
    assert result["technologies_created"] == 1 and result["risks_created"] == 4
    assert result["observations_created"] == 1
    assert {key.kind for key in db_session.query(NetSuiteImportNote) if not key.kind.startswith("observation:")} == {
        "term_ending", "downgrade", "terminated"}
    risks = db_session.query(SalesNote).filter_by(category="risk").all()
    assert len(risks) == 4 and all(n.verification_state == "inferred" for n in risks)
    assert all(n.source == f"NetSuite import #{result['import_id']}" and n.related_technology_ids for n in risks)
    note = db_session.query(SalesNote).filter_by(category="account_observation").one()
    assert note.content == "Exact original note  " and note.verification_state == "verified"
    tech = db_session.query(CustomerTechnology).filter_by(customer_id=customer.id).one()
    assert tech.quantity == 10 and tech.end_of_support_date is None
    assert tech.date_observed == date(2026, 9, 30)
    before = db_session.query(AuditLog).filter_by(action="netsuite_import.create").count()
    duplicate = upload(client, rows, extra_headers=["Notes"])
    assert duplicate.status_code == 200 and duplicate.json()["import_id"] == result["import_id"]
    assert db_session.query(NetSuiteImport).count() == 1 and db_session.query(SalesNote).count() == 5
    assert db_session.query(AuditLog).filter_by(action="netsuite_import.create").count() == before == 1
    assert client.get(BASE, headers=headers()).json()[0]["import_id"] == result["import_id"]
    assert client.get(f"{BASE}{result['import_id']}/unmatched/", headers=headers()).json() == []


def test_later_import_refreshes_keys_missing_products_untouched_and_older_protected(client, db_session, customer):
    first = upload(client, [line(end="2026-10-30"), line(subscription="retained", product="Adobe Acrobat", quantity=2)])
    assert first.status_code == 200, first.text
    note_id = db_session.query(SalesNote).filter_by(category="risk").one().id
    retained = db_session.query(CustomerTechnology).filter_by(name="Adobe Acrobat").one()
    retained_id, observed = retained.id, retained.date_observed
    second = upload(client, [line(quantity=8, invoice="2026-10-01", end="2026-11-30")])
    assert second.status_code == 200, second.text
    assert second.json()["risks_created"] == 0 and second.json()["risks_refreshed"] == 1
    assert db_session.query(SalesNote).filter_by(category="risk").one().id == note_id
    db_session.expire_all()
    assert db_session.get(CustomerTechnology, retained_id).date_observed == observed
    tech = db_session.query(CustomerTechnology).filter_by(name="Microsoft 365 Business").one()
    assert tech.quantity == 8
    third = upload(client, [line(quantity=999, invoice="2026-08-01", end="2026-09-01")])
    assert third.status_code == 200, third.text
    db_session.expire_all()
    assert db_session.get(CustomerTechnology, tech.id).quantity == 8
    assert db_session.get(SalesNote, note_id).note_date == date(2026, 10, 1)


def test_other_source_preserved_and_unclassified_staged(client, db_session, customer):
    tech = CustomerTechnology(customer_id=customer.id, name="Microsoft 365 Business", category="software",
                              quantity=77, source="Human inventory", notes="Keep this", end_of_support_date=date(2030, 1, 1))
    db_session.add(tech)
    db_session.commit()
    before = tech.to_dict()
    response = upload(client, [line(end="2026-10-30"), line(product="Unknown product", subscription="unknown", uom="unknown")])
    assert response.status_code == 200, response.text
    assert response.json()["technologies_associated"] == 1 and response.json()["skipped_rows"] == 1
    db_session.expire_all()
    assert db_session.get(CustomerTechnology, tech.id).to_dict() == before
    assert db_session.query(CustomerTechnology).count() == 1
    stage = db_session.query(NetSuiteImportRow).filter_by(subscription_id="unknown").one()
    assert stage.customer_id == customer.id and stage.technology_id is None
    assert stage.reason == "Product category is unknown"
    assert db_session.query(SalesNote).one().related_technology_ids == [tech.id]


def test_manual_alias_rematch_no_upload_or_alias_creation(client, db_session, customer):
    response = upload(client, [line(customer="Synthetic Customer Inc"), line(customer="Unmatched source")])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["matched_rows"] == 0 and result["skipped"][0]["suggestion"]["customer_id"] == customer.id
    assert db_session.query(CustomerAlias).count() == 0
    db_session.add(CustomerAlias(customer_id=customer.id, alias="Synthetic Customer Inc", alias_norm="synthetic customer inc"))
    db_session.commit()
    response = client.post(f"{BASE}{result['import_id']}/rematch/", headers=headers())
    assert response.status_code == 200, response.text
    assert response.json()["matched_rows"] == 1 and response.json()["rows"][0]["matched_by"] == "alias"
    assert db_session.query(CustomerAlias).count() == 1 and db_session.query(NetSuiteImport).count() == 1
    assert db_session.query(CustomerTechnology).one().quantity == 5
    assert client.post(f"{BASE}{result['import_id']}/rematch/", headers=headers()).status_code == 200
    assert db_session.query(CustomerTechnology).count() == 1


@pytest.mark.parametrize("role", ["rep", "inside_sales", "sales_admin", "sales_ops", "auditor", "user", "ps_admin"])
def test_role_matrix_all_routes(client, db_session, role):
    user = User(username="netsuite_" + role, sales_role=role if role != "ps_admin" else None,
                role="ps_admin" if role == "ps_admin" else "user", is_active=1, approved=1)
    db_session.add(user)
    db_session.commit()
    for method, path in (("get", BASE), ("get", BASE + "999/"), ("get", BASE + "999/unmatched/"),
                         ("post", BASE + "999/rematch/")):
        assert getattr(client, method)(path, headers=headers(user.username)).status_code == 403
    assert upload(client, [line()], user.username).status_code == 403
    assert db_session.query(NetSuiteImport).count() == 0


def test_unauthenticated_and_missing_matrix(client, db_session):
    for method, path in (("get", BASE), ("get", BASE + "999/"), ("get", BASE + "999/unmatched/"),
                         ("post", BASE + "999/rematch/")):
        assert getattr(client, method)(path).status_code == 401
    response = client.post(BASE, files={"file": ("test.csv", report([line()]))})
    assert response.status_code == 401
    for path in (BASE + "999/", BASE + "999/unmatched/"):
        assert client.get(path, headers=headers()).status_code == 404
    assert client.post(BASE + "999/rematch/", headers=headers()).status_code == 404


def manager_fixture(db_session, customer):
    manager = User(username="netsuite_manager", sales_role="sales_manager", is_active=1, approved=1)
    other = User(username="netsuite_other_manager", sales_role="sales_manager", is_active=1, approved=1)
    rep = User(username="netsuite_rep", sales_role="rep", is_active=1, approved=1)
    outside = Customer(name="Synthetic Outside")
    db_session.add_all([manager, other, rep, outside])
    db_session.flush()
    db_session.add(SalesReporting(manager_user_id=manager.id, rep_user_id=rep.id))
    db_session.add(CustomerUser(customer_id=customer.id, user_id=rep.id, role="owner"))
    db_session.commit()
    return manager, other, rep, outside


def test_manager_scope_duplicate_privacy_and_revocation(client, db_session, customer):
    manager, other, rep, outside = manager_fixture(db_session, customer)
    rows = [line(), line(customer=outside.name, subscription="outside", end="2026-10-30"),
            line(customer="Synthetic Outside Inc", subscription="suggestion")]
    response = upload(client, rows, manager.username)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["matched_accounts"] == 1 and result["matched_rows"] == 1
    assert all(r["customer_name"] != outside.name for r in result["rows"])
    assert all(r.get("suggestion") is None for r in result["skipped"])
    assert db_session.query(CustomerTechnology).filter_by(customer_id=outside.id).count() == 0
    assert client.get(BASE, headers=headers(other.username)).json() == []
    for suffix in ("", "unmatched/"):
        assert client.get(f"{BASE}{result['import_id']}/{suffix}", headers=headers(other.username)).status_code == 404
    assert client.post(f"{BASE}{result['import_id']}/rematch/", headers=headers(other.username)).status_code == 404
    assert upload(client, rows, other.username).status_code == 404
    assert db_session.query(NetSuiteImport).count() == 1
    db_session.query(CustomerUser).filter_by(customer_id=customer.id, user_id=rep.id).delete()
    db_session.commit()
    result = client.get(f"{BASE}{result['import_id']}/", headers=headers(manager.username)).json()
    assert result["matched_rows"] == 0 and result["matched_accounts"] == 0
    assert all(r["customer_id"] != customer.id for r in result["rows"])
    before = db_session.query(CustomerTechnology).one().to_dict()
    assert client.post(f"{BASE}{result['import_id']}/rematch/", headers=headers(manager.username)).status_code == 200
    db_session.expire_all()
    assert db_session.query(CustomerTechnology).one().to_dict() == before


def test_service_role_gate_cannot_be_bypassed(db_session):
    for user in (None, {"username": "auditor", "sales_role": "auditor"}):
        with pytest.raises(Exception) as caught:
            service.history(db_session, user)
        assert caught.value.status_code in {401, 403}


def test_atomic_rollback_on_audit_failure(client, db_session, customer, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        upload(client, [line(end="2026-10-30") + ["Synthetic observation"]], extra_headers=["Notes"])
    assert db_session.query(NetSuiteImport).count() == 0
    assert db_session.query(NetSuiteImportRow).count() == 0
    assert db_session.query(NetSuiteImportNote).count() == 0
    assert db_session.query(CustomerTechnology).count() == 0
    assert db_session.query(SalesNote).count() == 0


@pytest.mark.parametrize("layout", ["csv", "xlsx"])
def test_financial_exclusion_through_api_db_audit_logs(client, db_session, customer, caplog, layout):
    from pathlib import Path

    layouts = json.loads((Path(__file__).parent / "fixtures" / "netsuite_headers.json").read_text())
    allowed = dict(zip(HEADERS, line(end="2026-10-30"), strict=True))
    values, sentinels = [], []
    for index, header in enumerate(layouts[layout]):
        if header.strip() in allowed:
            values.append(allowed[header.strip()])
        else:
            sentinel = f"FINANCIAL-SECRET-{index}-87654321"
            sentinels.append(sentinel)
            values.append(sentinel)
    response = client.post(BASE, headers=headers(), files={"file": ("synthetic." + layout,
                           report([values], layout, layouts[layout]))})
    assert response.status_code == 200, response.text
    serialized = response.text + caplog.text
    for table in (NetSuiteImport.__table__, NetSuiteImportRow.__table__, NetSuiteImportNote.__table__,
                  CustomerTechnology.__table__, SalesNote.__table__, AuditLog.__table__):
        serialized += json.dumps([dict(row) for row in db_session.execute(select(table)).mappings()], default=str)
    serialized += client.get(BASE, headers=headers()).text
    serialized += client.get(f"{BASE}{response.json()['import_id']}/", headers=headers()).text
    assert all(sentinel not in serialized for sentinel in sentinels)
    assert all(column.type.__class__.__name__ != "LargeBinary" for column in NetSuiteImport.__table__.columns)


def test_record_and_customer_cleanup_prevents_rematch_resurrection(client, db_session, customer):
    response = upload(client, [line(end="2026-10-30") + ["Synthetic observation"]], extra_headers=["Notes"])
    assert response.status_code == 200, response.text
    batch_id = response.json()["import_id"]
    tech = db_session.query(CustomerTechnology).one()
    risk = db_session.query(SalesNote).filter_by(category="risk").one()
    record_cleanup.technologies(db_session, [tech.id])
    db_session.delete(tech)
    record_cleanup.sales_notes(db_session, [risk.id])
    db_session.delete(risk)
    db_session.commit()
    db_session.expire_all()
    stage = db_session.query(NetSuiteImportRow).one()
    assert stage.technology_id is None and stage.risk_note_id is None
    assert db_session.query(NetSuiteImportNote).filter_by(kind="term_ending").one().note_id is None
    delete_customer_with_use_cases(db_session, customer)
    db_session.commit()
    db_session.expire_all()
    stage = db_session.query(NetSuiteImportRow).one()
    assert stage.customer_id is None and stage.disposition == "customer_deleted"
    assert db_session.query(NetSuiteImportNote).count() == 0
    db_session.add(Customer(name="Synthetic Customer"))
    db_session.commit()
    assert client.post(f"{BASE}{batch_id}/rematch/", headers=headers()).status_code == 200
    assert db_session.query(CustomerTechnology).count() == 0 and db_session.query(SalesNote).count() == 0


@pytest.mark.parametrize("end,term,term_type,expected", [
    ("2026-12-29", "12", "Months", 1),  # exactly 90 days after invoice
    ("2026-12-30", "12", "Months", 0),
    ("2026-09-29", "12", "Months", 0),
    ("2026-09-30", "1", "Year", 1),
    ("2026-10-15", "1", "Months", 0),
    ("2026-10-15", "", "", 0),
    ("2026-10-15", "36", "Months", 1),
])
def test_risk_term_boundary(client, db_session, customer, end, term, term_type, expected):
    response = upload(client, [line(end=end, term=term, term_type=term_type)])
    assert response.status_code == 200, response.text
    assert response.json()["risks_created"] == expected
    assert db_session.query(SalesNote).filter_by(category="risk").count() == expected


def test_scope_expansion_rematch_and_scoped_counters(client, db_session, customer):
    manager, other, rep, outside = manager_fixture(db_session, customer)
    response = upload(client, [line(end="2026-10-30"),
                              line(customer=outside.name, subscription="outside", end="2026-10-30")], manager.username)
    assert response.status_code == 200, response.text
    batch_id = response.json()["import_id"]
    assert response.json()["risks_created"] == 1
    db_session.add(CustomerUser(customer_id=outside.id, user_id=rep.id, role="owner"))
    db_session.commit()
    response = client.post(f"{BASE}{batch_id}/rematch/", headers=headers(manager.username))
    assert response.status_code == 200, response.text
    assert response.json()["matched_accounts"] == 2
    assert response.json()["risks_created"] == 1 and response.json()["risks_refreshed"] == 1
    assert db_session.query(CustomerTechnology).count() == 2
    db_session.query(CustomerUser).filter_by(customer_id=outside.id, user_id=rep.id).delete()
    db_session.commit()
    summary = client.get(BASE, headers=headers(manager.username)).json()[0]
    assert summary["matched_accounts"] == 1 and summary["risks_created"] == 0 and summary["risks_refreshed"] == 1


def test_ambiguous_technology_never_overwritten(client, db_session, customer):
    db_session.add_all([CustomerTechnology(customer_id=customer.id, name="Microsoft 365 Business", category="software", quantity=q)
                        for q in (7, 8)])
    db_session.commit()
    response = upload(client, [line()])
    assert response.status_code == 200, response.text
    assert response.json()["matched_rows"] == 0
    assert response.json()["skipped"][0]["reason"] == "Ambiguous existing technology"
    assert sorted(t.quantity for t in db_session.query(CustomerTechnology)) == [7, 8]


def test_normalized_product_names_aggregate_before_writing(client, db_session, customer):
    response = upload(client, [line(quantity=2), line(subscription="second", product="Microsoft  365 Business", quantity=3)])
    assert response.status_code == 200, response.text
    assert db_session.query(CustomerTechnology).one().quantity == 5


def test_human_reclassified_risk_is_preserved(client, db_session, customer):
    response = upload(client, [line(end="2026-10-30")])
    assert response.status_code == 200
    risk = db_session.query(SalesNote).one()
    risk.category = "account_observation"
    risk.verification_state = "verified"
    risk.content = "Human assessment, retain"
    db_session.commit()
    response = upload(client, [line(invoice="2026-10-01", end="2026-10-30")])
    assert response.status_code == 200
    db_session.expire_all()
    assert db_session.get(SalesNote, risk.id).content == "Human assessment, retain"
    assert db_session.query(SalesNote).count() == 1


def test_failed_rematch_rolls_back_existing_results(client, db_session, customer, monkeypatch):
    response = upload(client, [line(customer="Synthetic Alias")])
    assert response.status_code == 200
    batch_id = response.json()["import_id"]
    db_session.add(CustomerAlias(customer_id=customer.id, alias="Synthetic Alias", alias_norm="synthetic alias"))
    db_session.commit()

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic rematch audit failure")

    monkeypatch.setattr(service, "_audit", fail)
    with pytest.raises(RuntimeError, match="synthetic rematch audit failure"):
        client.post(f"{BASE}{batch_id}/rematch/", headers=headers())
    assert db_session.query(CustomerTechnology).count() == 0
    assert db_session.query(NetSuiteImportRow).one().disposition == "skipped"
    assert db_session.get(NetSuiteImport, batch_id).matched_rows == 0


@pytest.mark.parametrize("same_file", [True, False])
def test_concurrent_imports_keep_one_inventory_and_risk_identity(db_session, customer, same_file):
    import asyncio
    import io
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy.engine.create import create_engine
    from sqlalchemy.orm import Session
    from starlette.datastructures import UploadFile

    db_session.commit()
    engine = create_engine(db_session.get_bind().url, pool_size=2, max_overflow=0,
                           connect_args={"timeout": 15} if db_session.bind.dialect.name == "sqlite" else {})
    barrier = Barrier(2, timeout=15)
    actor = {"username": "admin", "is_admin": 1}

    def run(index):
        data = report([line(quantity=5 if same_file else 5 + index, end="2026-10-30")])
        upload_file = UploadFile(filename="synthetic.csv", file=io.BytesIO(data))
        with Session(engine) as session:
            barrier.wait()
            return asyncio.run(service.import_file(session, upload_file, actor))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run, (0, 1)))
        db_session.expire_all()
        assert len({r["import_id"] for r in results}) == (1 if same_file else 2)
        assert db_session.query(NetSuiteImport).count() == (1 if same_file else 2)
        assert db_session.query(CustomerTechnology).count() == 1
        assert db_session.query(SalesNote).count() == 1
        assert db_session.query(NetSuiteImportNote).count() == 1
    finally:
        engine.dispose()


def test_rematch_older_batch_cannot_replace_same_invoice_correction(client, db_session, customer):
    first = upload(client, [line(quantity=5, end="2026-10-30")])
    second = upload(client, [line(quantity=9, end="2026-11-30")])
    assert first.status_code == second.status_code == 200
    assert client.post(f"{BASE}{first.json()['import_id']}/rematch/", headers=headers()).status_code == 200
    db_session.expire_all()
    tech = db_session.query(CustomerTechnology).one()
    note = db_session.query(SalesNote).one()
    assert tech.quantity == 9
    assert tech.source == note.source == f"NetSuite import #{second.json()['import_id']}"
    assert "2026-11-30" in note.content


def test_two_managers_share_digest_and_rematch_only_their_customers(client, db_session, customer):
    manager, other, rep, outside = manager_fixture(db_session, customer)
    db_session.add(CustomerUser(customer_id=outside.id, user_id=other.id, role="owner"))
    db_session.commit()
    rows = [line(), line(customer=outside.name, subscription="outside", end="2026-10-30"),
            line(customer="Synthetic Unresolved Secret", subscription="unknown")]
    first = upload(client, rows, manager.username)
    assert first.status_code == 200, first.text
    batch_id = first.json()["import_id"]
    second = upload(client, rows, other.username)
    assert second.status_code == 200, second.text
    assert second.json()["import_id"] == batch_id
    assert all(row["customer_name"] == outside.name for row in second.json()["rows"])
    assert second.json()["matched_rows"] == 0
    rematched = client.post(f"{BASE}{batch_id}/rematch/", headers=headers(other.username))
    assert rematched.status_code == 200, rematched.text
    assert rematched.json()["matched_rows"] == 1 and rematched.json()["matched_accounts"] == 1
    assert rematched.json()["risks_created"] == 1
    assert all(row["customer_id"] == outside.id for row in rematched.json()["rows"])
    original = client.get(f"{BASE}{batch_id}/", headers=headers(manager.username)).json()
    assert original["matched_accounts"] == 1
    assert all(row["customer_id"] != outside.id for row in original["rows"])
    assert db_session.query(CustomerTechnology).count() == 2
    assert db_session.query(NetSuiteImport).count() == 1
    summaries = client.get(BASE, headers=headers(other.username)).json()
    assert len(summaries) == 1 and summaries[0]["matched_accounts"] == 1
