
"""Regression tests: customer scoping for bulk scoring and template creation.

Covers the security gap flagged in the 2026-08-18 session summary:
the bulk endpoints accepted unauthenticated requests, and use cases
without a customer assignment bypassed the junction check entirely,
so any caller could trigger scoring on any use case.

Access-denied paths short-circuit before the AI call (fast). Allowed
paths perform real inference calls — project convention: AI is real
and never mocked/deterministic in tests.

Run: pytest tests/backend/test_bulk_scoping.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest
from backend.dependencies import get_db
from sqlalchemy.orm import sessionmaker

from tests.backend._shared import engine

_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _token_for(username: str, is_admin: bool = False) -> dict:
    from backend.auth import create_access_token
    token = create_access_token({"sub": username, "is_admin": bool(is_admin)})
    return {"Authorization": f"Bearer {token}"}


def _seed(db_session):
    """Create customers, users, junction entries, and use cases.

    Returns a dict of the created ids.
    """
    from backend.models.use_case import Customer, CustomerUser, UseCase, User

    bulk_admin = User(username="bulk_admin", email="ba@test.local",
                      hashed_password=_FAKE_HASH, role="admin", is_admin=1,
                      approved=1, is_active=1)
    bulk_member = User(username="bulk_member", email="bm@test.local",
                       hashed_password=_FAKE_HASH, role="user", is_admin=0,
                       approved=1, is_active=1)
    bulk_stranger = User(username="bulk_stranger", email="bs@test.local",
                         hashed_password=_FAKE_HASH, role="user", is_admin=0,
                         approved=1, is_active=1)
    bulk_auditor = User(username="bulk_auditor", email="bu@test.local",
                        hashed_password=_FAKE_HASH, role="user", is_admin=0,
                        approved=1, is_active=1)
    db_session.add_all([bulk_admin, bulk_member, bulk_stranger, bulk_auditor])
    db_session.commit()
    for u in (bulk_admin, bulk_member, bulk_stranger, bulk_auditor):
        db_session.refresh(u)

    cust_a = Customer(name="ScopeCustA", description="A")
    cust_b = Customer(name="ScopeCustB", description="B")
    db_session.add_all([cust_a, cust_b])
    db_session.commit()
    db_session.refresh(cust_a)
    db_session.refresh(cust_b)

    db_session.add(CustomerUser(customer_id=cust_a.id, user_id=bulk_member.id, role="member"))
    db_session.add(CustomerUser(customer_id=cust_a.id, user_id=bulk_auditor.id, role="auditor"))
    db_session.commit()

    uc_a = UseCase(title="UC in A", customer_id=cust_a.id, status="active", created_by="test")
    uc_b = UseCase(title="UC in B", customer_id=cust_b.id, status="active", created_by="test")
    uc_none = UseCase(title="UC unassigned", customer_id=None, status="active", created_by="test")
    db_session.add_all([uc_a, uc_b, uc_none])
    db_session.commit()
    for uc in (uc_a, uc_b, uc_none):
        db_session.refresh(uc)

    return {
        "cust_a": cust_a.id,
        "cust_b": cust_b.id,
        "uc_a": uc_a.id,
        "uc_b": uc_b.id,
        "uc_none": uc_none.id,
    }


def _assert_no_access_errors(data: dict):
    """Assert none of the per-item errors is an access violation."""
    for err in data.get("errors", []):
        msg = err["error"]
        assert "No write access" not in msg, f"unexpected access error: {msg}"
        assert "Auditors cannot score" not in msg, f"unexpected access error: {msg}"
        assert "Unassigned use cases are admin-only" not in msg, f"unexpected access error: {msg}"
        assert "Authentication required" not in msg, f"unexpected access error: {msg}"


with patch("backend.auth.hash_password", side_effect=lambda p: _FAKE_HASH):
    from backend.main import app
    from fastapi.testclient import TestClient

    @pytest.fixture(scope="function")
    def db_session():
        """Reset the selected integration backend; no secondary SQLite fallback."""
        from tests.backend.database_support import reset_tables

        session = sessionmaker(bind=engine, autoflush=False)()
        try:
            reset_tables(session, reset_ids=True)
            yield session
        finally:
            session.rollback()
            session.close()

    @pytest.fixture()
    def client(db_session):
        def override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    class TestBulkScoringScoping:
        """The bulk score endpoint enforces auth + junction access per use case."""

        def test_unauthenticated_bulk_score_rejected(self, client):
            r = client.post("/api/bulk/score-multiple/", json=[1, 2])
            assert r.status_code == 401

        def test_bulk_score_denied_for_customer_without_access(self, client, db_session):
            ids = _seed(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json=[ids["uc_a"], ids["uc_b"]],
                headers=_token_for("bulk_stranger"),
            )
            assert r.status_code == 200
            data = r.json()
            assert data["success_count"] == 0
            assert data["error_count"] == 2
            # R4/Q7: out-of-scope ids report the SAME per-item error as
            # missing ids — a batch probe must not confirm existence.
            for err in data["errors"]:
                assert err["error"] == f"Use case {err['use_case_id']} not found"

        def test_bulk_score_denied_for_unassigned_use_case(self, client, db_session):
            ids = _seed(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json=[ids["uc_none"]],
                headers=_token_for("bulk_stranger"),
            )
            data = r.json()
            assert data["error_count"] == 1
            # R2 + R4/Q7: unassigned use cases are admin-only; for a
            # non-admin the id is the same per-item error as a missing one.
            assert data["errors"][0]["error"] == f"Use case {ids['uc_none']} not found"

        def test_bulk_score_denied_for_auditor(self, client, db_session):
            ids = _seed(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json=[ids["uc_a"]],
                headers=_token_for("bulk_auditor"),
            )
            data = r.json()
            assert data["error_count"] == 1
            # Central-policy denial (Part 13 DV6): an auditor junction holds
            # no CAP_EDIT on the customer = no write access.
            assert data["errors"][0]["error"] == "scoring requires edit access to this customer"

        def test_bulk_score_allowed_for_member(self, client, db_session):
            """Member of customer A can score A's use case (real AI call)."""
            ids = _seed(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json=[ids["uc_a"]],
                headers=_token_for("bulk_member"),
            )
            assert r.status_code == 200
            data = r.json()
            _assert_no_access_errors(data)
            if data["success_count"] == 1:
                from backend.models.use_case import UseCase
                uc = db_session.query(UseCase).filter(UseCase.id == ids["uc_a"]).first()
                assert uc.overall_score is not None

        def test_admin_can_score_unassigned_and_any_customer(self, client, db_session):
            """Admins bypass the junction check (real AI calls)."""
            ids = _seed(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json=[ids["uc_none"], ids["uc_b"]],
                headers=_token_for("bulk_admin", is_admin=True),
            )
            assert r.status_code == 200
            _assert_no_access_errors(r.json())

        def test_single_scoring_unassigned_denied_for_non_admin(self, client, db_session):
            ids = _seed(db_session)
            r = client.post(
                "/api/scoring/",
                json={"use_case_id": ids["uc_none"], "reasoning": "test"},
                headers=_token_for("bulk_member"),
            )
            assert r.status_code == 403


