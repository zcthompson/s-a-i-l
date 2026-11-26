
"""WP1 contract regression tests — the exact wire shapes the frontend sends/expects.

Pins the five P0 contract breaks found in the 2026-08-25 end-to-end audit
(PLAN.md part 13) against the exact payload shapes the React client uses:

- P0-1: bulk scoring body must be a BARE JSON array of ids — the old
  frontend object body ``{"use_case_ids": [...]}`` must keep 422-ing.
- P0-2: assessment-round creation takes a JSON body (``{"name": ...}``),
  not a query parameter.
- P0-3: templates live under ``/api/bulk/templates/`` (the old
  ``/api/templates/`` path must 404).
- P0-4: ``POST /api/scoring/`` returns the ``{use_case, scores}`` envelope;
  ``scores`` carries ``dimension_scores`` and has NO ``use_case_id`` field.
- P0-5: ``GET /api/customers/{name}/users/`` returns ``{"users": [...]}``.

The AI boundary (``AIClient``) is replaced with a deterministic canned
response: these tests pin the HTTP contract (request binding + response
serialization through the route's ``response_model``), not the LLM. The
real route logic (auth, junction access, persistence, score history,
audit log) still runs end to end.

Run: pytest tests/backend/test_frontend_contract.py -v
"""

import copy
import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest
from backend.dependencies import get_db

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

from backend.services.scoring import ScoringService as _ScoringService

# Canned AI scoring response — deterministic stand-in for the LLM.
# Mirrors what AIClient.score_use_case returns: overall_score,
# dimension_scores entries (name/score/weight/description), ISO scored_at.
_CANNED_SCORES = {
    "dimension_scores": [
        {"name": d["name"], "score": 72.0 + 3.0 * i, "weight": d["weight"],
         "description": f"Canned score for {d['name']}"}
        for i, d in enumerate(_ScoringService.DIMENSIONS)
    ],
    "overall_score": 74.0,
    "reasoning": "Canned deterministic scoring response (test seam - no LLM call).",
    "scored_at": "2026-08-25T12:00:00Z",
    "recommendations": ["Canned recommendation"],
}


class _FakeAIClient:
    """AIClient stand-in: no network, deterministic scores."""

    def __init__(self, settings=None):
        self.settings = settings

    async def score_use_case(self, use_case_data):
        return copy.deepcopy(_CANNED_SCORES)


