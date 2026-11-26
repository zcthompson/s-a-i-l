"""Account strategy contract checks."""
from datetime import UTC, date, datetime

import pytest
from backend.models.use_case import Customer
from backend.services import account_strategy as service
from fastapi import HTTPException

from tests.backend.test_customer_contacts import statements


@pytest.fixture
def customer_id(db_session):
    row = Customer(name="Strategy test")
    db_session.add(row)
    db_session.commit()
    return row.id


def test_empty_and_deterministic(db_session, customer_id):
    args = {"reference_date": date(2026, 10, 28), "as_of": datetime(2026, 10, 28, tzinfo=UTC)}
    with statements(db_session) as sql:
        result = service.get_strategy(db_session, customer_id, **args)
    assert result["plan"] is None
    assert result["snapshots"] == {"count": 0, "latest": None}
    suggestions = result["suggestions"]
    assert all(not suggestions[key] for key in ("objectives", "desired_outcomes", "risks", "plays", "next_actions"))
    assert [x["text"] for x in suggestions["discovery_gaps"]] == ["No contacts recorded", "No economic buyer recorded", "No champion recorded", "No recorded activity or dated note — source: engagement basis"]
    assert suggestions == service.suggestions_for(db_session, customer_id, **args)
    assert len(sql) == 11


def test_draft_snapshot_and_restore(db_session, customer_id):
    row = service.save_strategy(db_session, customer_id, {"expected_version": 0, "objectives": "one"}, "alice")
    assert row["version"] == 1
    snap = service.publish_snapshot(db_session, customer_id, {}, "alice")
    assert snap["content"]["objectives"] == "one"
    row = service.save_strategy(db_session, customer_id, {"expected_version": 1, "objectives": None, "risks": "risk"}, "alice")
    assert row["version"] == 2
    with pytest.raises(HTTPException, match=service.CONFLICT):
        service.save_strategy(db_session, customer_id, {"expected_version": 1}, "alice")
    row = service.restore_snapshot(db_session, customer_id, snap["id"], {"expected_version": 2}, "alice")
    assert row["objectives"] == "one" and row["risks"] is None
    assert service.get_snapshot(db_session, customer_id, snap["id"]) == snap
    assert service.list_snapshots(db_session, customer_id)[0]["plan_number"] == 1


def test_http_validation_and_snapshots(client, customer_id):
    from tests.backend.test_customer_contacts import headers
    auth = headers()
    path = f"/api/customers/{customer_id}/strategy/"
    for payload, status, detail in [
        ({}, 422, "expected_version is required"),
        ({"expected_version": "1"}, 422, "expected_version must be an integer"),
        ({"expected_version": 1}, 409, service.CONFLICT),
        ({"expected_version": 0, "risks": 3}, 422, "Field risks must be a string or null"),
        ({"expected_version": 0, "risks": "x" * 10001}, 422, "Field risks must be at most 10000 characters"),
    ]:
        response = client.put(path, headers=auth, json=payload)
        assert response.status_code == status and response.json()["detail"] == detail
    response = client.post(path + "snapshots/", headers=auth, json={})
    assert response.status_code == 422 and response.json()["detail"] == "No strategy content recorded to publish"
    assert client.put(path, headers=auth, json={"expected_version": 0, "objectives": "one"}).json()["version"] == 1
    for note, detail in [(12, "note must be a string"), ("x" * 201, "note must be at most 200 characters")]:
        response = client.post(path + "snapshots/", headers=auth, json={"note": note})
        assert response.status_code == 422 and response.json()["detail"] == detail
    first = client.post(path + "snapshots/", headers=auth, json={"note": "first"})
    assert first.status_code == 201 and first.json()["plan_number"] == 1
    assert client.put(path, headers=auth, json={"expected_version": 1, "objectives": None, "risks": "risk"}).json()["version"] == 2
    assert client.post(path + "snapshots/", headers=auth, json={}).json()["plan_number"] == 2
    assert [s["plan_number"] for s in client.get(path + "snapshots/", headers=auth).json()["snapshots"]] == [2, 1]
    snapshot_path = f"/api/strategy-snapshots/{first.json()['id']}/"
    assert client.get(snapshot_path, headers=auth).json() == first.json()
    assert client.get("/api/strategy-snapshots/999999/", headers=auth).status_code == 404
    assert client.put(snapshot_path, headers=auth, json={}).status_code in (404, 405)
    assert client.delete(snapshot_path, headers=auth).status_code in (404, 405)
    response = client.post(snapshot_path + "restore/", headers=auth, json={"expected_version": 1})
    assert response.status_code == 409 and response.json()["detail"] == service.CONFLICT
    restored = client.post(snapshot_path + "restore/", headers=auth, json={"expected_version": 2}).json()
    assert restored["version"] == 3 and restored["objectives"] == "one" and restored["risks"] is None
    assert client.get(snapshot_path, headers=auth).json() == first.json()


