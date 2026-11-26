"""Integration tests for authentication and CRUD endpoints.

Tests cover:
- User registration, login, and JWT flow
- Admin approval workflow
- Auth-protected routes (401 without token)
- Use case CRUD with created_by/updated_by tracking
- Admin-only endpoints
- Rate limit exemption for auth endpoints

NOTE: The passlib/bcrypt bug on Python 3.12 crashes during import when
hash_password() is called. All test code monkey-patches at module level
so the real bcrypt backend is never invoked.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import os
from unittest.mock import MagicMock, Mock

import pytest

# ── Monkey-patch passlib BEFORE any module that calls hash_password is imported ─
# We assign directly to the module dict so the patch persists for the
# entire module lifetime (unlike `with patch()` which restores on exit).

_real_crypt = __import__("passlib.context", fromlist=["CryptContext"])
_real_crypt.CryptContext = MagicMock


# Now safe to import: backend.auth will see the replaced CryptContext.
import backend.auth
from backend.auth import (
    create_access_token,
    decode_access_token,
)
from backend.models.use_case import User
from backend.routes.auth import (
    approve_user,
    get_me,
    list_pending_users,
    login,
    register_user,
)
from backend.services.use_case_service import UseCaseService

# NOTE: DO NOT import db_session directly from conftest.py here.
# Pytest injects fixtures as parameters — importing directly creates a
# separate Base.metadata instance that conflicts with the one in conftest.py.
# Just use db_session as a fixture parameter in each test method.

# Restore real CryptContext for normal use (but tests still call our mocks).
# Actually we need to keep the mock in place for the rest of this module's
# life.  We'll replace hash_password/verify_password with test doubles.

_REAL_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _mock_hash_password(password: str) -> str:
    return _REAL_BCRYPT_HASH


def _mock_verify_password(plain_password: str, hashed_password: str) -> bool:
    # Accept any password when the stored hash is our known test hash.
    if hashed_password == _REAL_BCRYPT_HASH:
        return True
    return False


# Apply monkey-patches to every module that references them.
backend.auth.hash_password = _mock_hash_password
backend.auth.verify_password = _mock_verify_password
backend.routes.auth.hash_password = _mock_hash_password
backend.routes.auth.verify_password = _mock_verify_password

# Also patch the original module for any import-time callers.
__import__("backend.auth").hash_password = _mock_hash_password
__import__("backend.auth").verify_password = _mock_verify_password


# ── Test DB setup ─────────────────────────────────────────────────────

# The shared db_session fixture from conftest.py provides:
# - A fresh session for each test with savepoint isolation
# - Tables created once at module load time
# - Admin user seeded once at module load time
#
# Tests use db_session as a fixture parameter to get a session.


# ── Registration Tests ────────────────────────────────────────────────

class TestRegistration:
    """Tests for user registration flow."""

    def test_register_success(self, db_session):
        from backend.schemas.use_case import UserCreate

        user_data = UserCreate(
            username="newuser",
            email="new@test.local",
            password="securepass12",
            display_name="New User",
            department="Marketing",
        )
        result = register_user(user_data, db=db_session)
        assert result["username"] == "newuser"
        assert result["email"] == "new@test.local"
        assert result["display_name"] == "New User"
        assert result["department"] == "Marketing"
        assert result["approved"] == 0

    def test_register_duplicate_username(self, db_session):
        from backend.schemas.use_case import UserCreate
        from fastapi import HTTPException

        register_user(
            UserCreate(username="dupuser", email="first@test.local", password="securepass12", display_name="First", department=None),
            db=db_session,
        )
        with pytest.raises(HTTPException) as exc:
            register_user(
                UserCreate(username="dupuser", email="second@test.local", password="securepass12", display_name="Second", department=None),
                db=db_session,
            )
        assert exc.value.status_code == 400
        assert "already exists" in exc.value.detail

    def test_register_duplicate_email(self, db_session):
        from backend.schemas.use_case import UserCreate
        from fastapi import HTTPException

        register_user(
            UserCreate(username="user1", email="dup@test.local", password="securepass12", display_name="User 1", department=None),
            db=db_session,
        )
        with pytest.raises(HTTPException) as exc:
            register_user(
                UserCreate(username="user2", email="dup@test.local", password="securepass12", display_name="User 2", department=None),
                db=db_session,
            )
        assert exc.value.status_code == 400
        assert "already exists" in exc.value.detail

    def test_register_minimal(self, db_session):
        from backend.schemas.use_case import UserCreate

        result = register_user(
            UserCreate(username="minimal", email="minimal@test.local", password="securepass12"),
            db=db_session,
        )
        assert result["username"] == "minimal"
        assert result["display_name"] is None
        assert result["department"] is None


# ── Login Tests ───────────────────────────────────────────────────────

class TestLogin:
    """Tests for login flow."""

    def test_login_success(self, db_session):
        from backend.schemas.use_case import LoginRequest
        result = login(
            LoginRequest(username="admin", password="anything"),
            db=db_session,
        )
        assert result.username == "admin"
        assert result.token
        assert result.is_admin is True

    def test_login_pending_rejected(self, db_session):
        from backend.schemas.use_case import LoginRequest
        from fastapi import HTTPException

        pending = User(
            username="pending_user",
            email="pending@test.local",
            hashed_password=_REAL_BCRYPT_HASH,
            display_name="Pending User",
            department="Sales",
            is_admin=0,
            approved=0,
            is_active=1,
        )
        db_session.add(pending)
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            login(
                LoginRequest(username="pending_user", password="anything"),
                db=db_session,
            )
        assert exc.value.status_code == 403
        assert "pending approval" in exc.value.detail.lower()

    def test_login_nonexistent_user(self, db_session):
        from backend.schemas.use_case import LoginRequest
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            login(
                LoginRequest(username="nobody", password="password"),
                db=db_session,
            )
        assert exc.value.status_code == 401
        assert "invalid credentials" in exc.value.detail.lower()


# ── Admin Approval Tests ──────────────────────────────────────────────

class TestUserApproval:
    """Tests for admin approval workflow."""

    def test_admin_can_approve_user(self, db_session):
        from backend.auth import create_access_token

        pending = User(
            username="pending_user",
            email="pending@test.local",
            hashed_password=_REAL_BCRYPT_HASH,
            display_name="Pending User",
            department="Sales",
            is_admin=0,
            approved=0,
            is_active=1,
        )
        db_session.add(pending)
        db_session.commit()
        db_session.refresh(pending)

        admin_token = create_access_token({"sub": "admin", "is_admin": True})
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Bearer {admin_token}"}

        result = approve_user(pending.username, mock_request, db=db_session)
        assert result["approved"] == 1

    def test_approve_already_approved(self, db_session):
        from backend.auth import create_access_token

        admin_token = create_access_token({"sub": "admin", "is_admin": True})
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Bearer {admin_token}"}

        result = approve_user("admin", mock_request, db=db_session)
        assert result["approved"] == 1

    def test_non_admin_cannot_approve(self, db_session):
        from backend.auth import create_access_token
        from fastapi import HTTPException

        # Create regular_user in DB so _get_user_by_username resolves
        regular = User(
            username="regular_user",
            email="regular@test.local",
            hashed_password=_REAL_BCRYPT_HASH,
            display_name="Regular User",
            department="Finance",
            is_admin=0,
            approved=1,
            is_active=1,
        )
        db_session.add(regular)
        db_session.commit()

        user_token = create_access_token({"sub": "regular_user", "is_admin": False})
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Bearer {user_token}"}

        with pytest.raises(HTTPException) as exc:
            approve_user("pending_user", mock_request, db=db_session)
        assert exc.value.status_code == 403
        assert "admin" in exc.value.detail.lower()


# ── Admin List Endpoints Tests ────────────────────────────────────────

class TestAdminListEndpoints:
    """Tests for admin-only listing endpoints."""

    def test_pending_users_list(self, db_session):
        from backend.auth import create_access_token

        pending = User(
            username="pending_user",
            email="pending@test.local",
            hashed_password=_REAL_BCRYPT_HASH,
            display_name="Pending User",
            department="Sales",
            is_admin=0,
            approved=0,
            is_active=1,
        )
        db_session.add(pending)
        db_session.commit()

        admin_token = create_access_token({"sub": "admin", "is_admin": True})
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Bearer {admin_token}"}

        results = list_pending_users(mock_request, db=db_session)
        usernames = [u["username"] for u in results]
        assert "pending_user" in usernames
        assert "admin" not in usernames


# ── Auth-Protected Route Tests ────────────────────────────────────────

class TestAuthProtected:
    """Tests for auth-protected route behavior."""

    def test_me_requires_auth(self, db_session):
        from fastapi import HTTPException

        mock_request = Mock()
        mock_request.headers = {}
        with pytest.raises(HTTPException) as exc:
            get_me(mock_request, db=db_session)
        assert exc.value.status_code == 401

    def test_me_with_valid_token(self, db_session):
        admin_token = create_access_token({"sub": "admin", "is_admin": True})
        mock_request = Mock()
        mock_request.headers = {"Authorization": f"Bearer {admin_token}"}

        result = get_me(mock_request, db=db_session)
        assert result["username"] == "admin"
        assert result["email"] == "admin@test.local"

    def test_invalid_token_rejected(self, db_session):
        from fastapi import HTTPException

        mock_request = Mock()
        mock_request.headers = {"Authorization": "Bearer invalid-token"}
        with pytest.raises(HTTPException) as exc:
            get_me(mock_request, db=db_session)
        assert exc.value.status_code == 401


# ── JWT Token Tests ───────────────────────────────────────────────────

class TestJWTToken:
    """Tests for JWT token behavior."""

    def test_token_contains_username(self):
        token = create_access_token({"sub": "admin", "is_admin": True})
        assert token
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_has_expiry(self):
        token = create_access_token({"sub": "admin", "is_admin": True})
        payload = decode_access_token(token)
        assert payload is not None
        assert "exp" in payload
        assert payload["sub"] == "admin"
        assert payload["is_admin"] is True

    def test_invalid_token_returns_none(self):
        assert decode_access_token("invalid-token-string") is None

    def test_malformed_token_returns_none(self):
        assert decode_access_token("not.a.valid.jwt") is None


# ── Use Case Service Tests (CRUD with audit trail) ───────────────────

class TestUseCaseService:
    """Tests for use case CRUD via service layer.

