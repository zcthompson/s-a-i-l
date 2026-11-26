"""Synthetic acceptance pins for bounded, account-scoped search."""
from contextlib import contextmanager
from datetime import date, datetime

import pytest
from backend.auth import create_access_token
from backend.models.account_strategy import AccountStrategy, AccountStrategySnapshot
from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, User
from backend.services.account_search import MODULES, search_account
from fastapi import HTTPException
from sqlalchemy import event

ADMIN = {"is_admin": 1, "username": "admin"}


@contextmanager
def statements(db):
    sql = []

    def record(conn, cursor, statement, parameters, context, executemany):
        sql.append(statement)

    event.listen(db.bind, "before_cursor_execute", record)
    try:
        yield sql
    finally:
        event.remove(db.bind, "before_cursor_execute", record)


@pytest.fixture()
def accounts(db_session):
    rows = [Customer(name="Synthetic search A"), Customer(name="Synthetic search B")]
    db_session.add_all(rows)
    db_session.commit()
    return tuple(row.id for row in rows)


def headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def path(cid):
    return f"/api/customers/{cid}/search/"


def note(cid, **kwargs):
    return SalesNote(customer_id=cid, category="discovery", **{
        "title": "Synthetic needle", "content": "Synthetic evidence", **kwargs})


def populate(db, cid):
    instant = datetime(2026, 11, 1)
    rows = [
        note(cid, note_date=date(2026, 11, 1)),
        CustomerContact(customer_id=cid, display_name="needle contact", created_at=instant),
        CustomerActivity(customer_id=cid, type="qbr", outcome="needle activity", actor="admin",
                         created_by="admin", occurred_date=date(2026, 11, 1)),
        CustomerTask(customer_id=cid, title="needle task", created_by="admin", updated_at=instant),
        CustomerTechnology(customer_id=cid, name="needle technology", category="software",
                           date_observed=date(2026, 11, 1)),
        AccountStrategy(customer_id=cid, objectives="needle objective", updated_at=instant),
        CustomerKnowledge(customer_id=cid, file_name="needle.txt", file_data=b"synthetic",
                          knowledge_type="document", uploaded_at=instant),
    ]
    db.add_all(rows)
    db.commit()
    return rows