def test_links_validation_and_replacement(client, db_session, customer_id):
    from backend.models.customer_contact import CustomerContact
    from backend.models.customer_engagement import CustomerTask
    from backend.models.sales_note import SalesNote

    from tests.backend.test_customer_contacts import headers
    other = Customer(name="Foreign strategy")
    db_session.add(other)
    db_session.flush()
    rows = []
    for cid in (customer_id, other.id):
        rows.append((CustomerTask(customer_id=cid, title="task", status="open", created_by="admin"),
                     CustomerContact(customer_id=cid, display_name="contact"),
                     SalesNote(customer_id=cid, category="discovery", title="note", content="text")))
        db_session.add_all(rows[-1])
    db_session.commit()
    path, auth = f"/api/customers/{customer_id}/strategy/", headers()
    empty = {"task_ids": [], "contact_ids": [], "note_ids": []}
    response = client.put(path + "links/", headers=auth, json=empty)
    assert response.status_code == 422 and response.json()["detail"] == "No strategy recorded; save a strategy before linking"
    client.put(path, headers=auth, json={"expected_version": 0})
    for key, label, foreign in zip(empty, ("task", "contact", "note"), rows[1]):
        response = client.put(path + "links/", headers=auth, json={**empty, key: [foreign.id]})
        assert response.status_code == 422 and response.json()["detail"] == f"Related {label} {foreign.id} does not belong to this customer"
        response = client.put(path + "links/", headers=auth, json={**empty, key: "bad"})
        assert response.status_code == 422 and response.json()["detail"] == f"Field {key} must be a list of integers"
    linked = {key: [row.id] for key, row in zip(empty, rows[0])}
    assert all(client.put(path + "links/", headers=auth, json=linked).json().values())
    assert client.put(path + "links/", headers=auth, json=empty).json() == {"tasks": [], "contacts": [], "notes": []}


