"""Tests for projection service."""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

# Import AsyncMock for Python 3.8+
try:
    from unittest.mock import AsyncMock
except ImportError:
    # Python 3.7 fallback
    class FakeAsyncMock(MagicMock):
        async def __call__(self, *args, **kwargs):
            return super().__call__(*args, **kwargs)
    AsyncMock = FakeAsyncMock

from backend.models.use_case import Customer, CustomerUser, Projection, UseCase, User
from backend.services.projection_service import ProjectionService

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Keep JWT user and CustomerUser lookups on the shared test database."""
    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

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

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", lambda *args, **kwargs: shared_engine):
        yield



def _token(username):
    from backend.auth import create_access_token

    token = create_access_token({"sub": username})
    return {"Authorization": f"Bearer {token}"}


class TestProjectionService:
    """Test the projection service."""

    @pytest.mark.asyncio
    async def test_generate_projection_customer_not_found(self):
        """Test that ValueError is raised when customer is not found."""
        db = MagicMock()

        # Mock the chain: db.query(Customer).filter(...).first() returns None
        mock_chain = MagicMock()
        mock_chain.filter.return_value.first.return_value = None
        db.query.return_value = mock_chain

        with pytest.raises(ValueError, match="Customer test not found"):
            await ProjectionService.generate_projection(db, "test")

    @pytest.mark.asyncio
    async def test_generate_projection_no_use_cases(self):
        """Test projection with no use cases returns defaults."""
        db = MagicMock()

        # Mock db.query(Customer).filter(...).first() -> customer
        customer_query_chain = MagicMock()
        customer_query_chain.filter.return_value.first.return_value = Customer(
            id=1, name="test", description="Test"
        )
        db.query.return_value = customer_query_chain

        # Mock db.query(UseCase).filter(...).all() -> empty list
        use_case_query_chain = MagicMock()
        use_case_query_chain.filter.return_value.all.return_value = []

        def query_side_effect(model):
            if model == UseCase:
                return use_case_query_chain
            return customer_query_chain

        db.query.side_effect = query_side_effect

        projection = await ProjectionService.generate_projection(db, "test")

        assert projection["customer_name"] == "test"
        assert projection["speed"]["current"] == 0.0
        assert projection["value"]["current"] == 0.0
        assert projection["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_generate_projection_with_use_cases(self):
        """Test projection generation with use cases."""
        db = MagicMock()

        # Create mock use cases with all required attributes for to_dict()
        use_case1 = UseCase(
            id=1,
            title="Test Use Case 1",
            department="IT",
            status="active",
            overall_score=75.0,
            estimated_savings=50000,
            estimated_revenue=100000,
            description="Test 1",
            customer_id=1,
            customer=None,
            scored_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            score_history=[],
            scores=None,
            goals=None,
            challenges=None,
            pain_points=None,
            impact_category=None,
            impact_description=None,
            timeline_estimate=None,
        )

        use_case2 = UseCase(
            id=2,
            title="Test Use Case 2",
            department="Finance",
            status="active",
            overall_score=80.0,
            estimated_savings=30000,
            estimated_revenue=80000,
            description="Test 2",
            customer_id=1,
            customer=None,
            scored_at=datetime.now(UTC),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            score_history=[],
            scores=None,
            goals=None,
            challenges=None,
            pain_points=None,
            impact_category=None,
            impact_description=None,
            timeline_estimate=None,
        )

        # Mock db.query(Customer).filter(...).first() -> customer
        customer_query_chain = MagicMock()
        customer_query_chain.filter.return_value.first.return_value = Customer(
            id=1, name="test", description="Test"
        )

        # Mock db.query(UseCase).filter(...).all() -> [use_case1, use_case2]
        use_case_query_chain = MagicMock()
        use_case_query_chain.filter.return_value.all.return_value = [use_case1, use_case2]

        def query_side_effect(model):
            if model == UseCase:
                return use_case_query_chain
            return customer_query_chain

        db.query.side_effect = query_side_effect

        # Mock the config service + AI client: the model refines
        # recommendations; the numeric axes come from the data.
        model_text = '{"recommendations": ["R1", "R2", "R3"]}'

        with patch("backend.services.projection_service.effective_inference_settings", return_value={}), \
             patch("backend.services.projection_service.AIClient") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.complete = AsyncMock(return_value=model_text)

            projection = await ProjectionService.generate_projection(db, "test")

            # Model was consulted for the text
            assert mock_client.complete.called, "AI client should be called"

            # Data-driven numbers (never the old constant 50/50/0.5)
            # speed.current = avg(75, 80) = 77.5
            # value.current = (80k savings + 180k revenue) / 10k = 26.0
            assert projection["customer_name"] == "test"
            assert "generated_at" in projection
            assert projection["speed"]["current"] == 77.5
            assert projection["value"]["current"] == 26.0
            assert "projected" in projection["speed"]
            assert "projected_30d" not in projection["speed"]
            assert projection["speed"]["projected"] > projection["speed"]["current"]
            assert projection["horizon"] == "30-60d"
            assert projection["horizon_label"] == "30–60 days"
            # confidence = 0.40 + 0.35*1.0 + 0.02 (2 UCs) + 0.05 (impact) = 0.82
            assert projection["confidence"] == 0.82
            assert len(projection["key_factors"]) > 0
            assert projection["recommendations"] == ["R1", "R2", "R3"]
            assert projection["model_used"] is True

    def test_store_projection(self):
        """Test that projection can be stored."""
        db = MagicMock()
        projection = {
            "customer_name": "test",
            "generated_at": datetime.now(UTC).isoformat(),
            "speed": {"current": 50.0, "projected_30d": 60.0, "trajectory": "improving"},
            "value": {"current": 50.0, "projected_30d": 60.0, "trajectory": "improving"},
            "key_factors": [],
            "recommendations": [],
            "confidence": 0.5,
        }

        result = ProjectionService.store_projection(db, projection)
        assert result is True

    def test_clear_projection(self):
        """Test that projection can be cleared."""
        db = MagicMock()

        result = ProjectionService.clear_projection(db, "test")
        assert result is True


class TestProjectionDeleteAuthorization:
    """DELETE is restricted to global admins and the customer's owner."""

    @pytest.fixture(autouse=True)
    def _seed(self, db_session):
        customer = Customer(name="delete-auth-customer", description="Test")
        db_session.add(customer)
        db_session.flush()

        for username, role in (("projection_owner", "owner"),
                               ("projection_member", "member"),
                               ("projection_auditor", "auditor"),
                               ("projection_outsider", None)):
            user = User(
                username=username,
                email=f"{username}@test.local",
                hashed_password=_FAKE_BCRYPT_HASH,
                display_name=username,
                department="IT",
                is_admin=0,
                approved=1,
                is_active=1,
            )
            db_session.add(user)
            db_session.flush()
            if role:
                db_session.add(CustomerUser(
                    customer_id=customer.id, user_id=user.id, role=role,
                ))

        db_session.add(Projection(
            customer_id=customer.id,
            customer_name=customer.name,
            projection_data={"customer_name": customer.name},
            status="completed",
        ))
        db_session.commit()
        self.customer_name = customer.name

    @pytest.mark.parametrize("username", ["admin", "projection_owner"])
    def test_admin_or_owner_can_delete(self, client, username):
        response = client.delete(
            f"/api/customers/{self.customer_name}/projections/",
            headers=_token(username),
        )
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "username", ["projection_member", "projection_auditor", "projection_outsider"]
    )
    def test_non_owner_is_404_first(self, client, username):
        # clearing needs owner/admin on the customer — member, auditor
        # and outsider are all out of scope for that surface, so they get the
        # same 404 as a missing customer (no existence oracle).
        response = client.delete(
            f"/api/customers/{self.customer_name}/projections/",
            headers=_token(username),
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "Customer not found"

    def test_unauthenticated_is_rejected(self, client):
        response = client.delete(f"/api/customers/{self.customer_name}/projections/")
        assert response.status_code == 401


class TestProjectionTypes:
    """Test that projection types are correctly structured."""

    def test_projection_structure(self):
        """Test that a projection has all required fields."""
        projection = {
            "customer_name": "test",
            "generated_at": datetime.now(UTC).isoformat(),
            "horizon": "30-60d",
            "horizon_label": "30–60 days",
            "speed": {
                "current": 50.0,
                "projected": 60.0,
                "trajectory": "improving",
            },
            "value": {
                "current": 50.0,
                "projected": 60.0,
                "trajectory": "improving",
            },
            "key_factors": ["factor1"],
            "recommendations": ["recommendation1"],
            "confidence": 0.5,
        }

        # Verify structure
        assert "customer_name" in projection
        assert "generated_at" in projection
        assert "horizon" in projection
        assert "horizon_label" in projection
        assert "speed" in projection
        assert "value" in projection
        assert "key_factors" in projection
        assert "recommendations" in projection
        assert "confidence" in projection

        # Verify axis structure (v2 contract: "projected", not "projected_30d")
        assert "current" in projection["speed"]
        assert "projected" in projection["speed"]
        assert "trajectory" in projection["speed"]

        assert "current" in projection["value"]
        assert "projected" in projection["value"]
        assert "trajectory" in projection["value"]

        # Verify values
        assert 0 <= projection["speed"]["current"] <= 100
        assert 0 <= projection["confidence"] <= 1
        assert projection["speed"]["trajectory"] in ["improving", "stable", "declining"]
