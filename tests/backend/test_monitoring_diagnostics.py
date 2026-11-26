"""Regression tests: monitoring diagnostics (BE-05/BE-06) and sales readiness
over the complete dataset (BE-07) — fe_enhancements backlog, part 48.

2026-09-19 review: ``/api/monitoring/health/detailed`` hardwired
``database: {status: healthy, connected: true}``, ``get_ai_endpoint_health``
read only the environment variable (ignoring DB overrides + the enabled
flag), and ``/health/detailed``, ``/status``, and ``/metrics`` all answered
anonymously with host/process/traffic detail. Separately, sales readiness
computed total/scored/average from a ``limit=1000`` row fetch and presented
them as customer-wide metrics.

Run: pytest tests/backend/test_monitoring_diagnostics.py -v
"""

import os
from unittest.mock import patch

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
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
def mon_env(db_session):
    from backend.models.use_case import Customer, CustomerUser, User

    admin = User(
        username="mon_admin", email="ma@test.local",
        hashed_password=_FAKE_HASH,
        display_name="MA", is_admin=1, approved=1, is_active=1,
    )
    member = User(
        username="mon_member", email="mm@test.local",
        hashed_password=_FAKE_HASH,
        display_name="MM", is_admin=0, approved=1, is_active=1,
    )
    db_session.add_all([admin, member])
    db_session.commit()
    for u in (admin, member):
        db_session.refresh(u)

    cust = Customer(name="MonCustomer", description="M")
    db_session.add(cust)
    db_session.commit()
    db_session.refresh(cust)
    db_session.add(CustomerUser(customer_id=cust.id, user_id=member.id, role="member"))
    db_session.commit()

    return {
        "admin": _token("mon_admin"),
        "member": _token("mon_member"),
        "customer": cust,
    }


# ─────────────────────────── BE-06: privileged routes ─────────────────────────

