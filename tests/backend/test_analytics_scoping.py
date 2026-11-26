"""Regression tests: auth + multi-tenant scoping of analytics endpoints.

2026-08-19 session: /api/analytics/* had no authentication, and department
trends / correlations ignored customer scope entirely, so a customer's
Analytics tab showed data blended from every customer.

Run: pytest tests/backend/test_analytics_scoping.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Point auth's user lookup at the shared test session.

    The real lookup opens a separate connection to the DB file, which cannot
    see users committed only inside the test transaction; without this patch
    get_user_from_request falls back to a minimal dict (no is_admin/user_id)
    and admin/junction checks misfire.
    """
    from backend.models.use_case import User

    from backend import auth as auth_mod

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "department": user.department,
            "is_admin": user.is_admin,
            "role": user.role,
            "user_id": user.id,
        }

    with patch.object(auth_mod, "_get_user_by_username", _lookup):
        yield


def _token(username: str) -> dict:
    from backend.auth import create_access_token
    token = create_access_token({"sub": username, "is_admin": False})
    return {"Authorization": f"Bearer {token}"}


def _seed(db_session):
    from backend.models.collaboration import ScoreHistory
    from backend.models.use_case import Customer, CustomerUser, UseCase, User

    admin = User(username="an_admin", email="aa@test.local",
                 hashed_password=_FAKE_HASH,
                 display_name="A", is_admin=1, approved=1, is_active=1)
    member = User(username="an_member", email="am@test.local",
                  hashed_password=_FAKE_HASH,
                  display_name="M", is_admin=0, approved=1, is_active=1)
    stranger = User(username="an_stranger", email="as@test.local",
                    hashed_password=_FAKE_HASH,
                    display_name="S", is_admin=0, approved=1, is_active=1)
    db_session.add_all([admin, member, stranger])
    db_session.commit()
    for u in (admin, member, stranger):
        db_session.refresh(u)

    cust_a = Customer(name="AnalyticsA", description="A")
    cust_b = Customer(name="AnalyticsB", description="B")
    db_session.add_all([cust_a, cust_b])
    db_session.commit()
    db_session.refresh(cust_a)
    db_session.refresh(cust_b)

    db_session.add(CustomerUser(customer_id=cust_a.id, user_id=member.id, role="member"))
    db_session.commit()

    uc_a1 = UseCase(title="A EngA 1", customer_id=cust_a.id, department="EngA",
                    status="active", overall_score=70.0,
                    estimated_savings=100000, estimated_revenue=50000, created_by="seed")
    uc_a2 = UseCase(title="A EngA 2", customer_id=cust_a.id, department="EngA",
                    status="active", overall_score=80.0,
                    estimated_savings=200000, estimated_revenue=0, created_by="seed")
    uc_a3 = UseCase(title="A OpsA", customer_id=cust_a.id, department="OpsA",
                    status="active", overall_score=50.0,
                    estimated_savings=0, estimated_revenue=10000, created_by="seed")
    uc_b1 = UseCase(title="B OpsB", customer_id=cust_b.id, department="OpsB",
                    status="active", overall_score=90.0,
                    estimated_savings=500000, estimated_revenue=0, created_by="seed")
    db_session.add_all([uc_a1, uc_a2, uc_a3, uc_b1])
    db_session.commit()
    for uc in (uc_a1, uc_a2, uc_a3, uc_b1):
        db_session.refresh(uc)

    # Two history points so the prediction endpoint can return 200
    now = datetime.now(UTC)
    for i, score in enumerate([65.0, 70.0]):
        db_session.add(ScoreHistory(use_case_id=uc_a1.id, score=score,
                                    scored_at=now - timedelta(days=7 - i)))
    db_session.commit()

    return {"cust_a": cust_a.id, "cust_b": cust_b.id, "uc_a1": uc_a1.id, "uc_b1": uc_b1.id}


def test_department_trends_requires_auth(client):
    r = client.get("/api/analytics/department-trends/")
    assert r.status_code == 401


def test_department_trends_customer_scoped(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/analytics/department-trends/?customer_id={ids['cust_a']}",
                   headers=_token("an_admin"))
    assert r.status_code == 200
    depts = r.json()
    assert {t["department"] for t in depts} == {"EngA", "OpsA"}
    eng = next(t for t in depts if t["department"] == "EngA")
    assert eng["use_case_count"] == 2


def test_department_trends_member_rejected_for_foreign_customer(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/analytics/department-trends/?customer_id={ids['cust_b']}",
                   headers=_token("an_member"))
    # 404-first (R4/Q7): a foreign explicit scope is the same 404 as missing.
    assert r.status_code == 404


def test_department_trends_unscoped_member_limited_to_accessible(client, db_session):
    ids = _seed(db_session)
    r = client.get("/api/analytics/department-trends/", headers=_token("an_member"))
    assert r.status_code == 200
    assert {t["department"] for t in r.json()} == {"EngA", "OpsA"}


def test_correlations_requires_auth(client):
    r = client.get("/api/analytics/correlations/")
    assert r.status_code == 401


def test_correlations_customer_scoped(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/analytics/correlations/?customer_id={ids['cust_a']}",
                   headers=_token("an_admin"))
    assert r.status_code == 200
    assert r.json()["sample_size"] == 3


def test_correlations_member_foreign_customer_rejected(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/analytics/correlations/?customer_id={ids['cust_b']}",
                   headers=_token("an_member"))
    # 404-first (R4/Q7): a foreign explicit scope is the same 404 as missing.
    assert r.status_code == 404


def test_predictive_requires_auth(client):
    r = client.get("/api/analytics/predictive/1/")
    assert r.status_code == 401


def test_predictive_cross_customer_rejected(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/analytics/predictive/{ids['uc_b1']}/", headers=_token("an_member"))
    # 404-first (R4/Q7): an out-of-scope use case is the same 404 as a missing one.
    assert r.status_code == 404
    assert r.json()["detail"] == "Use case not found"


def test_predictive_scoped_use_case_ok(client, db_session):
    ids = _seed(db_session)
    r = client.get(f"/api/analytics/predictive/{ids['uc_a1']}/", headers=_token("an_member"))
    assert r.status_code == 200
    assert r.json()["data_points"] == 2
