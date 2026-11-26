
"""P3-2: Cross-customer data isolation tests.

Tests that the junction table enforces strict customer isolation:
1. Create customer A -> add user1 as owner -> add user2 as member
2. Test: user1 can access customer A, user2 cannot access customer B
3. Test: user1 cannot create/use case in customer B
4. Test: junction table access control on scoring endpoint

Run: pytest tests/backend/test_multi_tenant_isolation.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import copy
from unittest.mock import patch

import pytest
from backend.dependencies import get_db
from backend.services.scoring import ScoringService as _ScoringService

# Canned AI scoring response — deterministic stand-in for the LLM.
# Mirrors what AIClient.score_use_case returns (see
# tests/backend/test_frontend_contract.py for the established seam pattern):
# the scoring-route tests below verify junction enforcement, not the model.
# The dedicated real-inference liveness test lives in
# tests/backend/test_real_inference.py.
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

from sqlalchemy.orm import sessionmaker

from tests.backend._shared import engine

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _no_background_inference_for_access_tests(monkeypatch):
    # These tests pin junction authorization. Insight generation has its own
    # worker/AI tests; launching it here races the shared SQLite connection.
    monkeypatch.setattr("backend.services.insight_service.InsightService.trigger_async", lambda *args, **kwargs: None)


def _fake_hash_password(password: str) -> str:
    return _FAKE_BCRYPT_HASH


with patch("backend.auth.hash_password", side_effect=_fake_hash_password):
    from backend.auth import create_access_token
    from backend.main import app
    from backend.models.use_case import Customer, CustomerUser, User
    from fastapi.testclient import TestClient

    @pytest.fixture()
    def client():
        def override_get_db():
            session = sessionmaker(bind=engine)()
            try:
                yield session
            finally:
                session.rollback()
                session.close()
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    @pytest.fixture()
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
    def admin_auth(client, db_session):
        """Get admin auth headers."""
        existing = db_session.query(User).filter(User.username == "admin").first()
        if existing:
            token = create_access_token({"sub": "admin", "is_admin": True})
            return {"Authorization": f"Bearer {token}"}
        admin = User(
            username="admin", email="admin@example.com",
            hashed_password=_fake_hash_password("adminpass"),
            role="admin", is_admin=True, approved=1, is_active=1,
        )
        db_session.add(admin)
        db_session.commit()
        token = create_access_token({"sub": "admin", "is_admin": True})
        return {"Authorization": f"Bearer {token}"}

    def _create_user(db_session, username, email, role="user"):
        """Helper to create a user and return auth headers + user object."""
        user = User(
            username=username, email=email,
            hashed_password=_fake_hash_password("pass"),
            role=role, approved=1, is_active=1,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        token = create_access_token({"sub": username, "is_admin": role == "admin"})
        return {"Authorization": f"Bearer {token}"}, user

    # ------------------------------------------------------------------
    # P3-2: Create Customer -> Add Users -> Verify Junction
    # ------------------------------------------------------------------

    class TestCreateCustomerAndAddUsers:
        """Test the full lifecycle: create customer -> add users -> verify junction."""

        def test_create_customer_a_add_owner_and_member(self, client, admin_auth, db_session):
            """Step 1: Create customer A -> add user1 as owner -> add user2 as member."""
            # Create customer A
            r = client.post("/api/customers/", json={"name": "Customer A", "description": "Test cust A"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "Customer A").first()
            assert cust_a is not None
            assert cust_a.id == 1

            # Add user1 as owner
            user_headers1, user1 = _create_user(db_session, "owneruser1", "owner1@test.example")
            r = client.post(
                "/api/customers/Customer%20A/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            junction = db_session.query(CustomerUser).filter_by(customer_id=cust_a.id, user_id=user1.id).first()
            assert junction is not None
            assert junction.role == "owner"

            # Add user2 as member
            user_headers2, user2 = _create_user(db_session, "memberuser1", "member1@test.example")
            r = client.post(
                "/api/customers/Customer%20A/users/",
                params={"user_id": user2.id, "role": "member"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            junction2 = db_session.query(CustomerUser).filter_by(customer_id=cust_a.id, user_id=user2.id).first()
            assert junction2 is not None
            assert junction2.role == "member"

        def test_create_customer_b_add_auditor(self, client, admin_auth, db_session):
            """Create customer B and add an auditor user."""
            r = client.post("/api/customers/", json={"name": "Customer B", "description": "Test cust B"}, headers=admin_auth)
            assert r.status_code == 201
            cust_b = db_session.query(Customer).filter(Customer.name == "Customer B").first()
            # Don't hardcode IDs - query for actual ID
            assert cust_b is not None

            user_headers, auditor_user = _create_user(db_session, "auditoruser1", "auditor1@test.example")
            r = client.post(
                "/api/customers/Customer%20B/users/",
                params={"user_id": auditor_user.id, "role": "auditor"},
                headers=admin_auth,
            )
            assert r.status_code == 200
            junction = db_session.query(CustomerUser).filter_by(customer_id=cust_b.id, user_id=auditor_user.id).first()
            assert junction is not None
            assert junction.role == "auditor"

    # ------------------------------------------------------------------
    # P3-2: Cross-Customer Isolation
    # ------------------------------------------------------------------

    class TestCrossCustomerIsolation:
        """Test that users cannot access customers they don't have junction access to."""

        def test_user1_cannot_access_customer_b(self, client, admin_auth, db_session):
            """user1 (owner of Customer A) cannot access Customer B."""
            # Setup: create Customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "IsoCustA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "IsoCustA").first()

            user_headers1, user1 = _create_user(db_session, "isouser1", "iso1@test.example")
            r = client.post(
                "/api/customers/IsoCustA/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Setup: create Customer B with no access for user1
            r = client.post("/api/customers/", json={"name": "IsoCustB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201
            cust_b = db_session.query(Customer).filter(Customer.name == "IsoCustB").first()

            # Verify user1 has no junction for Customer B
            junction_b = db_session.query(CustomerUser).filter_by(customer_id=cust_b.id, user_id=user1.id).first()
            assert junction_b is None

            # Try to access Customer B -> should fail
            r = client.get("/api/customers/IsoCustB/", headers=user_headers1)
            assert r.status_code == 404  # 404-first (R4/Q7): out-of-scope == missing

        def test_user2_cannot_access_customer_b(self, client, admin_auth, db_session):
            """user2 (member of Customer A) cannot access Customer B."""
            # Setup: create Customer A with user2 as member
            r = client.post("/api/customers/", json={"name": "IsoCustA2", "description": "A2"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "IsoCustA2").first()

            user_headers2, user2 = _create_user(db_session, "isouser2", "iso2@test.example")
            r = client.post(
                "/api/customers/IsoCustA2/users/",
                params={"user_id": user2.id, "role": "member"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Setup: create Customer B with no access for user2
            r = client.post("/api/customers/", json={"name": "IsoCustB2", "description": "B2"}, headers=admin_auth)
            assert r.status_code == 201
            cust_b = db_session.query(Customer).filter(Customer.name == "IsoCustB2").first()

            junction_b = db_session.query(CustomerUser).filter_by(customer_id=cust_b.id, user_id=user2.id).first()
            assert junction_b is None

            # Try to access Customer B -> should fail
            r = client.get("/api/customers/IsoCustB2/", headers=user_headers2)
            assert r.status_code == 404  # 404-first (R4/Q7): out-of-scope == missing

        def test_admin_can_access_all_customers(self, client, admin_auth, db_session):
            """Admin user can access all customers regardless of junction."""
            r = client.post("/api/customers/", json={"name": "AdminCust", "description": "Admin test"}, headers=admin_auth)
            assert r.status_code == 201

            # Admin should be able to access the customer
            r = client.get("/api/customers/AdminCust/", headers=admin_auth)
            assert r.status_code == 200
            assert r.json()["name"] == "AdminCust"

        def test_user_cannot_list_other_customers(self, client, admin_auth, db_session):
            """User can only see customers they have junction access to."""
            # Setup: customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "UserCustA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201

            user_headers1, user1 = _create_user(db_session, "listuser1", "list1@test.example")
            r = client.post(
                "/api/customers/UserCustA/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Setup: customer B with no access for user1
            r = client.post("/api/customers/", json={"name": "UserCustB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201

            # List customers as user1 -> should only see UserCustA
            r = client.get("/api/customers/", headers=user_headers1)
            assert r.status_code == 200
            customers = r.json()
            names = [c["name"] for c in customers]
            assert "UserCustA" in names
            assert "UserCustB" not in names

    # ------------------------------------------------------------------
    # P3-2: Use Case Isolation
    # ------------------------------------------------------------------

    class TestUseCaseIsolation:
        """Test that users cannot create or use cases in customers they don't have access to."""

        def test_user_cannot_create_use_case_in_other_customer(self, client, admin_auth, db_session):
            """user1 cannot create a use case in Customer B."""
            # Setup: Customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "UCIsolA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "UCIsolA").first()

            user_headers1, user1 = _create_user(db_session, "ucisouser1", "uciso1@test.example")
            r = client.post(
                "/api/customers/UCIsolA/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Setup: Customer B with no access for user1
            r = client.post("/api/customers/", json={"name": "UCIsolB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201
            cust_b = db_session.query(Customer).filter(Customer.name == "UCIsolB").first()

            # Try to create a use case in Customer B -> should fail (no junction access)
            r = client.post(
                "/api/use-cases/",
                json={"title": "Unauthorized UC", "description": "Test", "customer_id": cust_b.id, "status": "draft"},
                headers=user_headers1,
            )
            # 404-first (R4/Q7): out of scope == missing customer.
            assert r.status_code == 404

        def test_user_can_create_use_case_in_accessible_customer(self, client, admin_auth, db_session):
            """user1 can create a use case in Customer A (where they have access)."""
            # Setup: Customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "UCIsolA2", "description": "A2"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "UCIsolA2").first()

            user_headers1, user1 = _create_user(db_session, "ucisouser2", "uciso2@test.example")
            r = client.post(
                "/api/customers/UCIsolA2/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Create a use case in Customer A -> should succeed
            r = client.post(
                "/api/use-cases/",
                json={"title": "Authorized UC", "description": "Test", "customer_id": 1, "status": "draft"},
                headers=user_headers1,
            )
            assert r.status_code == 201

        def test_user_can_list_only_their_customers_use_cases(self, client, admin_auth, db_session):
            """user1 can only list use cases from customers they have access to."""
            # Setup: Customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "ListCustA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "ListCustA").first()

            user_headers1, user1 = _create_user(db_session, "listcustuser1", "listcust1@test.example")
            r = client.post(
                "/api/customers/ListCustA/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Create a use case in Customer A
            r = client.post(
                "/api/use-cases/",
                json={"title": "UC in A", "description": "Test", "customer_id": 1, "status": "draft"},
                headers=user_headers1,
            )
            assert r.status_code == 201

            # Setup: Customer B with no access for user1
            r = client.post("/api/customers/", json={"name": "ListCustB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201

            # Create a use case in Customer B as admin
            r = client.post(
                "/api/use-cases/",
                json={"title": "UC in B", "description": "Test", "customer_id": 2, "status": "draft"},
                headers=admin_auth,
            )
            assert r.status_code == 201

            # List use cases as user1 -> should only see UC in A
            r = client.get("/api/use-cases/", headers=user_headers1)
            assert r.status_code == 200
            use_cases = r.json()
            titles = [uc["title"] for uc in use_cases]
            assert "UC in A" in titles
            assert "UC in B" not in titles

    # ------------------------------------------------------------------
    # P3-2: Scoring Endpoint Junction Enforcement
    # ------------------------------------------------------------------

    class TestScoringJunctionEnforcement:
        """Test that the scoring endpoint enforces junction table access control."""

        def test_user_cannot_score_use_case_in_other_customer(self, client, admin_auth, db_session):
            """user1 cannot score a use case in Customer B."""
            # Setup: Customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "ScoreCustA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "ScoreCustA").first()

            user_headers1, user1 = _create_user(db_session, "scoreuser1", "score1@test.example")
            r = client.post(
                "/api/customers/ScoreCustA/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Setup: Customer B with no access for user1
            r = client.post("/api/customers/", json={"name": "ScoreCustB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201
            cust_b = db_session.query(Customer).filter(Customer.name == "ScoreCustB").first()

            # Create a use case in Customer B
            r = client.post(
                "/api/use-cases/",
                json={"title": "UC for Scoring", "description": "Test", "customer_id": 2, "status": "active"},
                headers=admin_auth,
            )
            assert r.status_code == 201
            uc_id = r.json()["id"]

            # Try to score the use case -> should fail due to junction
            r = client.post(
                "/api/scoring/",
                json={"use_case_id": uc_id, "reasoning": "Test"},
                headers=user_headers1,
            )
            # 404-first (R4/Q7): out of scope == missing use case.
            assert r.status_code == 404

        def test_user_can_score_use_case_in_accessible_customer(self, client, admin_auth, db_session):
            """user1 can score a use case in Customer A (where they have junction access).

            The AI seam is stubbed (see _FakeAIClient above): this test pins
            the junction ALLOW path on scoring — not the model. The live
            model liveness test is tests/backend/test_real_inference.py.
            """
            # Setup: Customer A with user1 as owner
            r = client.post("/api/customers/", json={"name": "ScoreCustA2", "description": "A2"}, headers=admin_auth)
            assert r.status_code == 201
            cust_a = db_session.query(Customer).filter(Customer.name == "ScoreCustA2").first()

            user_headers1, user1 = _create_user(db_session, "scoreuser2", "score2@test.example")
            r = client.post(
                "/api/customers/ScoreCustA2/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Create and score a use case in Customer A
            r = client.post(
                "/api/use-cases/",
                json={"title": "UC for Scoring 2", "description": "Test", "customer_id": 1, "status": "active"},
                headers=user_headers1,
            )
            assert r.status_code == 201
            uc_id = r.json()["id"]

            with patch("backend.services.scoring.AIClient", _FakeAIClient):
                r = client.post(
                    "/api/scoring/",
                    json={"use_case_id": uc_id, "reasoning": "Test"},
                    headers=user_headers1,
                )
            assert r.status_code == 200

        def test_admin_can_score_all_use_cases(self, client, admin_auth, db_session):
            """Admin can score use cases in any customer.

            The AI seam is stubbed (see _FakeAIClient above): this test pins
            the junction ALLOW path on scoring — not the model. The live
            model liveness test is tests/backend/test_real_inference.py.
            """
            # Setup: create two customers
            r = client.post("/api/customers/", json={"name": "AdminCustA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201
            r = client.post("/api/customers/", json={"name": "AdminCustB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201

            # Create use cases in both customers as admin
            r = client.post(
                "/api/use-cases/",
                json={"title": "UC in A", "description": "Test", "customer_id": 1, "status": "active"},
                headers=admin_auth,
            )
            assert r.status_code == 201
            uc_a_id = r.json()["id"]

            r = client.post(
                "/api/use-cases/",
                json={"title": "UC in B", "description": "Test", "customer_id": 2, "status": "active"},
                headers=admin_auth,
            )
            assert r.status_code == 201
            uc_b_id = r.json()["id"]

            # Score use case in Customer A -> should succeed
            with patch("backend.services.scoring.AIClient", _FakeAIClient):
                r = client.post("/api/scoring/", json={"use_case_id": uc_a_id, "reasoning": "Test"}, headers=admin_auth)
                assert r.status_code == 200

                # Score use case in Customer B -> should also succeed
                r = client.post("/api/scoring/", json={"use_case_id": uc_b_id, "reasoning": "Test"}, headers=admin_auth)
                assert r.status_code == 200

    # ------------------------------------------------------------------
    # P3-2: Junction Role Restrictions
    # ------------------------------------------------------------------

    class TestJunctionRoleRestrictions:
        """Test that junction roles enforce appropriate restrictions."""

        def test_auditor_cannot_update_use_case(self, client, admin_auth, db_session):
            """Auditor cannot update use cases (read-only)."""
            # Setup: Customer A with auditor user
            r = client.post("/api/customers/", json={"name": "AuditorCust", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201

            user_headers, auditor_user = _create_user(db_session, "auditorrole", "auditorrole@test.example")
            r = client.post(
                "/api/customers/AuditorCust/users/",
                params={"user_id": auditor_user.id, "role": "auditor"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Create a use case as admin
            r = client.post(
                "/api/use-cases/",
                json={"title": "Auditor UC", "description": "Test", "customer_id": 1, "status": "draft"},
                headers=admin_auth,
            )
            assert r.status_code == 201
            uc_id = r.json()["id"]

            # Try to update the use case as auditor -> should fail
            r = client.put(
                f"/api/use-cases/{uc_id}/",
                json={"title": "Updated by Auditor", "status": "active"},
                headers=user_headers,
            )
            assert r.status_code == 403

        def test_auditor_can_read_use_cases(self, client, admin_auth, db_session):
            """Auditor can read use cases (read-only access)."""
            # Setup: Customer A with auditor user
            r = client.post("/api/customers/", json={"name": "AuditorCust2", "description": "A2"}, headers=admin_auth)
            assert r.status_code == 201

            user_headers, auditor_user = _create_user(db_session, "auditorrole2", "auditorrole2@test.example")
            r = client.post(
                "/api/customers/AuditorCust2/users/",
                params={"user_id": auditor_user.id, "role": "auditor"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Create a use case as admin
            r = client.post(
                "/api/use-cases/",
                json={"title": "Auditor Read UC", "description": "Test", "customer_id": 1, "status": "draft"},
                headers=admin_auth,
            )
            assert r.status_code == 201

            # Auditor should be able to read the use case
            r = client.get(f"/api/use-cases/{r.json()['id']}/", headers=user_headers)
            assert r.status_code == 200

        def test_member_cannot_delete_customer(self, client, admin_auth, db_session):
            """Member cannot delete the customer."""
            # Setup: Customer A with member user
            r = client.post("/api/customers/", json={"name": "MemberCust", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201

            user_headers, member_user = _create_user(db_session, "memberrole", "memberrole@test.example")
            r = client.post(
                "/api/customers/MemberCust/users/",
                params={"user_id": member_user.id, "role": "member"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Member tries to delete the customer -> should fail
            r = client.delete("/api/customers/MemberCust/", headers=user_headers)
            assert r.status_code == 403

    # ------------------------------------------------------------------
    # P3-2: Get My Customers
    # ------------------------------------------------------------------

    class TestGetMyCustomers:
        """Test that users can only list their assigned customers."""

        def test_user_sees_only_assigned_customers(self, client, admin_auth, db_session):
            """User can only list customers they have junction access to."""
            # Setup: create three customers
            r = client.post("/api/customers/", json={"name": "MyCustA", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201
            r = client.post("/api/customers/", json={"name": "MyCustB", "description": "B"}, headers=admin_auth)
            assert r.status_code == 201
            r = client.post("/api/customers/", json={"name": "MyCustC", "description": "C"}, headers=admin_auth)
            assert r.status_code == 201

            # Add user1 to Customer A as owner
            user_headers1, user1 = _create_user(db_session, "mycustuser1", "mycust1@test.example")
            r = client.post(
                "/api/customers/MyCustA/users/",
                params={"user_id": user1.id, "role": "owner"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # Add user1 to Customer B as member
            r = client.post(
                "/api/customers/MyCustB/users/",
                params={"user_id": user1.id, "role": "member"},
                headers=admin_auth,
            )
            assert r.status_code == 200

            # user1 should NOT be added to Customer C

            # Get my customers for user1 -> should only return A and B
            r = client.get("/api/customers/me/customers/", headers=user_headers1)
            assert r.status_code == 200
            my_customers = r.json()
            names = [c["customer_name"] for c in my_customers]
            assert "MyCustA" in names
            assert "MyCustB" in names
            assert "MyCustC" not in names

        def test_admin_sees_all_customers(self, client, admin_auth, db_session):
            """Admin sees all customers via my-customers endpoint."""
            r = client.post("/api/customers/", json={"name": "AdminMyCust", "description": "A"}, headers=admin_auth)
            assert r.status_code == 201

            r = client.get("/api/customers/me/customers/", headers=admin_auth)
            assert r.status_code == 200
            my_customers = r.json()
            names = [c["customer_name"] for c in my_customers]
            assert "AdminMyCust" in names
