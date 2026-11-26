"""Integrations honor persisted DB values.

The UI persists integration credentials through the admin-config API
(categories ``integration_<platform>`` in system_config). The send and
status routes must honor those stored values — DB overrides .env, and
.env remains the fallback (same layering as effective_inference_settings).
The HTTP layer is mocked (no network); persistence uses the real
admin-config routes — the exact path the UI takes.

Run: pytest tests/backend/test_integrations_effective_settings.py -v
"""

from unittest.mock import patch

import pytest

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

_ENV_KEYS = ("SLACK_WEBHOOK_URL", "TEAMS_WEBHOOK_URL", "JIRA_URL",
             "JIRA_API_KEY", "JIRA_PROJECT_KEY")

STORED_SLACK = "https://hooks.slack.example/stored-webhook"
STORED_TEAMS = "https://outlook.office.example/stored-webhook"
STORED_JIRA_URL = "https://jira.example.com"
STORED_JIRA_KEY = "stored-jira-key"
STORED_JIRA_PROJECT = "STOR"
ENV_SLACK = "https://hooks.slack.example/env-webhook"


class _FakeAsyncClient:
    """httpx.AsyncClient stand-in: records POSTed URLs, canned response.

    No network. ``status_code``/``response_json`` are configurable per
    test (Jira success needs 201 + a body with ``key``).
    """
    status_code = 200
    response_json = {"key": "FAKE-1"}
    posted_urls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        type(self).posted_urls.append(url)

        class _Resp:
            def __init__(self):
                self.status_code = _FakeAsyncClient.status_code
                self.text = "ok"

            def json(self):
                return _FakeAsyncClient.response_json

        return _Resp()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Known-empty integration env for every test (auto-restored)."""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Route-level auth: point the real JWT user lookup at the shared
    session (test_integration.py pattern)."""
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
def auth(db_session):
    """Authorization header for the seeded admin user."""
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    return {
        "Authorization":
            f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"
    }


def _store_slack(client, headers, url=STORED_SLACK):
    r = client.put("/api/admin/config/integration/slack",
                   json={"webhook_url": url}, headers=headers)
    assert r.status_code == 200


def _store_teams(client, headers, url=STORED_TEAMS):
    r = client.put("/api/admin/config/integration/teams",
                   json={"webhook_url": url}, headers=headers)
    assert r.status_code == 200


def _store_jira(client, headers):
    r = client.put("/api/admin/config/integration/jira",
                   json={"url": STORED_JIRA_URL, "api_key": STORED_JIRA_KEY,
                         "project_key": STORED_JIRA_PROJECT},
                   headers=headers)
    assert r.status_code == 200


class TestStoredValuesHonored:
    """Persisted (admin-config) credentials drive status + send."""

    def test_status_reflects_stored_slack(self, client, db_session, auth):
        _store_slack(client, auth)
        r = client.get("/api/integrations/status/", headers=auth)
        assert r.status_code == 200
        assert r.json()["slack"] is True
        assert r.json()["teams"] is False
        assert r.json()["jira"] is False

    def test_send_uses_stored_slack_url(self, client, db_session, auth):
        _store_slack(client, auth)
        _FakeAsyncClient.posted_urls.clear()
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            r = client.post("/api/integrations/slack/send/",
                            json={"message": "WP2 stored test"}, headers=auth)
        assert r.status_code == 200
        assert r.json() == {"success": True}
        assert _FakeAsyncClient.posted_urls == [STORED_SLACK]

    def test_status_reflects_stored_teams(self, client, db_session, auth):
        _store_teams(client, auth)
        r = client.get("/api/integrations/status/", headers=auth)
        assert r.json()["teams"] is True

    def test_send_uses_stored_teams_url(self, client, db_session, auth):
        _store_teams(client, auth)
        _FakeAsyncClient.posted_urls.clear()
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            r = client.post("/api/integrations/teams/send/",
                            json={"message": "WP2 stored test"}, headers=auth)
        assert r.status_code == 200
        assert _FakeAsyncClient.posted_urls == [STORED_TEAMS]

    def test_status_reflects_stored_jira(self, client, db_session, auth):
        _store_jira(client, auth)
        r = client.get("/api/integrations/status/", headers=auth)
        assert r.json()["jira"] is True

    def test_send_uses_stored_jira_creds_and_project(self, client, db_session, auth):
        """url/api_key from the stored entries; project_key falls back to
        the stored value when the request omits it."""
        _store_jira(client, auth)
        _FakeAsyncClient.posted_urls.clear()
        _FakeAsyncClient.status_code = 201
        _FakeAsyncClient.response_json = {"key": "FAKE-1"}
        try:
            with patch("httpx.AsyncClient", _FakeAsyncClient):
                r = client.post("/api/integrations/jira/create-ticket/",
                                json={"summary": "S", "description": "D"},
                                headers=auth)
        finally:
            _FakeAsyncClient.status_code = 200
            _FakeAsyncClient.response_json = {"key": "FAKE-1"}
        assert r.status_code == 200
        assert r.json()["key"] == "FAKE-1"
        assert _FakeAsyncClient.posted_urls == [
            f"{STORED_JIRA_URL}/rest/api/2/issue"]


