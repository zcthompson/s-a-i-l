"""GET /api/customers/ batches use-case loading (no per-customer N+1).

The list route must return exactly what the detail route reports for each
customer (use_case_count / total_impact / departments), keep junction scoping
(no cross-customer leak), and issue a bounded number of queries.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest
from backend.models.use_case import Customer, CustomerUser, UseCase, User
from sqlalchemy import event

from tests.backend.common import _token

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    from unittest.mock import patch

    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {
            "username": user.username, "email": user.email,
            "display_name": user.display_name, "department": user.department,
            "is_admin": user.is_admin, "role": user.role, "user_id": user.id,
        }

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", lambda *a, **k: shared_engine):
        yield





def _user(db, username, is_admin=0):
    u = User(username=username, email=f"{username}@test.local",
             hashed_password=_FAKE_BCRYPT_HASH, display_name=username,
             department="IT", is_admin=is_admin, approved=1, is_active=1)
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def seeded(db_session):
    admin = _user(db_session, "batch_admin", is_admin=1)
    rep = _user(db_session, "batch_rep")
    names = ["BatchCo A", "BatchCo B", "BatchCo C", "BatchCo D"]
    customers = []
    for n in names:
        c = Customer(name=n, description=None, vertical=None)
        db_session.add(c)
        db_session.commit()
        customers.append(c)
    specs = {
        "BatchCo A": [("Eng", 100.0, 50.0), ("Ops", 200.0, None), ("Eng", None, 25.0)],
        "BatchCo B": [("Sales", 10.0, 10.0), ("Finance", 5.0, 0.0)],
        "BatchCo C": [("Ops", 1000.0, 2000.0), ("Ops", 1.0, 1.0), ("HR", None, None)],
        "BatchCo D": [],
    }
    for c in customers:
        for i, (dept, sav, rev) in enumerate(specs[c.name]):
            db_session.add(UseCase(
                title=f"{c.name} uc{i}", customer_id=c.id, department=dept,
                status="active", estimated_savings=sav, estimated_revenue=rev,
                created_by="seed",
            ))
    db_session.commit()
    # Rep is scoped to A and C only.
    for c in (customers[0], customers[2]):
        db_session.add(CustomerUser(customer_id=c.id, user_id=rep.id, role="member",
                                    granted_by=admin.id))
    db_session.commit()
    return {"admin": admin, "rep": rep, "customers": customers}


def _by_name(rows):
    return {r["name"]: r for r in rows}


def test_list_matches_detail_route(client, seeded):
    hdr = _token("batch_admin", True)
    r = client.get("/api/customers/", headers=hdr)
    assert r.status_code == 200
    listed = _by_name(r.json())
    for c in seeded["customers"]:
        assert c.name in listed
        detail = client.get(f"/api/customers/{c.name}/", headers=hdr).json()
        row = listed[c.name]
        assert row["use_case_count"] == detail["use_case_count"]
        assert row["total_impact"] == detail["total_impact"]
        assert row["departments"] == detail["departments"]
    assert listed["BatchCo A"]["use_case_count"] == 3
    assert listed["BatchCo A"]["total_impact"] == 375.0
    assert listed["BatchCo D"]["use_case_count"] == 0
    assert listed["BatchCo D"]["total_impact"] == 0.0


def test_scoping_no_leak_and_admin_sees_all(client, seeded):
    rep_rows = client.get("/api/customers/", headers=_token("batch_rep")).json()
    rep_names = {r["name"] for r in rep_rows}
    assert rep_names == {"BatchCo A", "BatchCo C"}
    admin_rows = client.get("/api/customers/", headers=_token("batch_admin", True)).json()
    assert {"BatchCo A", "BatchCo B", "BatchCo C", "BatchCo D"} <= {r["name"] for r in admin_rows}


def test_list_issues_bounded_use_case_queries(client, db_session, seeded):
    engine = db_session.get_bind()
    engine = getattr(engine, "engine", engine)
    stmts = []

    def _count(conn, cursor, statement, *a):
        if "FROM use_cases" in statement:
            stmts.append(statement)

    event.listen(engine, "before_cursor_execute", _count)
    try:
        r = client.get("/api/customers/", headers=_token("batch_admin", True))
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert r.status_code == 200
    # Batched: not one use_cases query per customer.
    assert len(r.json()) >= 4
    assert len(stmts) < len(r.json())
