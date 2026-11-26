"""Regression tests: caller authorization on aggregate stats, score trends,
and use-case list scoping.

2026-09-19 review: ``/api/stats/aggregate/`` and ``/api/stats/trends/``
authenticated the request but discarded the caller, and
``StatsService.get_aggregate_stats`` computed ``average_score`` globally even
when a customer scope was supplied. Any non-admin caller therefore received
cross-customer totals, averages, impact, top records, and trends. Separately,
an explicit ``customer_id=0`` on the use-case list widened to the global setand unbounded/negative pagination was accepted.

``/api/use-cases/stats/`` (UseCaseService.get_stats) had the same customer
isolation gap and is covered here (sibling defect).

Run: pytest tests/backend/test_stats_scoping.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Point auth's user lookup at the shared test session (same pattern as
    test_analytics_scoping.py). Without this, get_user_from_request falls back
    to a minimal dict with no is_admin/user_id and the scoping misfires."""
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


@pytest.fixture()
def scope_env(db_session):
    """Seed two customers with distinct scores, an admin, a member assigned
    only to A, and an unassigned stranger."""
    from backend.models.use_case import Customer, CustomerUser, UseCase, User

    admin = User(
        username="stats_admin", email="sa@test.local",
        hashed_password=_FAKE_HASH,
        display_name="SA", is_admin=1, approved=1, is_active=1,
    )
    member = User(
        username="stats_member", email="sm@test.local",
        hashed_password=_FAKE_HASH,
        display_name="SM", is_admin=0, approved=1, is_active=1,
    )
    stranger = User(
        username="stats_stranger", email="ss@test.local",
        hashed_password=_FAKE_HASH,
        display_name="SS", is_admin=0, approved=1, is_active=1,
    )
    db_session.add_all([admin, member, stranger])
    db_session.commit()
    for u in (admin, member, stranger):
        db_session.refresh(u)

    cust_a = Customer(name="StatsScopeA", description="A")
    cust_b = Customer(name="StatsScopeB", description="B")
    db_session.add_all([cust_a, cust_b])
    db_session.commit()
    db_session.refresh(cust_a)
    db_session.refresh(cust_b)

    db_session.add(
        CustomerUser(customer_id=cust_a.id, user_id=member.id, role="member")
    )
    db_session.commit()

    scored_at = datetime.now(UTC) - timedelta(days=1)
    # Customer A: scores 70 / 80 (avg 75), dept EngA.
    uc_a1 = UseCase(title="SS A EngA 1", customer_id=cust_a.id, department="EngA",
                    status="active", overall_score=70.0, scored_at=scored_at,
                    estimated_savings=100_000, estimated_revenue=50_000,
                    created_by="seed")
    uc_a2 = UseCase(title="SS A EngA 2", customer_id=cust_a.id, department="EngA",
                    status="active", overall_score=80.0, scored_at=scored_at,
                    estimated_savings=200_000, estimated_revenue=0,
                    created_by="seed")
    # Customer B: score 30 (avg 30), different department.
    uc_b1 = UseCase(title="SS B Ops 1", customer_id=cust_b.id, department="Ops",
                    status="active", overall_score=30.0, scored_at=scored_at,
                    estimated_savings=1_000, estimated_revenue=0, created_by="seed")
    db_session.add_all([uc_a1, uc_a2, uc_b1])
    db_session.commit()
    db_session.refresh(uc_a1)
    db_session.refresh(uc_a2)
    db_session.refresh(uc_b1)

    return {
        "admin": _token("stats_admin"),
        "member": _token("stats_member"),
        "stranger": _token("stats_stranger"),
        "cust_a": cust_a,
        "cust_b": cust_b,
        "uc_a_ids": {uc_a1.id, uc_a2.id},
    }


# ───────────────────────────── stats/aggregate ─────────────────────────

