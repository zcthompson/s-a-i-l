"""SEC-02/03/04 regression coverage for auth, uploads, and password KDF."""

import hashlib
import importlib.util
from pathlib import Path

import pytest
from backend.auth import create_access_token, is_legacy_password_hash
from backend.models.use_case import User
from backend.rate_limit import (
    LOGIN_RATE_LIMIT_WINDOW,
    REGISTER_RATE_LIMIT_WINDOW,
    RateLimitMiddleware,
)
from backend.upload_size import MAX_UPLOAD_BYTES, read_upload_bytes
from fastapi import HTTPException
from starlette.requests import Request


def _load_real_auth_module():
    """Load auth.py separately from conftest's suite-wide fast KDF double."""
    path = Path(__file__).resolve().parents[2] / "backend" / "auth.py"
    spec = importlib.util.spec_from_file_location("_sec0234_auth_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _legacy_hash(password: str) -> str:
    salt = "0123456789abcdef0123456789abcdef"
    hashed = hashlib.sha512((salt + password).encode()).hexdigest()
    for _ in range(1000):
        hashed = hashlib.sha512((salt + hashed).encode()).hexdigest()
    return f"{salt}${hashed}"


def _admin_headers() -> dict:
    token = create_access_token({"sub": "admin", "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


class _AsyncUpload:
    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _request(peer: str, headers=None) -> Request:
    raw_headers = [
        (key.lower().encode("latin-1"), value.encode("latin-1"))
        for key, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": raw_headers,
            "client": (peer, 1234),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def test_auth_rate_limits_use_independent_endpoint_buckets(monkeypatch):
    """Self-contained: mounts the real middleware on a dedicated app.

    The shared app (backend.main) only mounts RateLimitMiddleware when
    SAIL_API_KEYS is set at import time — the gitignored .env provides it
    on the dev host but not on CI, so this test builds its own app
    instance and exercises the per-endpoint buckets without ambient-env
    dependence. (The env var is still set per-request, which the
    middleware checks dynamically.)
    """
    from backend.rate_limit import rate_limiter
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SAIL_API_KEYS", "rate-limit-test-key")

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware)

    @app.post("/api/auth/login")
    def _login():
        return {"ok": True}

    @app.post("/api/auth/register")
    def _register():
        return {"ok": True}

    rate_limiter.requests.clear()
    try:
        with TestClient(app) as client:
            # login bucket: 10 allowed, 11th rejected
            for _ in range(10):
                assert client.post("/api/auth/login").status_code == 200
            response = client.post("/api/auth/login")
            assert response.status_code == 429
            assert response.headers["Retry-After"] == str(LOGIN_RATE_LIMIT_WINDOW)
            assert response.headers["X-RateLimit-Limit"] == "10"
            assert response.headers["X-RateLimit-Remaining"] == "0"
            assert response.json()["retry_after"] == LOGIN_RATE_LIMIT_WINDOW

            # register bucket is independent: its own 5-request budget
            for _ in range(5):
                assert client.post("/api/auth/register").status_code == 200
            response = client.post("/api/auth/register")
            assert response.status_code == 429
            assert response.headers["Retry-After"] == str(REGISTER_RATE_LIMIT_WINDOW)
            assert response.headers["X-RateLimit-Limit"] == "5"
            assert response.json()["retry_after"] == REGISTER_RATE_LIMIT_WINDOW
    finally:
        rate_limiter.requests.clear()


def test_client_ip_ignores_forwarded_headers_by_default(monkeypatch):
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)
    monkeypatch.delenv("SAIL_TRUSTED_PROXIES", raising=False)
    request = _request(
        "198.51.100.10",
        {"X-Forwarded-For": "203.0.113.5", "X-Real-IP": "203.0.113.6"},
    )
    assert middleware.get_client_ip(request) == "198.51.100.10"


def test_client_ip_honors_headers_only_for_trusted_peer(monkeypatch):
    middleware = RateLimitMiddleware(lambda scope, receive, send: None)
    monkeypatch.setenv("SAIL_TRUSTED_PROXIES", "198.51.100.10")
    trusted = _request(
        "198.51.100.10",
        {"X-Forwarded-For": " , 203.0.113.5, 203.0.113.6"},
    )
    untrusted = _request(
        "198.51.100.11", {"X-Forwarded-For": "203.0.113.7"}
    )
    assert middleware.get_client_ip(trusted) == "203.0.113.5"
    assert middleware.get_client_ip(untrusted) == "198.51.100.11"


@pytest.mark.asyncio
async def test_shared_upload_reader_rejects_oversized_upload():
    with pytest.raises(HTTPException) as exc:
        await read_upload_bytes(_AsyncUpload(b"x" * (MAX_UPLOAD_BYTES + 1)))
    assert exc.value.status_code == 413
    assert exc.value.detail == "Upload exceeds the maximum size of 10 MiB"


@pytest.mark.asyncio
async def test_shared_upload_reader_rejects_empty_upload():
    with pytest.raises(HTTPException) as exc:
        await read_upload_bytes(_AsyncUpload(b""))
    assert exc.value.status_code == 400
    assert exc.value.detail == "Upload is empty"


@pytest.mark.asyncio
async def test_shared_upload_reader_returns_small_upload():
    assert await read_upload_bytes(_AsyncUpload(b"small upload")) == b"small upload"


def test_bcrypt_hash_verify_and_legacy_compatibility():
    auth_under_test = _load_real_auth_module()
    password = "A secure password longer than seventy-two bytes: " + "x" * 80
    hashed = auth_under_test.hash_password(password)
    assert hashed.startswith("$2b$12$")
    assert auth_under_test.verify_password(password, hashed)
    assert not auth_under_test.verify_password(password + "!", hashed)

    legacy = _legacy_hash("LegacyPass!2")
    assert auth_under_test.verify_password("LegacyPass!2", legacy)
    assert not auth_under_test.verify_password("wrong", legacy)
    assert is_legacy_password_hash(legacy)
    assert not is_legacy_password_hash(hashed)


def test_reset_password_schema_requires_twelve_characters(client, db_session):
    target = User(
        username="sec-reset",
        email="sec-reset@test.local",
        hashed_password="$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456",
        approved=1,
        is_active=1,
    )
    db_session.add(target)
    db_session.commit()

    endpoint = f"/api/auth/users/{target.id}/reset-password/"
    response = client.post(
        endpoint,
        json={"new_password": "12345678901"},
        headers=_admin_headers(),
    )
    assert response.status_code == 422

    response = client.post(
        endpoint,
        json={"new_password": "123456789012"},
        headers=_admin_headers(),
    )
    assert response.status_code == 200


def test_successful_local_login_rehashes_legacy_password(
    client, db_session, monkeypatch
):
    from backend.routes import auth as routes_auth_mod

    from backend import auth as auth_mod

    auth_under_test = _load_real_auth_module()
    password = "LegacyPass!2"
    user = User(
        username="legacy-login",
        email="legacy-login@test.local",
        hashed_password=_legacy_hash(password),
        approved=1,
        is_active=1,
        auth_provider="local",
    )
    db_session.add(user)
    db_session.commit()

    monkeypatch.setattr(auth_mod, "verify_password", auth_under_test.verify_password)
    monkeypatch.setattr(routes_auth_mod, "hash_password", auth_under_test.hash_password)
    response = client.post(
        "/api/auth/login/",
        json={"username": "legacy-login", "password": password},
    )
    assert response.status_code == 200, response.text

    db_session.expire_all()
    stored = (
        db_session.query(User.hashed_password)
        .filter(User.username == "legacy-login")
        .scalar()
    )
    assert stored.startswith("$2b$12$")
    assert auth_under_test.verify_password(password, stored)