class TestMonitoringPrivilege:
    def test_liveness_public_minimal(self, client, mon_env):
        r = client.get("/api/monitoring/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        # No host/process/metrics leak on the public liveness surface.
        assert "system" not in body
        assert "metrics" not in body
        assert "database" not in body
        assert "ai_endpoint" not in body

    def test_detailed_anonymous_401(self, client, mon_env):
        assert client.get("/api/monitoring/health/detailed").status_code == 401
        assert client.get("/api/monitoring/status").status_code == 401
        assert client.get("/api/monitoring/metrics").status_code == 401

    def test_detailed_non_admin_403(self, client, mon_env):
        assert client.get("/api/monitoring/health/detailed",
                          headers=mon_env["member"]).status_code == 403
        assert client.get("/api/monitoring/status",
                          headers=mon_env["member"]).status_code == 403
        assert client.get("/api/monitoring/metrics",
                          headers=mon_env["member"]).status_code == 403

    def test_detailed_admin_200_real_database(self, client, mon_env):
        r = client.get("/api/monitoring/health/detailed", headers=mon_env["admin"])
        assert r.status_code == 200
        body = r.json()
        # Real bounded DB check (was hardwired healthy/connected).
        assert body["database"]["status"] == "healthy"
        assert body["database"]["connected"] is True
        assert body["database"]["backend"] in ("sqlite", "postgresql")
        assert "system" in body  # psutil detail is present on the admin surface

    def test_metrics_admin_200(self, client, mon_env):
        r = client.get("/api/monitoring/metrics", headers=mon_env["admin"])
        assert r.status_code == 200
        assert "requests" in r.json()


# ─────────────────────────── BE-05: real readiness ────────────────────────────

class TestMonitoringReadiness:
    def test_status_admin_healthy(self, client, mon_env):
        r = client.get("/api/monitoring/status", headers=mon_env["admin"])
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert body["subsystems"]["database"]["connected"] is True

    def test_status_degraded_on_db_failure(self, client, mon_env):
        from backend import monitoring

        with patch.object(
            monitoring,
            "get_database_health",
            return_value={"status": "unhealthy", "connected": False,
                          "error": "mock connection failure"},
        ):
            r = client.get("/api/monitoring/status", headers=mon_env["admin"])
        assert r.status_code == 200
        body = r.json()
        # A failed dependency check degrades readiness while liveness remains.
        assert body["status"] == "degraded"
        assert body["subsystems"]["database"]["connected"] is False

    def test_detailed_degraded_on_db_failure(self, client, mon_env):
        from backend import monitoring

        with patch.object(
            monitoring,
            "get_database_health",
            return_value={"status": "unhealthy", "connected": False,
                          "error": "mock connection failure"},
        ):
            r = client.get("/api/monitoring/health/detailed", headers=mon_env["admin"])
        assert r.status_code == 200
        assert r.json()["database"]["connected"] is False

    def test_ai_health_uses_effective_settings(self, client, mon_env):
        """BE-05: the diagnostic reports the EFFECTIVE inference configuration
        (DB overrides + enabled flag), not just the env var — and never the
        endpoint URL or key."""
        from backend import monitoring

        effective = {
            "ai_endpoint": "http://10.0.0.9:8000/v1",
            "ai_model": "override-model",
            "api_key": "secret-should-never-leak",
            "enabled": False,
        }
        with patch(
            "backend.services.config_service.effective_inference_settings",
            return_value=effective,
        ):
            health = monitoring.get_ai_endpoint_health()
        assert health["status"] == "disabled"
        assert health["enabled"] is False
        assert health["model"] == "override-model"
        blob = str(health)
        assert "10.0.0.9" not in blob
        assert "secret-should-never-leak" not in blob

    def test_ai_health_disabled_via_db_override(self, client, mon_env):

        effective = {
            "ai_endpoint": "http://10.0.0.9:8000/v1",
            "ai_model": "override-model",
            "api_key": "x",
            "enabled": False,
        }
        with patch(
            "backend.services.config_service.effective_inference_settings",
            return_value=effective,
        ):
            r = client.get("/api/monitoring/health/detailed", headers=mon_env["admin"])
        assert r.status_code == 200
        ai = r.json()["ai_endpoint"]
        assert ai["status"] == "disabled"
        # No endpoint URL or key in the response body.
        assert "10.0.0.9" not in str(r.json())


# ─────────────────────────── BE-07: readiness over full dataset ───────────────

class TestSalesReadinessFullDataset:
    def test_readiness_counts_past_1000_rows(self, db_session, client, mon_env):
        """Customer A: 1005 use cases (1000 scored 50.0 + 5 unscored) + a
        zero score (scores present). Customer B: 3 use cases. The readiness
        endpoint must report the COMPLETE counts/average for A (the old
        limit=1000 fetch capped at 1000) and never mix in B's records."""
        from backend.models.use_case import UseCase

        a = mon_env["customer"]
        from backend.models.use_case import Customer
        other = Customer(name="MonOther", description="O")
        db_session.add(other)
        db_session.commit()
        db_session.refresh(other)

        # 1005 rows for customer A: 1000 scored 50.0, 4 unscored,
        # 1 scored 0.0 (zero is a real low score, counted as scored).
        rows = []
        for i in range(1000):
            rows.append(UseCase(title=f"A uc {i}", customer_id=a.id, department="D",
                                status="active", overall_score=50.0, created_by="seed"))
        for i in range(4):
            rows.append(UseCase(title=f"A unscored {i}", customer_id=a.id,
                                department="D", status="draft", created_by="seed"))
        rows.append(UseCase(title="A zero", customer_id=a.id, department="D",
                            status="active", overall_score=0.0, created_by="seed"))
        db_session.add_all(rows)
        # 3 rows for customer B (different scores).
        for i, score in enumerate([10.0, None, 90.0]):
            db_session.add(UseCase(title=f"B uc {i}", customer_id=other.id,
                                   department="D", status="active",
                                   overall_score=score, created_by="seed"))
        db_session.commit()

        r = client.get(f"/api/sales/customers/{a.id}/readiness",
                       headers=mon_env["admin"])
        assert r.status_code == 200
        org = r.json()["organizational_readiness"]
        # COMPLETE dataset: 1005 total (1000 + 4 + 1), 1001 scored
        # (1000×50.0 + 1×0.0) → average = 1000*50/1001 ≈ 49.95.
        assert org["total_use_cases"] == 1005
        assert org["scored_use_cases"] == 1001
        assert abs(org["average_score"] - round(1000 * 50.0 / 1001, 2)) < 0.01

        # Customer B's readiness is independent (3 total, 2 scored, avg 50.0).
        r_b = client.get(f"/api/sales/customers/{other.id}/readiness",
                         headers=mon_env["admin"])
        assert r_b.status_code == 200
        org_b = r_b.json()["organizational_readiness"]
        assert org_b["total_use_cases"] == 3
        assert org_b["scored_use_cases"] == 2
        assert org_b["average_score"] == 50.0

    def test_sales_usecases_pagination(self, db_session, client, mon_env):
        """The sales use-case listing is explicitly paginated (BE-07/BE-03),
        not silently capped at 1000."""
        from backend.models.use_case import UseCase
        a = mon_env["customer"]
        rows = [
            UseCase(title=f"Pag uc {i}", customer_id=a.id, department="D",
                    status="active", overall_score=float(i), created_by="seed")
            for i in range(150)
        ]
        db_session.add_all(rows)
        db_session.commit()

        r = client.get(f"/api/sales/customers/{a.id}/usecases",
                       headers=mon_env["admin"])
        assert r.status_code == 200
        assert len(r.json()) == 100  # default page size

        r2 = client.get(f"/api/sales/customers/{a.id}/usecases?skip=100&limit=100",
                        headers=mon_env["admin"])
        assert r2.status_code == 200
        assert len(r2.json()) == 50
        ids1 = {u["id"] for u in r.json()}
        ids2 = {u["id"] for u in r2.json()}
        assert ids1.isdisjoint(ids2)

        # Same bounded contract as /api/use-cases/.
        assert client.get(
            f"/api/sales/customers/{a.id}/usecases?limit=0",
            headers=mon_env["admin"],
        ).status_code == 422
        assert client.get(
            f"/api/sales/customers/{a.id}/usecases?limit=5000",
            headers=mon_env["admin"],
        ).status_code == 422