class TestAggregateStatsScoping:
    def test_admin_sees_global(self, client, scope_env):
        r = client.get("/api/stats/aggregate/", headers=scope_env["admin"])
        assert r.status_code == 200
        data = r.json()
        # 3 seeded rows (A×2 + B×1) — no other use cases exist in this DB.
        assert data["total_use_cases"] == 3
        assert data["scored_use_cases"] == 3
        # (70 + 80 + 30) / 3 = 60.0
        assert data["average_score"] == 60.0

    def test_member_sees_only_assigned_customer(self, client, scope_env):
        r = client.get("/api/stats/aggregate/", headers=scope_env["member"])
        assert r.status_code == 200
        data = r.json()
        # Member is assigned to A only: totals must reflect A, never B.
        assert data["total_use_cases"] == 2
        assert data["scored_use_cases"] == 2
        assert data["average_score"] == 75.0
        # top_use_cases must not leak a B record.
        for uc in data["top_use_cases"]:
            assert uc["id"] in scope_env["uc_a_ids"]
        # Departments: A rows are EngA only.
        assert set(data["by_department"].keys()) == {"EngA"}
        # Impact: A = 100k + 50k savings, 50k revenue.
        impact = data["impact_summary"]
        assert impact["total_savings"] == 300_000.0
        assert impact["total_revenue"] == 50_000.0

    def test_stranger_with_no_assignment_sees_nothing(self, client, scope_env):
        r = client.get("/api/stats/aggregate/", headers=scope_env["stranger"])
        assert r.status_code == 200
        data = r.json()
        assert data["total_use_cases"] == 0
        assert data["scored_use_cases"] == 0
        assert data["average_score"] == 0.0
        assert data["top_use_cases"] == []
        assert data["by_department"] == {}
        assert data["by_status"] == {}

    def test_member_explicit_own_customer(self, client, scope_env):
        cid = scope_env["cust_a"].id
        r = client.get(f"/api/stats/aggregate/?customer_id={cid}",
                       headers=scope_env["member"])
        assert r.status_code == 200
        assert r.json()["total_use_cases"] == 2
        assert r.json()["average_score"] == 75.0

    def test_member_explicit_foreign_customer_rejected(self, client, scope_env):
        cid = scope_env["cust_b"].id
        r = client.get(f"/api/stats/aggregate/?customer_id={cid}",
                       headers=scope_env["member"])
        # A foreign explicit scope is the same 404 as a missing customer
        # never widened and never answered with A's (or global) data.
        assert r.status_code == 404

    def test_admin_explicit_customer(self, client, scope_env):
        cid = scope_env["cust_b"].id
        r = client.get(f"/api/stats/aggregate/?customer_id={cid}",
                       headers=scope_env["admin"])
        assert r.status_code == 200
        data = r.json()
        assert data["total_use_cases"] == 1
        assert data["average_score"] == 30.0

    def test_zero_customer_id_rejected(self, client, scope_env):
        r = client.get("/api/stats/aggregate/?customer_id=0",
                       headers=scope_env["admin"])
        assert r.status_code == 422

    def test_anonymous_401(self, client, scope_env):
        r = client.get("/api/stats/aggregate/")
        assert r.status_code == 401


# ───────────────────────────── stats/trends ────────────────────────────

class TestScoreTrendsScoping:
    def test_member_trends_only_assigned(self, client, scope_env):
        r = client.get("/api/stats/trends/", headers=scope_env["member"])
        assert r.status_code == 200
        trends = r.json()
        total_count = sum(b["count"] for b in trends)
        # Only A's two scored use cases are visible to the member.
        assert total_count == 2
        # Averages across the member's trend buckets stay in A's score range.
        for b in trends:
            assert 70.0 <= b["avg_score"] <= 80.0

    def test_admin_trends_global(self, client, scope_env):
        r = client.get("/api/stats/trends/", headers=scope_env["admin"])
        assert r.status_code == 200
        trends = r.json()
        assert sum(b["count"] for b in trends) == 3

    def test_stranger_trends_empty(self, client, scope_env):
        r = client.get("/api/stats/trends/", headers=scope_env["stranger"])
        assert r.status_code == 200
        assert r.json() == []

    def test_member_trends_foreign_customer_rejected(self, client, scope_env):
        cid = scope_env["cust_b"].id
        r = client.get(f"/api/stats/trends/?customer_id={cid}",
                       headers=scope_env["member"])
        # 404-first: a foreign explicit scope is the same 404 as missing.
        assert r.status_code == 404


