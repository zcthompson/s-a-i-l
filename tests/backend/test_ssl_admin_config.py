"""Admin config surface for the connection trust model (docs/archive/PLAN_LDAP_AD_AUTH.md P0b).

Pins the API contract the expanded Application Settings UI consumes:

- ``GET/PUT /api/admin/config/inference`` now carries ``ssl_verify`` +
  ``ssl_ca_bundle`` (save-time 422 on bad PEM / missing bundle for ``ca`` /
  invalid mode);
- ``GET/PUT /api/admin/config/docling`` (new — Docling was env-only before):
  ``server_url`` / ``timeout_seconds`` / ``ssl_verify`` / ``ssl_ca_bundle``,
  with NO ``api_key`` in the contract (env/Secret-only);
- admin-only guard (401 anonymous / 403 non-admin).

Deterministic: PEM generated via host openssl; no live network, no secrets.
"""

import os
import subprocess
import tempfile

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from unittest.mock import patch

import pytest

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _pem() -> str:
    pem_path, key_path = tempfile.mktemp(suffix=".pem"), tempfile.mktemp(suffix=".key")
    subprocess.run(
        ["openssl", "req", "-x509", "-new", "-nodes", "-subj", "/CN=ssl-admin-test",
         "-days", "1", "-keyout", key_path, "-out", pem_path],
        capture_output=True, check=True,
    )
    with open(pem_path) as fh:
        data = fh.read()
    for p in (pem_path, key_path):
        os.unlink(p)
    return data


PEM = _pem()
BAD_PEM = "-----BEGIN CERTIFICATE-----\nnot-a-real-cert\n-----END CERTIFICATE-----\n"



@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    """Point the real JWT user lookup at the shared session."""
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
        return {"username": user.username, "email": user.email,
                "display_name": user.display_name, "department": user.department,
                "is_admin": user.is_admin, "role": user.role, "user_id": user.id}

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
def _cleanup_ssl_overrides(client, admin_auth):
    """Leave the shared test DB's effective settings clean for later files."""
    yield
    for category, keys in (("inference", ("ssl_verify", "ssl_ca_bundle")),
                           ("docling", ("server_url", "timeout_seconds", "ssl_verify", "ssl_ca_bundle"))):
        for key in keys:
            client.delete(f"/api/admin/config/category/{category}/{key}",
                          headers=admin_auth)


class TestInferenceSslContract:
    def test_get_carries_ssl_fields(self, client, admin_auth):
        r = client.get("/api/admin/config/inference", headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        assert "ssl_verify" in body
        assert "ssl_ca_bundle" in body
        assert body["ssl_verify"] in ("full", "skip", "ca")

    def test_put_skip_round_trips(self, client, admin_auth):
        r = client.put("/api/admin/config/inference",
                       json={"ssl_verify": "skip"}, headers=admin_auth)
        assert r.status_code == 200
        assert r.json()["ssl_verify"] == "skip"
        # Stored entry visible through the generic category surface.
        r3 = client.get("/api/admin/config/category/inference", headers=admin_auth)
        assert any(e["key"] == "ssl_verify" and e["value"] == "skip"
                   for e in r3.json()["entries"])

    def test_put_ca_with_valid_bundle_round_trips(self, client, admin_auth):
        r = client.put("/api/admin/config/inference",
                       json={"ssl_verify": "ca", "ssl_ca_bundle": PEM},
                       headers=admin_auth)
        assert r.status_code == 200
        assert r.json()["ssl_verify"] == "ca"
        assert r.json()["ssl_ca_bundle"] == PEM

    def test_put_ca_without_bundle_is_422(self, client, admin_auth):
        r = client.put("/api/admin/config/inference",
                       json={"ssl_verify": "ca"}, headers=admin_auth)
        assert r.status_code == 422
        assert "CA bundle" in r.json()["detail"]

    def test_put_bad_pem_is_422_with_precise_message(self, client, admin_auth):
        r = client.put("/api/admin/config/inference",
                       json={"ssl_verify": "ca", "ssl_ca_bundle": BAD_PEM},
                       headers=admin_auth)
        assert r.status_code == 422
        assert "Invalid CA bundle" in r.json()["detail"]

    def test_put_invalid_mode_is_422(self, client, admin_auth):
        # Pydantic Literal rejects before our guard runs.
        r = client.put("/api/admin/config/inference",
                       json={"ssl_verify": "bogus"}, headers=admin_auth)
        assert r.status_code == 422


class TestDoclingConfigSurface:
    def test_get_contract_shape(self, client, admin_auth):
        r = client.get("/api/admin/config/docling", headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        for field in ("server_url", "timeout_seconds", "ssl_verify", "ssl_ca_bundle"):
            assert field in body, body
        # Secret is NOT part of the surface (env/Secret-only by design).
        assert "api_key" not in body

    def test_put_round_trips(self, client, admin_auth):
        r = client.put("/api/admin/config/docling",
                       json={"server_url": "http://docling.example.internal:5001",
                             "timeout_seconds": 900.0,
                             "ssl_verify": "full"},
                       headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        assert body["server_url"] == "http://docling.example.internal:5001"
        assert body["timeout_seconds"] == 900.0

    def test_put_bad_pem_is_422(self, client, admin_auth):
        r = client.put("/api/admin/config/docling",
                       json={"ssl_verify": "ca", "ssl_ca_bundle": BAD_PEM},
                       headers=admin_auth)
        assert r.status_code == 422

    def test_put_skips_empty_strings(self, client, admin_auth):
        r = client.put("/api/admin/config/docling",
                       json={"server_url": "", "ssl_verify": "full"},
                       headers=admin_auth)
        assert r.status_code == 200
        r3 = client.get("/api/admin/config/category/docling", headers=admin_auth)
        assert not any(e["key"] == "server_url" and e["value"] == ""
                       for e in r3.json()["entries"])


class TestGuard:
    def test_anonymous_is_401(self, client):
        assert client.get("/api/admin/config/docling").status_code == 401
        assert client.put("/api/admin/config/docling", json={}).status_code == 401

    def test_non_admin_is_403(self, client, db_session):
        from backend.auth import create_access_token
        from backend.models.use_case import User

        member = User(username="member", email="member@test.local",
                      hashed_password=_FAKE_BCRYPT_HASH,
                      display_name="Member", is_admin=0, approved=1, is_active=1)
        db_session.add(member)
        db_session.commit()
        db_session.refresh(member)
        headers = {"Authorization": f"Bearer {create_access_token({'sub': 'member', 'is_admin': False})}"}
        assert client.get("/api/admin/config/docling", headers=headers).status_code == 403