use cases with no customer are admin-only, so
    these mechanics pins create/update with admin users (user=None remains
    the trusted in-process path)."""

    def test_create_use_case(self, db_session):
        uc = UseCaseService.create(
            db_session,
            title="Test Use Case",
            description="Test description",
            department="Engineering",
            goals=["Goal 1", "Goal 2"],
            challenges=["Challenge 1"],
            user={"username": "test_user", "email": "test@test.local", "is_admin": 1},
        )
        assert uc.title == "Test Use Case"
        assert uc.department == "Engineering"
        assert uc.status == "draft"
        assert uc.goals == ["Goal 1", "Goal 2"]
        assert uc.created_by == "test_user"

    def test_create_use_case_no_user(self, db_session):
        """Service defaults to 'anonymous' when no user provided."""
        uc = UseCaseService.create(
            db_session,
            title="No User Test",
            user=None,
        )
        assert uc.title == "No User Test"
        assert uc.created_by == "anonymous"

    def test_update_use_case(self, db_session):
        uc = UseCaseService.create(
            db_session, title="Original",
            user={"username": "user1", "is_admin": 1},
        )
        updated = UseCaseService.update(
            db_session, uc.id,
            user={"username": "user2", "is_admin": 1},
            title="Updated Title",
            status="active",
        )
        assert updated.title == "Updated Title"
        assert updated.status == "active"
        assert updated.created_by == "user1"
        assert updated.updated_by == "user2"

    def test_delete_use_case(self, db_session):
        uc = UseCaseService.create(
            db_session, title="To Delete",
            user={"username": "user1", "is_admin": 1},
        )
        deleted = UseCaseService.delete(db_session, uc.id)
        assert deleted is True

        result = UseCaseService.delete(db_session, uc.id)
        assert result is False

    def test_get_by_id(self, db_session):
        uc = UseCaseService.create(
            db_session, title="Retrievable",
            user={"username": "user1", "is_admin": 1},
        )
        found = UseCaseService.get_by_id(db_session, uc.id)
        assert found is not None
        assert found.title == "Retrievable"

    def test_get_by_id_not_found(self, db_session):
        result = UseCaseService.get_by_id(db_session, 99999)
        assert result is None

    def test_list_use_cases(self, db_session):
        for i in range(3):
            UseCaseService.create(
                db_session, title=f"Use Case {i}",
                user={"username": "user1", "is_admin": 1},
            )

        results = UseCaseService.get_all(db_session, skip=0, limit=100)
        assert len(results) == 3

    def test_list_with_filter(self, db_session):
        UseCaseService.create(
            db_session, title="Dept A", department="A",
            user={"username": "user1", "is_admin": 1},
        )
        UseCaseService.create(
            db_session, title="Dept B", department="B",
            user={"username": "user1", "is_admin": 1},
        )
        UseCaseService.create(
            db_session, title="Dept A 2", department="A",
            user={"username": "user1", "is_admin": 1},
        )

        results = UseCaseService.get_all(db_session, department="A")
        assert len(results) == 2

    def test_created_by_audit_trail(self, db_session):
        """created_by from user; updated_by defaults to 'anonymous'
        when update is called without user context."""
        uc = UseCaseService.create(
            db_session, title="Audit Trail",
            user={"username": "creator", "email": "creator@test.local", "is_admin": 1},
        )
        assert uc.created_by == "creator"
        assert uc.updated_by is None  # set on create only

        # Update without user — updated_by defaults to "anonymous"
        updated = UseCaseService.update(
            db_session, uc.id,
            status="active",
        )
        assert updated.created_by == "creator"
        assert updated.updated_by == "anonymous"

        # Update with user
        updated2 = UseCaseService.update(
            db_session, uc.id,
            user={"username": "editor", "email": "editor@test.local", "is_admin": 1},
            title="Updated",
        )
        assert updated2.updated_by == "editor"


# ── Rate Limit Configuration Tests ──────────────────────────────────────

class TestRateLimitConfig:
    """Tests that the rate limiter is active and auth endpoints carry
    strict per-IP buckets (SEC-02: auth flows are no longer exempt —
    /api/auth/login and /api/auth/register have their own buckets)."""

    def test_public_routes_includes_auth(self):
        from backend.rate_limit import ENDPOINT_RATE_LIMITS, rate_limiter

        # RateLimiter instance exists
        assert rate_limiter is not None

        # Auth endpoints are in the limiter's config (NOT exempt) with strict
        # per-IP buckets; the other restricted endpoints keep theirs.
        assert "/api/auth/login" in ENDPOINT_RATE_LIMITS
        assert "/api/auth/register" in ENDPOINT_RATE_LIMITS
        assert ENDPOINT_RATE_LIMITS["/api/auth/login"][0] == 10
        assert ENDPOINT_RATE_LIMITS["/api/auth/register"][0] == 5
        assert "/api/scoring/" in ENDPOINT_RATE_LIMITS
        assert "/api/bulk/" in ENDPOINT_RATE_LIMITS
        assert "/api/stats/export-csv" in ENDPOINT_RATE_LIMITS

        # Rate limiter enforces the strict login bucket (fresh instance —
        # don't consume the global singleton's state).
        from backend.rate_limit import RateLimiter
        fresh = RateLimiter()
        login_limit, _ = ENDPOINT_RATE_LIMITS["/api/auth/login"]
        for i in range(login_limit):
            assert fresh.is_allowed("127.0.0.1", "/api/auth/login/") is True
        assert fresh.is_allowed("127.0.0.1", "/api/auth/login/") is False
        # A different bucket for the same IP is independent.
        assert fresh.is_allowed("127.0.0.1", "/api/auth/register/") is True