# ───────────── sibling: /api/use-cases/stats/ customer isolation ────────

class TestUseCaseStatsIsolation:
    def test_member_use_case_stats_scoped(self, client, scope_env):
        r = client.get("/api/use-cases/stats/", headers=scope_env["member"])
        assert r.status_code == 200
        data = r.json()
        assert data["total_use_cases"] == 2
        assert data["scored_use_cases"] == 2
        assert data["average_score"] == 75.0
        assert data["by_department"] == {"EngA": 2}

    def test_admin_use_case_stats_global(self, client, scope_env):
        r = client.get("/api/use-cases/stats/", headers=scope_env["admin"])
        assert r.status_code == 200
        data = r.json()
        assert data["total_use_cases"] == 3
        assert data["average_score"] == 60.0


# ─────────────────────────────── zero ID ───────────────────────────────

class TestZeroCustomerId:
    def test_list_zero_id_rejected(self, client, scope_env):
        r = client.get("/api/use-cases/?customer_id=0", headers=scope_env["admin"])
        assert r.status_code == 422

    def test_list_negative_id_rejected(self, client, scope_env):
        r = client.get("/api/use-cases/?customer_id=-5", headers=scope_env["admin"])
        assert r.status_code == 422

    def test_list_omitted_id_admin_global(self, client, scope_env):
        r = client.get("/api/use-cases/", headers=scope_env["admin"])
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_service_zero_id_never_widens(self, db_session, scope_env):
        """Direct-service regression: customer_id=0 with no user must select
        nothing (the old ``elif customer_id:`` branch returned the global set)."""
        from backend.services.use_case_service import UseCaseService

        rows = UseCaseService.get_all(db_session, customer_id=0, user=None)
        assert rows == []


# ─────────────────────────────── pagination ───────────────────────────

# ─────────────────────────────── missing customer ─────────────────────

