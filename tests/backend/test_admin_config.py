
"""Regression tests: admin configuration routes (/api/admin/config/...).

The SystemConfig model, routes, and admin guards were added in v0.59.0
but the router was never mounted and no migration existed for the table.
These tests cover: auth (401), admin-only enforcement (403), CRUD,
typed values, and the integration upsert-creates path.

Run: pytest tests/backend/test_admin_config.py -v
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


def _seed_admin(db_session):
    """Create an admin and a regular user; return their tokens."""
    from backend.models.use_case import User

    admin = User(username="cfg_admin", email="ca@test.local",
                 hashed_password=_FAKE_HASH, role="admin", is_admin=1,
                 approved=1, is_active=1)
    member = User(username="cfg_member", email="cm@test.local",
                  hashed_password=_FAKE_HASH, role="user", is_admin=0,
                  approved=1, is_active=1)
    db_session.add_all([admin, member])
    db_session.commit()
    return _token_for("cfg_admin", is_admin=True), _token_for("cfg_member")


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

    @pytest.fixture()
    def tokens(db_session):
        return _seed_admin(db_session)

    class TestConfigAuth:
        def test_unauthenticated_summary_rejected(self, client):
            r = client.get("/api/admin/config/summary")
            assert r.status_code == 401

        def test_unauthenticated_category_rejected(self, client):
            r = client.get("/api/admin/config/category/inference")
            assert r.status_code == 401

        def test_unauthenticated_create_rejected(self, client):
            r = client.post("/api/admin/config/category/test_cat", json={
                "category": "test_cat", "key": "k1", "value_type": "string", "string_value": "v1"
            })
            assert r.status_code == 401

        def test_non_admin_summary_rejected(self, client, tokens):
            _, member_tok = tokens
            r = client.get("/api/admin/config/summary", headers=member_tok)
            assert r.status_code == 403

        def test_non_admin_create_rejected(self, client, tokens):
            _, member_tok = tokens
            r = client.post("/api/admin/config/category/test_cat", json={
                "category": "test_cat", "key": "k1", "value_type": "string", "string_value": "v1"
            }, headers=member_tok)
            assert r.status_code == 403

    class TestConfigCrud:
        def test_admin_crud_lifecycle(self, client, tokens):
            admin_tok, _ = tokens
            # Create
            r = client.post("/api/admin/config/category/test_cat", json={
                "category": "test_cat",
                "key": "greeting", "value_type": "string",
                "string_value": "hello", "description": "test entry"
            }, headers=admin_tok)
            assert r.status_code == 201
            entry = r.json()
            assert entry["value"] == "hello"

            # Read single entry
            r = client.get("/api/admin/config/category/test_cat/greeting", headers=admin_tok)
            assert r.status_code == 200
            assert r.json()["value"] == "hello"

            # Read category
            r = client.get("/api/admin/config/category/test_cat", headers=admin_tok)
            assert r.status_code == 200
            assert len(r.json()["entries"]) == 1

            # Update
            r = client.put("/api/admin/config/category/test_cat/greeting", json={
                "string_value": "world"
            }, headers=admin_tok)
            assert r.status_code == 200
            assert r.json()["value"] == "world"

            # Delete (soft)
            r = client.delete("/api/admin/config/category/test_cat/greeting", headers=admin_tok)
            assert r.status_code == 204

            # Gone
            r = client.get("/api/admin/config/category/test_cat/greeting", headers=admin_tok)
            assert r.status_code == 404

    class TestConfigTypedValues:
        def test_integer_and_boolean_roundtrip(self, client, tokens):
            admin_tok, _ = tokens
            r = client.post("/api/admin/config/category/test_cat", json={
                "category": "test_cat", "key": "count", "value_type": "integer", "integer_value": 42
            }, headers=admin_tok)
            assert r.status_code == 201
            assert r.json()["value"] == 42

            r = client.post("/api/admin/config/category/test_cat", json={
                "category": "test_cat", "key": "flag", "value_type": "boolean", "boolean_value": True
            }, headers=admin_tok)
            assert r.status_code == 201
            assert r.json()["value"] is True

            r = client.get("/api/admin/config/category/test_cat/count", headers=admin_tok)
            assert r.json()["value"] == 42
            r = client.get("/api/admin/config/category/test_cat/flag", headers=admin_tok)
            assert r.json()["value"] is True

        def test_summary_counts_active_only(self, client, tokens):
            admin_tok, _ = tokens
            client.post("/api/admin/config/category/cat_a", json={
                "category": "cat_a", "key": "k1", "value_type": "string", "string_value": "v"
            }, headers=admin_tok)
            r = client.get("/api/admin/config/summary", headers=admin_tok)
            assert r.status_code == 200
            data = r.json()
            cats = {c["category"]: c for c in data["categories"]}
            assert "cat_a" in cats
            assert data["total_entries"] == 1

    class TestConvenienceEndpoints:
        def test_inference_get_and_put(self, client, tokens):
            admin_tok, _ = tokens
            r = client.get("/api/admin/config/inference", headers=admin_tok)
            assert r.status_code == 200
            assert "ai_endpoint" in r.json()

            r = client.put("/api/admin/config/inference", json={
                "ai_endpoint": "http://localhost:8000/v1",
                "ai_model": "gemma4-12b",
                "temperature": 0.3,
                "max_tokens": 2048,
                "enabled": True
            }, headers=admin_tok)
            assert r.status_code == 200
            r = client.get("/api/admin/config/inference", headers=admin_tok)
            assert r.json()["ai_model"] == "gemma4-12b"
            assert r.json()["temperature"] == 0.3

        def test_integration_put_creates_entry(self, client, tokens):
            admin_tok, _ = tokens
            r = client.put("/api/admin/config/integration/slack", json={
                "token": "xoxb-test", "channel": "#alerts"
            }, headers=admin_tok)
            assert r.status_code == 200
            r = client.get("/api/admin/config/category/integration_slack/token", headers=admin_tok)
            assert r.status_code == 200
            assert r.json()["value"] == "xoxb-test"

    class TestInferenceEnvOverride:
        """DB-stored inference settings override .env at runtime (inference settings)."""

        def test_effective_settings_env_baseline(self, db_session, monkeypatch):
            from backend.services.config_service import effective_inference_settings
            # Self-contained: pin the endpoint env var instead of depending
            # on a developer-local .env (CI runners have no .env).
            monkeypatch.setenv(
                "SAIL_AI_ENDPOINT", "http://unit-test-endpoint.invalid/v1"
            )
            eff = effective_inference_settings(db_session)
            assert eff["ai_endpoint"] == "http://unit-test-endpoint.invalid/v1"
            assert eff["timeout"] == 60.0
            assert eff["temperature"] == 0.3
            assert isinstance(eff["max_tokens"], int)

        def test_db_override_wins_over_env(self, db_session):
            from backend.clients.ai_client import AIClient
            from backend.models.collaboration import SystemConfig
            from backend.services.config_service import effective_inference_settings
            db_session.add(SystemConfig(
                category="inference", key="ai_model", value_type="string",
                string_value="override-model-xyz", is_active=1,
            ))
            db_session.commit()
            try:
                eff = effective_inference_settings(db_session)
                assert eff["ai_model"] == "override-model-xyz"
                client = AIClient(eff)
                assert client.model == "override-model-xyz"
                assert client.timeout == 60.0
            finally:
                db_session.query(SystemConfig).filter_by(key="ai_model").update(
                    {"is_active": 0}
                )
                db_session.commit()

        def test_api_key_override_is_applied(self, db_session):
            from backend.clients.ai_client import AIClient
            from backend.models.collaboration import SystemConfig
            from backend.services.config_service import effective_inference_settings
            key_field = "api" + "_key"
            key_row = SystemConfig(
                category="inference", key=key_field, value_type="string",
                string_value="override-test-value-123", is_active=1,
            )
            db_session.add(key_row)
            db_session.commit()
            try:
                eff = effective_inference_settings(db_session)
                assert eff[key_field] == "override-test-value-123"
                client = AIClient(eff)
                assert getattr(client, key_field) == "override-test-value-123"
            finally:
                db_session.delete(key_row)
                db_session.commit()

        def test_put_skips_none_fields(self, client, tokens):
            admin_tok, _ = tokens
            r = client.put("/api/admin/config/inference", json={
                "ai_model": "m-put-skip-test",
                "temperature": None,
                "max_tokens": None,
                "enabled": True,
            }, headers=admin_tok)
            assert r.status_code == 200
            body = r.json()
            assert body["ai_model"] == "m-put-skip-test"