@pytest.mark.parametrize("kind,read,write", [
    ("owner", 200, 200), ("member", 200, 200), ("inside_strategy", 200, 200),
    ("inside_contacts", 200, 403), ("inside_none", 200, 403), ("legacy_inside", 200, 200),
    ("sales_ops", 200, 403), ("sales_ops_member", 200, 200), ("auditor", 200, 403),
    ("sales_admin", 200, 403), ("ps_admin", 404, 404), ("outsider", 404, 404),
])
def test_route_authorization(client, db_session, customer_id, kind, read, write):
    from backend.models.account_membership import AccountMembership
    from backend.models.sales_access import InsideSalesAssignment, SalesOpsAssignment
    from backend.models.use_case import CustomerUser, User

    from tests.backend.test_customer_contacts import headers
    service.save_strategy(db_session, customer_id, {"expected_version": 0, "objectives": "one"}, "admin")
    snap = service.publish_snapshot(db_session, customer_id, {}, "admin")
    user = User(username="strategy_actor", approved=1, is_active=1, is_admin=0,
                role="ps_admin" if kind == "ps_admin" else None,
                sales_role=kind if kind in ("auditor", "sales_ops", "sales_admin") else "rep")
    db_session.add(user)
    db_session.flush()
    if kind in ("owner", "member", "auditor"):
        db_session.add(CustomerUser(customer_id=customer_id, user_id=user.id, role=kind))
    if kind == "sales_ops":
        db_session.add(SalesOpsAssignment(customer_id=customer_id, user_id=user.id))
    if kind == "sales_ops_member":
        user.sales_role = "sales_ops"
        db_session.add(AccountMembership(customer_id=customer_id, user_id=user.id, role="sales_ops"))
    if kind.startswith("inside_"):
        grants = {"strategy": "contribute"} if kind == "inside_strategy" else ({"contacts": "contribute"} if kind == "inside_contacts" else None)
        db_session.add(AccountMembership(customer_id=customer_id, user_id=user.id, role="inside_sales", section_grants=grants))
    if kind == "legacy_inside":
        user.sales_role = "inside_sales"
        rep = User(username="strategy_rep", sales_role="rep", approved=1, is_active=1, is_admin=0)
        db_session.add(rep)
        db_session.flush()
        db_session.add_all([CustomerUser(customer_id=customer_id, user_id=rep.id, role="owner"), InsideSalesAssignment(inside_sales_user_id=user.id, customer_id=customer_id, rep_user_id=rep.id)])
    db_session.commit()
    auth, path = headers(user.username), f"/api/customers/{customer_id}/strategy/"
    snap_path = f"/api/strategy-snapshots/{snap['id']}/"
    for url in (path, path + "snapshots/", snap_path):
        assert client.get(url, headers=auth).status_code == read
    for url, payload, method in [(path, {"expected_version": 1}, "put"),
                                  (path + "links/", {"task_ids": [], "contact_ids": [], "note_ids": []}, "put"),
                                  (path + "snapshots/", {}, "post"),
                                  (snap_path + "restore/", {"expected_version": 2}, "post")]:
        response = getattr(client, method)(url, headers=auth, json=payload)
        assert response.status_code == (201 if write == 200 and url.endswith("snapshots/") else write), response.text
        if write == 403:
            # The auditor takes the app-wide write block (middleware 403 before
            # the route); every other denied identity gets the route's exact 403.
            expected = "Auditor role is read-only" if kind == "auditor" else "Not authorized to modify this customer"
            assert response.json()["detail"] == expected
    assert client.get(path).status_code == 401


def test_plan_query_budget(db_session, customer_id):
    service.save_strategy(db_session, customer_id, {"expected_version": 0, "objectives": "recorded"}, "admin")
    with statements(db_session) as sql:
        result = service.get_strategy(db_session, customer_id, reference_date=date(2026, 10, 28), as_of=datetime(2026, 10, 28, tzinfo=UTC))
    assert result["plan"]["objectives"] == "recorded"
    assert len(sql) == 14


def test_populated_suggestions_and_budget(db_session, customer_id):
    from backend.models.customer_contact import CustomerContact
    from backend.models.customer_engagement import CustomerTask
    from backend.models.customer_technology import CustomerTechnology
    from backend.models.use_case import UseCase

    from tests.backend._shared import add_pipeline_batch
    customer = db_session.get(Customer, customer_id)
    batch = add_pipeline_batch(db_session, [(customer, [
        {"opportunity_number": "A", "current_contract_end_date": date(2026, 10, 27)},
        {"opportunity_number": "B", "current_contract_end_date": date(2026, 11, 2)},
        {"opportunity_number": "C", "current_contract_end_date": date(2026, 10, 30)},
        {"opportunity_number": "D", "current_contract_end_date": date(2026, 11, 10)},
    ])])
    db_session.add_all([CustomerTechnology(customer_id=customer_id, name=f"Tech {i}", category="software", support_state="no_support") for i in range(3)])
    db_session.add_all([UseCase(customer_id=customer_id, title=f"Case {i}") for i in range(4)])
    db_session.add_all([CustomerTask(customer_id=customer_id, title=f"Task {i}", status="open", created_by="admin") for i in range(6)])
    db_session.add(CustomerContact(customer_id=customer_id, display_name="Fixture contact"))
    db_session.commit()
    service.save_strategy(db_session, customer_id, {"expected_version": 0}, "admin")
    args = {"reference_date": date(2026, 10, 28), "as_of": datetime(2026, 10, 28, tzinfo=UTC)}
    with statements(db_session) as sql:
        result = service.get_strategy(db_session, customer_id, **args)["suggestions"]
    assert len(sql) == 18
    assert result == service.suggestions_for(db_session, customer_id, **args)
    assert result["objectives"] == [
        {"text": f"Advance the recorded partner-pipeline opportunities (4 line(s), 4 opportunity number(s)) — source: pipeline import #{batch.id} (synthetic-pipeline.csv)", "source": "partner pipeline"},
        {"text": "Work the 4 recorded renewal(s) due within 90 days or past their recorded end date — source: recorded renewal evidence", "source": "recorded renewal evidence"},
    ]
    # Risks cap 5 with the renewal leg capped at 3 (4 dated cards -> A, C, B in
    # bucket/days order) and the support leg capped at 2 (3 techs -> Tech 0, 1).
    assert [x["text"] for x in result["risks"]] == [
        "Renewal A (not recorded): recorded end date 2026-10-27, -1 days from reference — source: recorded renewal evidence",
        "Renewal C (not recorded): recorded end date 2026-10-30, 2 days from reference — source: recorded renewal evidence",
        "Renewal B (not recorded): recorded end date 2026-11-02, 5 days from reference — source: recorded renewal evidence",
        "Tech 0 (not recorded) recorded with support state no_support — source: technology inventory",
        "Tech 1 (not recorded) recorded with support state no_support — source: technology inventory",
    ]
    assert len(result["desired_outcomes"]) == 3
    # Plays cap 2: the task leg + the contact leg (the one recorded contact
    # drops the "No contacts recorded" gap, leaving 3 discovery gaps).
    assert result["plays"] == [
        {"text": "Follow through on the 6 open task(s) (next due: none recorded) — source: task records", "source": "task records"},
        {"text": "Work the 1 recorded contact(s) — source: contact records", "source": "contact records"},
    ]
    assert [x["text"] for x in result["discovery_gaps"]] == [
        "No economic buyer recorded", "No champion recorded",
        "No recorded activity or dated note — source: engagement basis"]
    assert len(result["next_actions"]) == 5