class TestMissingCustomerErrors:
    """A missing customer is a 404, not a 200 error-dict / zero-shaped body.

    The access gate runs before the existence check, so an unauthorized
    (unassigned) caller gets 403, not a 404 existence disclosure.
    """

    def test_per_name_stats_missing_404(self, client, scope_env):
        r = client.get("/api/customers/NoSuchCustomerXyz/stats/",
                       headers=scope_env["admin"])
        assert r.status_code == 404

    def test_per_name_stats_admin_real_200(self, client, scope_env):
        r = client.get(f"/api/customers/{scope_env['cust_a'].name}/stats/",
                       headers=scope_env["admin"])
        assert r.status_code == 200
        data = r.json()
        assert data["customer_name"] == scope_env["cust_a"].name
        assert data["total_use_cases"] == 2

    def test_per_name_stats_member_own_200(self, client, scope_env):
        r = client.get(f"/api/customers/{scope_env['cust_a'].name}/stats/",
                       headers=scope_env["member"])
        assert r.status_code == 200
        assert r.json()["total_use_cases"] == 2

    def test_per_name_stats_member_foreign_404(self, client, scope_env):
        # Member has no junction row for B → the same 404 as a missing
        # customer (404-first; was a 200 error-dict, then 403).
        r = client.get(f"/api/customers/{scope_env['cust_b'].name}/stats/",
                       headers=scope_env["member"])
        assert r.status_code == 404
        assert r.json()["detail"] == "Customer not found"

    def test_per_name_stats_anonymous_401(self, client, scope_env):
        r = client.get(f"/api/customers/{scope_env['cust_a'].name}/stats/")
        assert r.status_code == 401

    def test_sales_readiness_missing_404(self, client, scope_env):
        r = client.get("/api/sales/customers/999999/readiness",
                       headers=scope_env["admin"])
        # Was: 200 with a zero-count readiness-shaped body.
        assert r.status_code == 404

    def test_sales_readiness_real_200(self, client, scope_env):
        r = client.get(
            f"/api/sales/customers/{scope_env['cust_b'].id}/readiness",
            headers=scope_env["admin"],
        )
        assert r.status_code == 200
        org = r.json()["organizational_readiness"]
        assert org["total_use_cases"] == 1

    def test_sales_usecases_missing_404(self, client, scope_env):
        r = client.get("/api/sales/customers/999999/usecases",
                       headers=scope_env["admin"])
        assert r.status_code == 404

    def test_sales_knowledge_missing_404(self, client, scope_env):
        r = client.get("/api/sales/customers/999999/knowledge",
                       headers=scope_env["admin"])
        assert r.status_code == 404

    def test_sales_readiness_unassigned_member_403(self, client, scope_env):
        # Stranger has no junction row → access gate (403) fires before
        # existence (404), for both a real and a missing customer.
        r = client.get(
            f"/api/sales/customers/{scope_env['cust_a'].id}/readiness",
            headers=scope_env["stranger"],
        )
        assert r.status_code == 403
        r2 = client.get("/api/sales/customers/999999/readiness",
                        headers=scope_env["stranger"])
        assert r2.status_code == 403

    def test_sales_readiness_anonymous_401(self, client, scope_env):
        r = client.get(f"/api/sales/customers/{scope_env['cust_a'].id}/readiness")
        assert r.status_code == 401


def _param_bounds(schema: dict):
    """Extract minimum/maximum from a query-param schema, unwrapping the
    ``anyOf``/``allOf``/``oneOf`` composite FastAPI emits for Optional
    (nullable) parameters."""
    if "minimum" in schema or "maximum" in schema:
        return schema.get("minimum"), schema.get("maximum")
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in schema.get(key, []):
            if isinstance(sub, dict) and ("minimum" in sub or "maximum" in sub):
                return sub.get("minimum"), sub.get("maximum")
    return None, None


class TestPaginationBounds:
    def test_negative_limit_rejected(self, client, scope_env):
        r = client.get("/api/use-cases/?limit=-1", headers=scope_env["admin"])
        assert r.status_code == 422

    def test_zero_limit_rejected(self, client, scope_env):
        r = client.get("/api/use-cases/?limit=0", headers=scope_env["admin"])
        assert r.status_code == 422

    def test_huge_limit_rejected(self, client, scope_env):
        r = client.get("/api/use-cases/?limit=1000000", headers=scope_env["admin"])
        assert r.status_code == 422

    def test_negative_skip_rejected(self, client, scope_env):
        r = client.get("/api/use-cases/?skip=-1", headers=scope_env["admin"])
        assert r.status_code == 422

    def test_valid_paging(self, client, scope_env):
        r = client.get("/api/use-cases/?skip=0&limit=2", headers=scope_env["admin"])
        assert r.status_code == 200
        assert len(r.json()) == 2
        r2 = client.get("/api/use-cases/?skip=2&limit=2", headers=scope_env["admin"])
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        # Pages must not overlap.
        page1 = {uc["id"] for uc in r.json()}
        page2 = {uc["id"] for uc in r2.json()}
        assert page1.isdisjoint(page2)

    def test_openapi_documents_bounds(self, client, scope_env):
        spec = client.get("/openapi.json").json()
        uc = spec["paths"]["/api/use-cases/"]["get"]["parameters"]
        by_name = {p["name"]: p["schema"] for p in uc}
        assert _param_bounds(by_name["limit"]) == (1, 1000)
        assert _param_bounds(by_name["skip"]) == (0, None)
        assert _param_bounds(by_name["customer_id"])[0] == 1
