"""Tests for inference settings persistence (Application Settings page).

Regression coverage for the field-contract fix (2026-08-24):

The Application Settings inference form previously read the effective
config under ``c.base_url`` / ``c.model`` (fields the API never returns)
and saved under ``base_url`` / ``model`` (fields the ``InferenceConfig``
schema does not declare — Pydantic dropped them silently). The form
therefore always rendered empty and the API endpoint / model the user
typed were never persisted; only temperature / max_tokens / timeout
round-tripped. These tests pin the real contract:

- ``PUT /api/admin/config/inference`` persists ``ai_endpoint`` and
  ``ai_model`` (and the numeric fields) — verified by a fresh GET and by
  the stored system_config entries;
- empty strings are not persisted (the override layer treats empty as
  "fall back to the .env default", so storing them would be a silent
  no-op at runtime);
- partial updates preserve previously saved overrides;
- admin-only guard (401 anonymous / 403 non-admin);
- the AIClient maps the effective-settings override keys onto the
  request it sends (endpoint/model/temperature/max_tokens/timeout).

Run: pytest tests/backend/test_inference_config_save.py -v
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

_INFERENCE_KEYS = ("ai_endpoint", "ai_model", "api_key",
                   "temperature", "max_tokens", "timeout", "enabled")



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Point the real JWT user lookup at the shared session (same pattern
    as test_export.py)."""
    from backend.models.use_case import User

    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    if not db_session.query(User).count():
        db_session.add(User(username="admin", email="admin@test.local",
                            hashed_password=_FAKE_BCRYPT_HASH,
                            display_name="Administrator", department="IT",
                            is_admin=1, approved=1, is_active=1))
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
        return shared_engine

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", _shared_engine):
        yield


@pytest.fixture()
def admin_auth(db_session):
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    token = create_access_token({"sub": admin.username, "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _cleanup_inference_config(client, admin_auth):
    """Soft-delete any inference overrides the tests created so later
    files (including the real-inference scoring tests) see a clean
    effective config."""
    yield
    for key in _INFERENCE_KEYS:
        client.delete(f"/api/admin/config/category/inference/{key}",
                      headers=admin_auth)


class TestInferenceConfigSave:
    def test_put_persists_endpoint_model_and_numbers(self, client, admin_auth):
        r = client.put("/api/admin/config/inference", json={
            "ai_endpoint": "http://override-host:11434/v1",
            "ai_model": "override-model-x",
            "temperature": 0.55,
            "max_tokens": 900,
            "timeout": 90,
            "enabled": True,
        }, headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        assert body["ai_endpoint"] == "http://override-host:11434/v1"
        assert body["ai_model"] == "override-model-x"
        assert body["temperature"] == 0.55
        assert body["max_tokens"] == 900
        assert body["timeout"] == 90

        # Fresh GET proves persistence beyond the PUT response.
        r2 = client.get("/api/admin/config/inference", headers=admin_auth)
        assert r2.status_code == 200
        assert r2.json()["ai_endpoint"] == "http://override-host:11434/v1"
        assert r2.json()["ai_model"] == "override-model-x"

        # Stored system_config entries reflect the same values.
        r3 = client.get("/api/admin/config/category/inference", headers=admin_auth)
        assert r3.status_code == 200
        entries = {e["key"]: e["value"] for e in r3.json()["entries"]}
        assert entries["ai_endpoint"] == "http://override-host:11434/v1"
        assert entries["ai_model"] == "override-model-x"
        assert entries["temperature"] == 0.55

    def test_put_empty_strings_not_persisted(self, client, admin_auth):
        r = client.put("/api/admin/config/inference", json={
            "ai_endpoint": "",
            "ai_model": "",
            "temperature": 0.4,
        }, headers=admin_auth)
        assert r.status_code == 200

        r3 = client.get("/api/admin/config/category/inference", headers=admin_auth)
        entries = {e["key"] for e in r3.json()["entries"]}
        assert "ai_endpoint" not in entries
        assert "ai_model" not in entries
        assert "temperature" in entries

        # Effective settings: endpoint/model fall back to the .env
        # defaults; the numeric override is live.
        from backend.config import get_settings
        r4 = client.get("/api/admin/config/inference", headers=admin_auth)
        eff = r4.json()
        assert eff["ai_endpoint"] == (get_settings().ai_endpoint or "")
        assert eff["ai_model"] == get_settings().ai_model
        assert eff["temperature"] == 0.4

    def test_partial_update_preserves_other_overrides(self, client, admin_auth):
        r1 = client.put("/api/admin/config/inference", json={
            "temperature": 0.1,
            "max_tokens": 500,
        }, headers=admin_auth)
        assert r1.status_code == 200

        # Second save without the endpoint/model keys (empty -> skipped):
        # previously saved numeric overrides must survive.
        r2 = client.put("/api/admin/config/inference", json={
            "ai_model": "m-two",
            "temperature": None,
        }, headers=admin_auth)
        assert r2.status_code == 200

        r3 = client.get("/api/admin/config/inference", headers=admin_auth)
        eff = r3.json()
        assert eff["ai_model"] == "m-two"
        assert eff["temperature"] == 0.1
        assert eff["max_tokens"] == 500

    def test_requires_admin(self, client, admin_auth, db_session):
        # Anonymous -> 401
        r = client.put("/api/admin/config/inference", json={"temperature": 0.2})
        assert r.status_code == 401

        # Non-admin -> 403
        from backend.auth import create_access_token
        from backend.models.use_case import User
        member = (
            db_session.query(User)
            .filter(User.username == "inference_nonadmin")
            .first()
        )
        if not member:
            member = User(username="inference_nonadmin",
                          email="inference_nonadmin@test.local",
                          hashed_password=_FAKE_BCRYPT_HASH,
                          display_name="Member", department="IT",
                          is_admin=0, role="member", approved=1, is_active=1)
            db_session.add(member)
            db_session.commit()
        token = create_access_token({"sub": "inference_nonadmin", "is_admin": False})
        r = client.put("/api/admin/config/inference",
                       json={"temperature": 0.2},
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 403

    def test_get_returns_effective_contract_shape(self, client, admin_auth):
        """Pin the API contract the Application Settings form consumes:
        the response carries ai_endpoint / ai_model (not base_url/model)."""
        r = client.get("/api/admin/config/inference", headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        for field in ("ai_endpoint", "ai_model", "temperature",
                      "max_tokens", "timeout", "enabled"):
            assert field in body
        assert "base_url" not in body
        assert "model" not in body


class TestAIClientOverrideMapping:
    def test_client_maps_effective_overrides(self):
        from backend.clients.ai_client import AIClient

        client = AIClient({
            "ai_endpoint": "http://override/v1",
            "ai_model": "override-model",
            "api_key": "***",
            "temperature": 0.2,
            "max_tokens": 111,
            "timeout": 45.0,
        })
        assert client.base_url == "http://override/v1"
        assert client.model == "override-model"
        assert client.api_key == "***"
        assert client.temperature == 0.2
        assert client.max_tokens == 111
        assert client.timeout == 45.0

    def test_client_falls_back_to_settings_without_overrides(self):
        from backend.clients.ai_client import AIClient
        from backend.config import get_settings

        client = AIClient({})
        # no overrides -> raw .env/Settings values (test env may load .env)
        assert client.model == (get_settings().ai_model or "gemma4-12b")
        assert client.temperature == 0.3
        assert client.max_tokens == 2000
        assert client.timeout == 60.0