@pytest.mark.parametrize("foreign_keys", [False, True])
def test_customer_delete_strategy_integrity(tmp_path, foreign_keys):
    from backend.models.account_strategy import (
        AccountStrategy,
        AccountStrategySnapshot,
        strategy_contact_links,
        strategy_note_links,
        strategy_task_links,
    )
    from backend.models.customer_contact import CustomerContact
    from backend.models.customer_engagement import CustomerTask
    from backend.models.sales_note import SalesNote
    from backend.models.use_case import Base
    from backend.services.customers_service import delete_customer_with_use_cases
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import Session

    engine = create_engine(f"sqlite:///{tmp_path / 'integrity.db'}")
    if foreign_keys:
        @event.listens_for(engine, "connect")
        def enable_fk(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        customer = Customer(name="Delete strategy")
        db.add(customer)
        db.flush()
        task = CustomerTask(customer_id=customer.id, title="Task", status="open", created_by="admin")
        contact = CustomerContact(customer_id=customer.id, display_name="Contact")
        note = SalesNote(customer_id=customer.id, category="discovery", title="Note", content="text")
        db.add_all([task, contact, note])
        db.commit()
        plan = service.save_strategy(db, customer.id, {"expected_version": 0, "objectives": "test"}, "admin")
        service.set_links(db, plan["id"], {"task_ids": [task.id], "contact_ids": [contact.id], "note_ids": [note.id]}, "admin")
        service.publish_snapshot(db, customer.id, {}, "admin")
        counts = delete_customer_with_use_cases(db, customer)
        db.commit()
        for table in (strategy_task_links, strategy_contact_links, strategy_note_links, AccountStrategy.__table__, AccountStrategySnapshot.__table__):
            assert counts[table.name] == 1
            assert db.execute(select(table)).all() == []
    engine.dispose()


def test_restore_recreates_missing_draft(db_session, customer_id):
    from backend.models.account_strategy import AccountStrategy
    service.save_strategy(db_session, customer_id, {"expected_version": 0, "plays": "recorded"}, "admin")
    snap = service.publish_snapshot(db_session, customer_id, {}, "admin")
    db_session.query(AccountStrategy).filter_by(customer_id=customer_id).delete()
    db_session.commit()
    restored = service.restore_snapshot(db_session, customer_id, snap["id"], {"expected_version": 0}, "admin")
    assert restored["version"] == 1 and restored["plays"] == "recorded"
    assert all(restored[field] is None for field in service.FIELDS if field != "plays")
