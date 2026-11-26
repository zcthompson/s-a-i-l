"""Regression tests: /api/departments must return computed use_case_count.

2026-08-19 session: the route returned raw Department ORM rows, so
DepartmentResponse.use_case_count always fell back to its default of 0.
Counts must reflect each department's real use-case totals.

Run: pytest tests/backend/test_departments_count.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _token(username: str) -> dict:
    from backend.auth import create_access_token
    token = create_access_token({"sub": username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def _seed(db_session):
    from backend.models.use_case import Customer, Department, UseCase

    cust = Customer(name="CountCo", description="C")
    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)

    eng = Department(name="Eng", customer_id=cust.id)
    ops = Department(name="Ops", customer_id=cust.id)
    db_session.add_all([eng, ops])
    db_session.commit()
    db_session.refresh(eng)
    db_session.refresh(ops)

    uc1 = UseCase(title="U1", customer_id=cust.id, department="Eng",
                  department_id=eng.id, status="active", created_by="seed")
    uc2 = UseCase(title="U2", customer_id=cust.id, department="Eng",
                  department_id=eng.id, status="active", created_by="seed")
    uc3 = UseCase(title="U3", customer_id=cust.id, department="Ops",
                  department_id=ops.id, status="active", created_by="seed")
    db_session.add_all([uc1, uc2, uc3])
    db_session.commit()

    return {"cust": cust.id, "eng": eng.id}


def test_department_list_returns_computed_counts(client, db_session):
    _seed(db_session)
    r = client.get("/api/departments/?customer_name=CountCo", headers=_token("admin"))
    assert r.status_code == 200
    by_name = {d["name"]: d["use_case_count"] for d in r.json()}
    assert by_name == {"Eng": 2, "Ops": 1}
    # Counts must match the customer's per-department use-case totals
    assert sum(by_name.values()) == 3


def test_department_detail_returns_computed_count(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/departments/{ids['eng']}/", headers=_token("admin"))
    assert r.status_code == 200
    assert r.json()["name"] == "Eng"
    assert r.json()["use_case_count"] == 2


def _mk_user(db, username, **kw):
    from backend.auth import hash_password
    from backend.models.use_case import User

    u = User(
        username=username, email=f"{username}@test.local",
        hashed_password=hash_password(username), display_name=username,
        department="Sales", is_admin=kw.pop("is_admin", 0),
        approved=kw.pop("approved", 1), is_active=kw.pop("is_active", 1),
        sales_role=kw.pop("sales_role", None), role=kw.pop("role", None),
    )
    db.add(u)
    db.flush()
    return u


def _grant(db, customer, user, role):
    from backend.models.use_case import CustomerUser

    db.add(CustomerUser(customer_id=customer.id, user_id=user.id, role=role, granted_by=user.id))


def test_unscoped_department_list_is_scoped_to_callable_customers(client, db_session):
    """the unscoped /api/departments/ list must be limited to the
    caller's readable customers — never the whole portfolio."""
    from backend.models.use_case import Customer, Department

    a = Customer(name="ScopeA", description="A")
    b = Customer(name="ScopeB", description="B")
    db_session.add_all([a, b])
    db_session.commit()
    db_session.refresh(a)
    db_session.refresh(b)
    db_session.add_all([Department(name="DA", customer_id=a.id),
                        Department(name="DB", customer_id=b.id)])
    rep = _mk_user(db_session, "scope_rep", sales_role="rep")
    _grant(db_session, a, rep, "owner")
    _mk_user(db_session, "scope_auditor", sales_role="auditor")
    _mk_user(db_session, "scope_none")
    db_session.commit()

    # a rep sees only their own customer's departments
    r = client.get("/api/departments/", headers=_token("scope_rep"))
    assert r.status_code == 200
    assert {d["customer_id"] for d in r.json()} == {a.id}
    assert [d["name"] for d in r.json()] == ["DA"]

    # an auditor (global read) sees every department
    r = client.get("/api/departments/", headers=_token("scope_auditor"))
    assert r.status_code == 200
    assert {d["customer_id"] for d in r.json()} == {a.id, b.id}

    # a user with no grants sees nothing (fail-closed — never all)
    r = client.get("/api/departments/", headers=_token("scope_none"))
    assert r.status_code == 200
    assert r.json() == []

    # a system admin sees the whole portfolio
    r = client.get("/api/departments/", headers=_token("admin"))
    assert r.status_code == 200
    assert {d["customer_id"] for d in r.json()} == {a.id, b.id}


def test_department_by_id_is_404_first(client, db_session):
    """(Wave B): out-of-scope by-id department access returns the same 404
    as a missing one (oracle-closing); in-scope capability denials keep 403."""
    from backend.models.use_case import Customer, Department

    cust = Customer(name="OracleCo", description="O")
    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)
    dept = Department(name="OD", customer_id=cust.id)
    owner = _mk_user(db_session, "oracle_owner", sales_role="rep")
    _grant(db_session, cust, owner, "owner")
    member = _mk_user(db_session, "oracle_member", sales_role="rep")
    _grant(db_session, cust, member, "member")
    _mk_user(db_session, "oracle_outsider", sales_role="rep")  # no grant on OracleCo
    db_session.add(dept)
    db_session.commit()

    base = f"/api/departments/{dept.id}/"

    # out-of-scope caller: 404 (same as missing) — not 403
    for method, kwargs in (("get", {}), ("put", dict(json={"name": "X"})), ("delete", {})):
        r = getattr(client, method)(base, headers=_token("oracle_outsider"), **kwargs)
        assert r.status_code == 404, f"{method}: {r.status_code} {r.text[:120]}"
    assert client.get(f"{base}use-cases/", headers=_token("oracle_outsider")).status_code == 404

    # in-scope member: capability denial (no manage-team) -> 403
    assert client.put(base, headers=_token("oracle_member"), json={"name": "X"}).status_code == 403

    # in-scope owner: allowed -> 200
    r = client.put(base, headers=_token("oracle_owner"), json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed"