class TestCreateFromTemplateScoping:
    """create-from-template enforces junction access when a customer is given.

    Reuses the module-level client/db_session fixtures.
    """

    def test_create_from_template_denied_without_access(self, client, db_session):
        ids = _seed(db_session)
        r = client.post(
            "/api/bulk/create-from-template/",
            json={
                "template_id": "operations",
                "title": "Scoped Create",
                "department": "Operations",
                "customer_id": ids["cust_a"],
            },
            headers=_token_for("bulk_stranger"),
        )
        # 404-first (R4/Q7): a customer the stranger cannot reach is the same
        # 404 as a missing one.
        assert r.status_code == 404

    def test_create_from_template_ok_for_member(self, client, db_session):
        ids = _seed(db_session)
        r = client.post(
            "/api/bulk/create-from-template/",
            json={
                "template_id": "operations",
                "title": "Member Create",
                "department": "Operations",
                "customer_id": ids["cust_a"],
            },
            headers=_token_for("bulk_member"),
        )
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        from backend.models.use_case import UseCase
        uc = db_session.query(UseCase).filter(UseCase.id == data["id"]).first()
        assert uc.customer_id == ids["cust_a"]
        assert uc.created_by == "bulk_member"

    def test_create_from_template_unknown_template_404(self, client, db_session):
        _seed(db_session)
        r = client.post(
            "/api/bulk/create-from-template/",
            json={"template_id": "nope", "title": "X", "department": "IT"},
            headers=_token_for("bulk_member"),
        )
        assert r.status_code == 404