class TestEnvFallback:
    """.env remains the fallback when nothing is stored (or it was cleared)."""

    def test_env_used_when_nothing_stored(self, client, db_session, auth, monkeypatch):
        monkeypatch.setenv("SLACK_WEBHOOK_URL", ENV_SLACK)
        r = client.get("/api/integrations/status/", headers=auth)
        assert r.json()["slack"] is True
        _FakeAsyncClient.posted_urls.clear()
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            r = client.post("/api/integrations/slack/send/",
                            json={"message": "m"}, headers=auth)
        assert r.status_code == 200
        assert _FakeAsyncClient.posted_urls == [ENV_SLACK]

    def test_stored_overrides_env(self, client, db_session, auth, monkeypatch):
        """DB wins over .env (the core P0-6 contract)."""
        _store_slack(client, auth)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", ENV_SLACK)
        _FakeAsyncClient.posted_urls.clear()
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            r = client.post("/api/integrations/slack/send/",
                            json={"message": "m"}, headers=auth)
        assert r.status_code == 200
        assert _FakeAsyncClient.posted_urls == [STORED_SLACK]

    def test_soft_deleted_entry_falls_back_to_env(self, client, db_session,
                                                  auth, monkeypatch):
        """The UI's 'clear field' path soft-deletes the entry (is_active=0);
        the .env value must take over, and status must follow it."""
        _store_slack(client, auth)
        monkeypatch.setenv("SLACK_WEBHOOK_URL", ENV_SLACK)
        r = client.delete("/api/admin/config/category/integration_slack/webhook_url",
                          headers=auth)
        assert r.status_code == 204
        r = client.get("/api/integrations/status/", headers=auth)
        assert r.json()["slack"] is True  # via .env now
        _FakeAsyncClient.posted_urls.clear()
        with patch("httpx.AsyncClient", _FakeAsyncClient):
            r = client.post("/api/integrations/slack/send/",
                            json={"message": "m"}, headers=auth)
        assert r.status_code == 200
        assert _FakeAsyncClient.posted_urls == [ENV_SLACK]


class TestNothingConfigured:
    """No stored values and no .env: status false, sends 400."""

    def test_status_all_false(self, client, db_session, auth):
        r = client.get("/api/integrations/status/", headers=auth)
        assert r.json() == {"slack": False, "teams": False, "jira": False}

    def test_slack_send_400(self, client, db_session, auth):
        r = client.post("/api/integrations/slack/send/",
                        json={"message": "m"}, headers=auth)
        assert r.status_code == 400
        assert "not configured" in r.json()["detail"]

    def test_teams_send_400(self, client, db_session, auth):
        r = client.post("/api/integrations/teams/send/",
                        json={"message": "m"}, headers=auth)
        assert r.status_code == 400
        assert "not configured" in r.json()["detail"]

    def test_jira_send_400(self, client, db_session, auth):
        r = client.post("/api/integrations/jira/create-ticket/",
                        json={"summary": "S", "description": "D"}, headers=auth)
        assert r.status_code == 400
        assert "not configured" in r.json()["detail"]


@pytest.mark.parametrize(
    "path,payload,method,error_detail",
    [
        ("/api/integrations/slack/send/", {"message": "hello"},
         "send_slack_notification", "Slack request failed"),
        ("/api/integrations/teams/send/", {"message": "hello"},
         "send_teams_notification", "Teams request failed"),
        ("/api/integrations/jira/create-ticket/", {"summary": "S", "description": "D"},
         "create_jira_ticket", "Jira request failed"),
    ],
)
def test_sends_require_admin_and_redact_errors(client, db_session, auth, path, payload,
                                               method, error_detail):
    from backend.auth import create_access_token
    from backend.models.use_case import User
    from backend.services.integration_service import IntegrationService

    user = User(username="integration_regular", email="integration@test.local",
                hashed_password=_FAKE_BCRYPT_HASH, is_admin=0, approved=1, is_active=1)
    db_session.add(user)
    db_session.commit()
    regular = {"Authorization": f"Bearer {create_access_token({'sub': user.username})}"}
    settings = {"slack_webhook_url": STORED_SLACK, "teams_webhook_url": STORED_TEAMS,
                "jira_url": STORED_JIRA_URL, "jira_api_key": STORED_JIRA_KEY,
                "jira_project_key": STORED_JIRA_PROJECT}
    with patch.object(IntegrationService, "get_effective_integration_settings", return_value=settings), \
         patch.object(IntegrationService, method, return_value={"success": True}) as send:
        response = client.post(path, json=payload, headers=regular)
        assert response.status_code == 403
        assert response.json()["detail"] == "Admin privileges required"
        send.assert_not_called()
        response = client.post(path, json=payload, headers=auth)
        assert response.status_code == 200
        send.assert_called_once()
        send.return_value = {"success": False, "error": "sensitive upstream detail"}
        response = client.post(path, json=payload, headers=auth)
        assert response.status_code == 500
        assert response.json()["detail"] == error_detail