with patch("backend.auth.hash_password", side_effect=lambda pw: _FAKE_BCRYPT_HASH):
    from backend.auth import create_access_token
    from backend.main import app
    from backend.models.use_case import (
        Customer,
        CustomerUser,
        UseCase,
        User,
    )
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from tests.backend._shared import engine

    @pytest.fixture(scope="function")
    def db_session():
        """Reset the selected integration backend; no secondary SQLite fallback."""
        from tests.backend.database_support import reset_tables

        session = sessionmaker(bind=engine, autoflush=False)()
        try:
            reset_tables(session)
            yield session
        finally:
            session.rollback()
            session.close()

    @pytest.fixture(autouse=True)
    def _auth_user_lookup(db_session):
        """Route-level auth: point the real JWT user lookup at the shared
        session so seeded users are visible (test_api.py pattern). Also
        guarantees the admin user exists."""
        from backend import auth as auth_mod

        bind = db_session.get_bind()
        shared = getattr(bind, "engine", bind)

        if not db_session.query(User).count():
            db_session.add(User(
                username="admin", email="admin@test.local",
                hashed_password=_FAKE_BCRYPT_HASH,
                display_name="Administrator", department="IT",
                is_admin=1, approved=1, is_active=1,
            ))
            db_session.commit()

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

        def _shared_engine(*args, **kwargs):
            return shared

        with patch.object(auth_mod, "_get_user_by_username", _lookup), \
             patch.object(auth_mod, "create_engine", _shared_engine):
            yield

    @pytest.fixture()
    def client(db_session):
        app.dependency_overrides[get_db] = lambda: db_session
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    @pytest.fixture()
    def admin_headers():
        return {
            "Authorization": f"Bearer {create_access_token({'sub': 'admin', 'is_admin': True})}"
        }

    @pytest.fixture()
    def ai_seam():
        """Patch the AI boundary so scoring stays deterministic (no LLM)."""
        with patch("backend.services.scoring.AIClient", _FakeAIClient):
            yield

    def _seed_customer(db_session, name="ContractCo"):
        c = Customer(name=name, description="contract regression seed")
        db_session.add(c)
        db_session.commit()
        db_session.refresh(c)
        return c

    def _seed_use_case(db_session, customer=None, title="Contract UC"):
        uc = UseCase(
            title=title,
            description="contract regression seed",
            department="Operations",
            status="draft",
            customer_id=customer.id if customer else None,
        )
        db_session.add(uc)
        db_session.commit()
        db_session.refresh(uc)
        return uc

    # ── P0-1: bulk scoring body contract ─────────────────────────────────

    class TestBulkScoreBodyContract:
        def test_object_body_rejected(self, client, admin_headers, db_session):
            """The OLD frontend payload (object body) must keep 422-ing:
            the route binds the ENTIRE body as a bare int array."""
            uc = _seed_use_case(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json={"use_case_ids": [uc.id]},
                headers=admin_headers,
            )
            assert r.status_code == 422

        def test_bare_array_accepted(self, client, admin_headers, db_session, ai_seam):
            """The FIXED frontend payload (bare JSON array) scores 200 and
            returns per-item {use_case, scores} envelopes."""
            uc = _seed_use_case(db_session)
            r = client.post(
                "/api/bulk/score-multiple/",
                json=[uc.id],
                headers=admin_headers,
            )
            assert r.status_code == 200
            data = r.json()
            assert data["success_count"] == 1
            assert data["error_count"] == 0
            item = data["results"][0]
            assert set(item.keys()) == {"use_case", "scores"}
            assert item["use_case"]["id"] == uc.id
            assert len(item["scores"]["dimension_scores"]) == len(_ScoringService.DIMENSIONS)
            # Wire shape: no phantom use_case_id field on scores
            assert "use_case_id" not in item["scores"]

    # ── P0-2: assessment-round creation body ─────────────────────────────

    class TestAssessmentCreateContract:
        def test_query_only_rejected(self, client, admin_headers, db_session):
            """The OLD frontend call (name as query param, no body) must
            keep 422-ing: the route requires an AssessmentNameIn body."""
            _seed_customer(db_session)
            r = client.post(
                "/api/customers/ContractCo/assessments/",
                params={"name": "Query Round"},
                headers=admin_headers,
            )
            assert r.status_code == 422

        def test_body_accepted(self, client, admin_headers, db_session):
            """The FIXED frontend call (JSON body) creates the round."""
            _seed_customer(db_session)
            r = client.post(
                "/api/customers/ContractCo/assessments/",
                json={"name": "Body Round"},
                headers=admin_headers,
            )
            assert r.status_code == 201
            data = r.json()
            assert data["name"] == "Body Round"
            assert data["status"] == "active"

    # ── P0-3: templates paths ─────────────────────────────────────────────

    class TestTemplatesPathContract:
        def test_old_path_404(self, client, admin_headers):
            """The pre-fix path must stay a 404 (it was never routed)."""
            r = client.get("/api/templates/", headers=admin_headers)
            assert r.status_code == 404

        def test_list(self, client, admin_headers):
            r = client.get("/api/bulk/templates/", headers=admin_headers)
            assert r.status_code == 200
            data = r.json()
            # WP19: the template registry was consolidated into a single
            # backend module (backend/templates.py) — 4 generic + 7 rich =
            # 11. Documented contract update, not a weakening: the
            # "operations" key, its detail shape, and the 404 paths below
            # all still hold.
            assert data["count"] == 11
            assert "operations" in data["templates"]

        def test_detail(self, client, admin_headers):
            r = client.get("/api/bulk/templates/operations/", headers=admin_headers)
            assert r.status_code == 200
            data = r.json()
            assert data["id"] == "operations"
            assert data["name"] == "Operations Template"

        def test_detail_unknown_404(self, client, admin_headers):
            r = client.get("/api/bulk/templates/nope/", headers=admin_headers)
            assert r.status_code == 404

    # ── P0-4: scoring response envelope ──────────────────────────────────

    class TestScoringEnvelopeContract:
        def test_envelope_shape(self, client, admin_headers, db_session, ai_seam):
            uc = _seed_use_case(db_session)
            r = client.post(
                "/api/scoring/",
                json={"use_case_id": uc.id},
                headers=admin_headers,
            )
            assert r.status_code == 200
            data = r.json()
            # Envelope, not a bare ScoringResponse
            assert set(data.keys()) == {"use_case", "scores"}
            assert data["use_case"]["id"] == uc.id
            scores = data["scores"]
            assert scores["overall_score"] == _CANNED_SCORES["overall_score"]
            assert len(scores["dimension_scores"]) == len(_ScoringService.DIMENSIONS)
            # Wire shape: no phantom use_case_id field on scores
            assert "use_case_id" not in scores
            # The score persisted onto the use case
            got = client.get(f"/api/use-cases/{uc.id}/", headers=admin_headers).json()
            assert got["overall_score"] == _CANNED_SCORES["overall_score"]

    # ── P0-5: customer users envelope ────────────────────────────────────

    class TestCustomerUsersEnvelope:
        def test_users_envelope(self, client, admin_headers, db_session):
            customer = _seed_customer(db_session)
            admin = db_session.query(User).filter(User.username == "admin").first()
            member = User(
                username="member1", email="member1@test.local",
                hashed_password=_FAKE_BCRYPT_HASH,
                department="Ops", approved=1, is_active=1,
            )
            db_session.add(member)
            db_session.commit()
            db_session.refresh(member)
            db_session.add(CustomerUser(
                customer_id=customer.id, user_id=member.id,
                role="member", granted_by=admin.id,
            ))
            db_session.commit()

            r = client.get("/api/customers/ContractCo/users/", headers=admin_headers)
            assert r.status_code == 200
            data = r.json()
            # Envelope, not a bare array
            assert set(data.keys()) == {"users"}
            assert isinstance(data["users"], list)
            entry = data["users"][0]
            assert entry["username"] == "member1"
            assert entry["role"] == "member"
            assert entry["user_id"] == member.id
            assert entry["customer_id"] == customer.id