@pytest.mark.parametrize("missing", [False, True])
def test_404_first(client, db_session, accounts, missing):
    outsider = User(username="outsider", email="outsider@test.local", hashed_password="unused",
                    is_admin=0, approved=1, is_active=1, sales_role="rep")
    db_session.add(outsider)
    db_session.commit()
    with statements(db_session) as sql:
        response = client.get(path(999999 if missing else accounts[0]), headers=headers("outsider"),
                              params={"q": "x", "include_archived": "maybe"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Customer not found"}
    assert len(sql) <= 3
    assert not any(model.__tablename__ in statement for _, model, *_ in MODULES for statement in sql)


@pytest.mark.parametrize("missing, status", [(True, 404), (False, 403)])
def test_direct_caller_gate(db_session, accounts, missing, status):
    user = {"is_admin": 0, "id": 999999, "username": "synthetic outsider", "sales_role": "rep"}
    with statements(db_session) as sql, pytest.raises(HTTPException) as exc:
        search_account(db_session, user, 999999 if missing else accounts[0], "needle", False)
    assert exc.value.status_code == status
    assert len(sql) <= 3
    assert not any(model.__tablename__ in statement for _, model, *_ in MODULES for statement in sql)


@pytest.mark.parametrize("params, detail", [
    ({}, "Search query must be 2-100 characters"),
    ({"q": " "}, "Search query must be 2-100 characters"),
    ({"q": "x"}, "Search query must be 2-100 characters"),
    ({"q": "x" * 101}, "Search query must be 2-100 characters"),
    ({"q": "needle", "include_archived": "maybe"}, "include_archived must be true or false"),
])
def test_validation(client, db_session, accounts, params, detail):
    with statements(db_session) as sql:
        response = client.get(path(accounts[0]), headers=headers(), params=params)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert not any(model.__tablename__ in statement for _, model, *_ in MODULES for statement in sql)


@pytest.mark.parametrize("literal", ["%_", "%%", "__", "\\\\", "!!"])
def test_literal_like(client, db_session, accounts, literal):
    row = note(accounts[0], title=f"Synthetic literal {literal}")
    db_session.add_all([row, note(accounts[0], title="Synthetic ordinary")])
    db_session.commit()
    response = client.get(path(accounts[0]), headers=headers(), params={"q": literal})
    assert [item["id"] for item in response.json()["results"]] == [row.id]
    # A single wildcard is rejected by HTTP validation; direct callers still match literally.
    if "%" in literal or "_" in literal:
        assert len(search_account(db_session, ADMIN, accounts[0], literal[0], False)["results"]) == 1
        assert client.get(path(accounts[0]), headers=headers(), params={"q": literal[0]}).status_code == 422


def test_cap_and_truncated(db_session, accounts):
    rows = [note(accounts[0]) for _ in range(12)]
    db_session.add_all(rows)
    db_session.commit()
    result = search_account(db_session, ADMIN, accounts[0], " needle ", False)
    assert result["query"] == "needle"
    assert result["counts"]["note"] == 10
    assert result["truncated"] is True
    assert [item["id"] for item in result["results"]] == sorted([row.id for row in rows], reverse=True)[:10]


def test_archives(client, db_session, accounts):
    db_session.add(CustomerContact(customer_id=accounts[0], display_name="needle archived", archived=True))
    db_session.commit()
    assert client.get(path(accounts[0]), headers=headers(), params={"q": "needle"}).json()["counts"]["contact"] == 0
    result = client.get(path(accounts[0]), headers=headers(), params={"q": "needle", "include_archived": "true"}).json()
    assert result["counts"]["contact"] == 1
    assert result["results"][0]["title"] == "needle archived (archived)"


def test_merge_order_and_budget(client, db_session, accounts):
    rows = populate(db_session, accounts[0])
    recent = note(accounts[0], note_date=date(2026, 11, 2))
    null_activity = CustomerActivity(customer_id=accounts[0], type="call", outcome="needle undated",
                                     actor="admin", created_by="admin")
    null_technology = CustomerTechnology(customer_id=accounts[0], name="needle undated", category="software")
    second_note = note(accounts[0], note_date=date(2026, 11, 1))
    db_session.add_all([recent, null_activity, null_technology, second_note])
    db_session.commit()
    expected = [("note", recent.id), ("note", second_note.id)] + [
        (module, row.id) for (module, *_), row in zip(MODULES, rows)
    ] + [("activity", null_activity.id), ("technology", null_technology.id)]
    with statements(db_session) as sql:
        response = client.get(path(accounts[0]), headers=headers(), params={"q": "needle"})
    assert response.status_code == 200
    assert len(sql) <= 12
    for _, model, *_ in MODULES:
        assert sum(f"FROM {model.__tablename__}" in statement for statement in sql) == 1
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in sql)
    result = response.json()
    assert [(item["module"], item["id"]) for item in result["results"]] == expected
    assert result["truncated"] is False
    items = {item["module"]: item for item in result["results"] if item["timestamp"]}
    assert items["note"]["date_only"] and items["activity"]["date_only"] and items["technology"]["date_only"]
    assert not items["contact"]["date_only"] and not items["task"]["date_only"]
    assert items["activity"]["title"] == "QBR"
    assert items["strategy"]["title"] == "Account strategy — Objectives"
    assert result["counts"] == dict(note=3, contact=1, activity=2, task=1, technology=2, strategy=1, knowledge=1, deal=0, use_case=0)


def test_snippet_window_and_first_column(db_session, accounts):
    content = "a" * 200 + "needle" + "b" * 200
    db_session.add(note(accounts[0], title="Synthetic", content=content))
    db_session.commit()
    result = search_account(db_session, ADMIN, accounts[0], "needle", False)
    assert result["results"][0]["snippet"] == content[123:283]
    db_session.add(note(accounts[0], title="needle first", content="needle later"))
    db_session.commit()
    assert search_account(db_session, ADMIN, accounts[0], "needle", False)["results"][0]["snippet"] == "needle first"


@pytest.mark.parametrize("field, label", [("objectives", "Objectives"), ("desired_outcomes", "Desired outcomes"),
    ("risks", "Risks"), ("plays", "Plays"), ("discovery_gaps", "Discovery gaps")])
def test_strategy_draft_only(db_session, accounts, field, label):
    assert search_account(db_session, ADMIN, accounts[0], "needle", False)["counts"]["strategy"] == 0
    plan = AccountStrategy(customer_id=accounts[0])
    db_session.add_all([plan, AccountStrategySnapshot(customer_id=accounts[0], plan_number=1,
                                                    content={field: "needle snapshot"})])
    db_session.commit()
    assert search_account(db_session, ADMIN, accounts[0], "needle", False)["counts"]["strategy"] == 0
    setattr(plan, field, "needle draft")
    db_session.commit()
    item = search_account(db_session, ADMIN, accounts[0], "needle", False)["results"][0]
    assert item["title"] == f"Account strategy — {label}"
    assert item["snippet"] == "needle draft"


def test_isolation(db_session, accounts):
    own = populate(db_session, accounts[0])
    populate(db_session, accounts[1])
    result = search_account(db_session, ADMIN, accounts[0], "needle", False)
    assert [(item["module"], item["id"]) for item in result["results"]] == [
        (module, row.id) for (module, *_), row in zip(MODULES, own)]


def test_deals_and_use_cases_are_searchable_and_scoped(db_session, accounts):
    from backend.models.deal import Deal, PipelineStage
    from backend.models.use_case import UseCase

    stage = PipelineStage(key="search-test-stage", label="Search test", stage_class="open", position=99)
    db_session.add(stage)
    db_session.flush()
    for cid in accounts:
        db_session.add(Deal(customer_id=cid, name="needle deal", stage_id=stage.id, created_by="admin"))
        db_session.add(UseCase(customer_id=cid, title="needle use case", description="Discovery", status="draft"))
    db_session.commit()
    result = search_account(db_session, ADMIN, accounts[0], "needle", False)
    assert result["counts"]["deal"] == 1
    assert result["counts"]["use_case"] == 1
    assert {item["module"] for item in result["results"]} == {"deal", "use_case"}
