"""Email settings, admin access and deterministic SMTP connection tests."""

import smtplib
from types import SimpleNamespace

import pytest
from backend.auth import create_access_token
from backend.config import Settings
from backend.models.collaboration import SystemConfig
from backend.models.use_case import User
from backend.services import config_service, email_service

URL = "/api/admin/config/email"
SECRET = "smtp-secret-fragment"


class FakeSMTP:
    SMTPException = smtplib.SMTPException
    SMTPAuthenticationError = smtplib.SMTPAuthenticationError

    def __init__(self):
        self.calls = []
        self.messages = []
        self.failure = None

    def SMTP(self, host, port):
        return self.connect("SMTP", host, port)

    def SMTP_SSL(self, host, port):
        return self.connect("SMTP_SSL", host, port)

    def connect(self, mode, host, port):
        self.calls.append((mode, host, port))
        if self.failure == "connection":
            raise OSError(SECRET)
        return self

    def starttls(self):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))
        if self.failure == "auth":
            raise self.SMTPAuthenticationError(535, SECRET.encode())

    def send_message(self, msg):
        if self.failure == "send":
            raise self.SMTPException(SECRET)
        self.messages.append(msg)

    def quit(self):
        self.calls.append("quit")


@pytest.fixture()
def smtp(monkeypatch):
    fake = FakeSMTP()
    monkeypatch.setattr(email_service, "smtplib", fake)
    return fake


@pytest.fixture()
def email_defaults(monkeypatch):
    settings = Settings(_env_file=None, email_enabled=True, email_smtp_host="smtp.example.test",
                        email_smtp_username="mailer", email_smtp_password=SECRET,
                        email_from_address="sail@example.test")
    monkeypatch.setattr(config_service, "get_settings", lambda: settings)
    monkeypatch.setattr(email_service, "get_settings", lambda: settings)
    return settings


@pytest.fixture()
def admin_auth(db_session):
    admin = db_session.query(User).filter(User.is_admin == 1).first()
    token = create_access_token({"sub": admin.username, "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def test_effective_merge(db_session, email_defaults):
    assert config_service.effective_email_settings(None)["smtp_host"] == "smtp.example.test"
    config_service.upsert_config_entry(db_session, "email", "smtp_host", "db.example.test")
    config_service.upsert_config_entry(db_session, "email", "smtp_username", "")
    config_service.upsert_config_entry(db_session, "email", "password_configured", False)
    eff = config_service.effective_email_settings(db_session)
    assert eff["smtp_host"] == "db.example.test"
    assert eff["smtp_username"] == "mailer"
    assert eff["password_configured"] is True
    email_defaults.email_smtp_password = ""
    assert config_service.effective_email_settings(db_session)["password_configured"] is False


@pytest.mark.parametrize("method", ["get", "put", "post"])
def test_admin_only(client, db_session, method):
    path = URL + ("/test" if method == "post" else "")
    kwargs = {"json": {}} if method == "put" else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401
    db_session.add(User(username="email_member", hashed_password="fake", is_admin=0, approved=1, is_active=1))
    db_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token({'sub': 'email_member', 'is_admin': False})}"}
    assert getattr(client, method)(path, headers=headers, **kwargs).status_code == 403


def test_get_put_roundtrip(client, db_session, admin_auth, email_defaults):
    result = client.get(URL, headers=admin_auth)
    assert result.status_code == 200
    assert result.json() == dict(enabled=True, smtp_host="smtp.example.test", smtp_port=587,
                                 smtp_username="mailer", smtp_security="starttls",
                                 from_address="sail@example.test", password_configured=True)
    payload = dict(enabled=True, smtp_host="override.test", smtp_port=465,
                   smtp_username="override", smtp_security="ssl", from_address="from@example.test")
    assert client.put(URL, headers=admin_auth, json=payload).status_code == 200
    assert client.get(URL, headers=admin_auth).json() == {**payload, "password_configured": True}
    assert {r.key for r in db_session.query(SystemConfig).filter_by(category="email")} == set(config_service.EMAIL_KEYS)
    email_defaults.email_smtp_password = ""
    payload.update(smtp_host="", smtp_username="", from_address="", password_configured=True)
    assert client.put(URL, headers=admin_auth, json=payload).status_code == 200
    saved = client.get(URL, headers=admin_auth).json()
    assert saved["smtp_host"] == "override.test"
    assert saved["smtp_username"] == "override"
    assert saved["from_address"] == "from@example.test"
    assert saved["password_configured"] is False
    assert not db_session.query(SystemConfig).filter_by(category="email", key="password_configured").count()


@pytest.mark.parametrize("payload,detail", [
    ({"smtp_port": 0}, "smtp_port must be between 1 and 65535"),
    ({"smtp_port": 65536}, "smtp_port must be between 1 and 65535"),
    ({"smtp_security": "bogus"}, None),
    ({"from_address": "not-an-email"}, "from_address must be a valid email address"),
])
def test_invalid_save_is_atomic(client, db_session, admin_auth, email_defaults, payload, detail):
    result = client.put(URL, headers=admin_auth, json={"smtp_host": "must-not-save", **payload})
    assert result.status_code == 422
    if detail:
        assert result.json()["detail"] == detail
    assert db_session.query(SystemConfig).filter_by(category="email").count() == 0


def test_test_requires_profile_email(client, db_session, admin_auth, email_defaults, smtp):
    db_session.query(User).filter_by(username="admin").update({"email": ""})
    db_session.commit()
    result = client.post(URL + "/test", headers=admin_auth)
    assert result.status_code == 422
    assert result.json()["detail"] == "Your profile has no email address set"
    assert smtp.calls == []


@pytest.mark.parametrize("missing", ["email_enabled", "email_smtp_host", "email_from_address"])
def test_unconfigured_never_connects(client, admin_auth, email_defaults, smtp, missing):
    setattr(email_defaults, missing, False if missing == "email_enabled" else " ")
    assert client.post(URL + "/test", headers=admin_auth).json() == {
        "ok": False, "latency_ms": 0, "error": "Email is not configured"}
    assert smtp.calls == []


@pytest.mark.parametrize("failure,error", [(None, None), ("auth", "SMTP authentication failed"),
    ("send", "Email send failed"), ("connection", "SMTP connection failed")])
def test_test_connection(client, admin_auth, email_defaults, smtp, failure, error, caplog):
    smtp.failure = failure
    response = client.post(URL + "/test", headers=admin_auth)
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is (error is None)
    assert result["error"] == error
    assert isinstance(result["latency_ms"], int) and result["latency_ms"] >= 0
    assert SECRET not in response.text + caplog.text
    if error is None:
        assert smtp.messages[0]["To"] == "admin@test.local"
        assert smtp.messages[0]["Subject"] == "S-A-I-L: Connection test"
        assert smtp.messages[0].get_content().strip() == (
            "This is a connection test from S-A-I-L (Sales Analytics and Intelligence Launchpad).\n\n"
            "If you received this email, the SMTP configuration works.")


@pytest.mark.parametrize("security,mode,tls", [("starttls", "SMTP", True), ("ssl", "SMTP_SSL", False), ("none", "SMTP", False)])
def test_transport_modes(email_defaults, smtp, security, mode, tls):
    eff = config_service.effective_email_settings(None)
    eff["smtp_security"] = security
    email_service.send_message(eff, email_service.build_message(SimpleNamespace(type="mention", message="Hello")))
    assert smtp.calls[0] == (mode, "smtp.example.test", 587)
    assert ("starttls" in smtp.calls) is tls
    assert ("login", "mailer", SECRET) in smtp.calls
    assert smtp.calls[-1] == "quit"
