"""Tests for the auth provider seam (0.2.0 P0, docs/archive/PLAN_LDAP_AD_AUTH.md §3.2).

Regression gate for the local (bcrypt) login path behind ``LocalBackend``.

The seam must stay behavior-identical to the pre-seam ``routes/auth.py``
login: ``get_by_username`` + ``verify_password``. Crucially, ``LocalBackend``
resolves ``verify_password`` as an attribute on ``backend.auth`` AT CALL TIME
(not an import-bound symbol) so the established test doubles — which patch
``backend.auth.verify_password`` with a deterministic fake, exactly like
``test_auth.py`` and ``test_user_management.py`` — take effect. If a future
refactor rebinds ``verify_password`` at import, these tests fail (real bcrypt
would run against the known fake hash and return False).
"""


import backend.auth
from backend.models.use_case import User
from backend.services.auth_provider import (
    LocalBackend,
    resolve_auth_backend,
)

# The shared test DB (conftest) replaces hash_password with a constant fake
# hash, so real bcrypt can never verify. Follow the established pattern: a
# verify_password double that accepts any password against the known fake hash,
# applied directly to the module dict so it persists for the module's life.
_FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _mock_verify_password(plain_password: str, hashed_password: str) -> bool:
    return hashed_password == _FAKE_HASH


backend.auth.verify_password = _mock_verify_password


def _make_user(db_session, username: str, hashed_password: str | None = _FAKE_HASH) -> User:
    user = User(
        username=username,
        email=f"{username}@test.local",
        hashed_password=hashed_password,
        display_name=username.title(),
        is_active=1,
        approved=1,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class TestLocalBackend:
    """LocalBackend.authenticate preserves the pre-seam bcrypt path."""

    def test_authenticate_success_returns_user(self, db_session):
        _make_user(db_session, "seamluser")
        result = LocalBackend().authenticate(db_session, "seamluser", "any-password")
        assert result is not None
        assert result.username == "seamluser"

    def test_authenticate_unknown_user_returns_none(self, db_session):
        result = LocalBackend().authenticate(db_session, "ghost", "any-password")
        assert result is None

    def test_authenticate_wrong_password_returns_none(self, db_session):
        # A user whose hash is NOT the known fake hash — the double rejects it.
        _make_user(db_session, "seamlbad", hashed_password="$2b$12$not-the-fake-hash")
        result = LocalBackend().authenticate(db_session, "seamlbad", "any-password")
        assert result is None

    def test_authenticate_null_hash_returns_none(self, db_session):
        # Directory-managed rows carry no local hash (hashed_password is
        # nullable post-P0). Local login must treat NULL as a failure, never
        # an error — and must not crash on the None check.
        _make_user(db_session, "seamldap", hashed_password=None)
        result = LocalBackend().authenticate(db_session, "seamldap", "any-password")
        assert result is None


class TestResolveAuthBackend:
    """P0: provider resolution is local-only."""

    def test_returns_local_backend(self, db_session):
        backend = resolve_auth_backend(db_session, "admin")
        assert isinstance(backend, LocalBackend)
        assert backend.name == "local"

    def test_local_backend_name_is_local(self):
        assert LocalBackend.name == "local"
