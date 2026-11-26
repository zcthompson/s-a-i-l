"""LDAP/AD settings tests (0.2.0 P1, docs/archive/PLAN_LDAP_AD_AUTH.md §5).

Deterministic: env defaults come from Settings (test env has no
SAIL_AUTH_LDAP_* set → plan defaults); DB overrides are written via
the SystemConfig 'auth_ldap' category. Covers env→DB precedence, the secret
never-leaks invariant, and the §3.6 validation rules (TLS enforcement,
filter-template, admin-role refusal).
"""

import pytest
from backend.config import get_settings
from backend.models.collaboration import SystemConfig
from backend.services.ldap_settings import (
    LDAP_KEYS,
    effective_ldap_settings,
    validate_effective_ldap_settings,
)


@pytest.fixture(autouse=True)
def _clean_ldap_category(db_session):
    """auth_ldap must start empty so env defaults are what the tests see."""
    yield
    db_session.query(SystemConfig).filter(
        SystemConfig.category == "auth_ldap"
    ).delete(synchronize_session=False)
    db_session.commit()


def _write(db_session, key, value):
    from backend.services.config_service import upsert_config_entry

    upsert_config_entry(db_session, "auth_ldap", key, value)


class TestEffectiveSettings:
    def test_env_defaults_when_no_db_rows(self, db_session):
        base = get_settings()
        eff = effective_ldap_settings(db_session)
        assert eff.enabled is base.auth_ldap_enabled
        assert eff.server_uri == base.auth_ldap_server_uri
        assert eff.require_tls is base.auth_ldap_require_tls
        assert eff.auto_approve is base.auth_ldap_auto_approve
        assert eff.default_role == base.auth_ldap_default_role
        assert eff.external_id_attr == "objectGUID"
        assert eff.timeout_seconds == pytest.approx(5.0)

    def test_db_override_wins(self, db_session):
        _write(db_session, "server_uri", "ldap://dc01:389")
        _write(db_session, "start_tls", True)
        _write(db_session, "auto_approve", False)
        eff = effective_ldap_settings(db_session)
        assert eff.server_uri == "ldap://dc01:389"
        assert eff.start_tls is True
        assert eff.auto_approve is False

    def test_empty_string_override_falls_back(self, db_session):
        # Empty strings are treated as "unset" by the override layer.
        _write(db_session, "server_uri", "ldaps://dc01:636")
        eff = effective_ldap_settings(db_session)
        assert eff.server_uri == "ldaps://dc01:636"

    def test_service_bind_password_is_env_only(self, db_session):
        # Even a row that somehow holds the password key is never read back.
        _write(db_session, "service_bind_password", "SHOULD-NEVER-APPEAR")
        eff = effective_ldap_settings(db_session)
        assert eff.service_bind_password == get_settings().auth_ldap_service_bind_password
        assert "SHOULD-NEVER-APPEAR" not in repr(eff)
        assert "service_bind_password" not in LDAP_KEYS

    def test_disabled_dir_needs_nothing(self, db_session):
        # No overrides, env default disabled → validation passes trivially.
        eff = effective_ldap_settings(db_session)
        if not eff.enabled:
            validate_effective_ldap_settings(eff)  # must not raise


class TestValidationRules:
    def _enabled(self, **over):
        from backend.services.ldap_settings import LdapSettings

        base = dict(
            enabled=True,
            server_uri="ldaps://dc01:636",
            service_bind_dn="CN=svc,DC=corp",
            service_bind_password="x",
            user_search_base_dn="OU=Users,DC=corp",
            user_search_filter="(sAMAccountName={username})",
            start_tls=False,
            require_tls=True,
            ssl_verify="full",
            ssl_ca_bundle="",
            timeout_seconds=5.0,
            email_attr="mail",
            display_name_attr="displayName",
            department_attr="department",
            external_id_attr="objectGUID",
            auto_approve=True,
            default_role="user",
            login_disabled=False,
            local_register_enabled=True,
        )
        base.update(over)
        return LdapSettings(**base)  # type: ignore[arg-type]

    def test_requires_uri_bind_dn_base_dn(self, db_session):
        for missing in ("server_uri", "service_bind_dn", "user_search_base_dn"):
            eff = self._enabled()
            setattr(eff, missing, "")
            with pytest.raises(Exception):
                validate_effective_ldap_settings(eff)

    def test_require_tls_refuses_plaintext_without_starttls(self, db_session):
        eff = self._enabled(server_uri="ldap://dc01:389", start_tls=False)
        with pytest.raises(Exception, match="require_tls"):
            validate_effective_ldap_settings(eff)

    def test_plaintext_with_starttls_is_ok(self, db_session):
        eff = self._enabled(server_uri="ldap://dc01:389", start_tls=True)
        validate_effective_ldap_settings(eff)  # 389 + StartTLS — first-class

    def test_require_tls_false_allows_plain_dev(self, db_session):
        eff = self._enabled(server_uri="ldap://dc01:389", start_tls=False,
                            require_tls=False)
        validate_effective_ldap_settings(eff)

    def test_ldaps_636_is_ok_by_default(self, db_session):
        eff = self._enabled(server_uri="ldaps://dc01:636")
        validate_effective_ldap_settings(eff)

    def test_admin_default_role_refused(self, db_session):
        eff = self._enabled(default_role="admin")
        with pytest.raises(Exception, match="refused"):
            validate_effective_ldap_settings(eff)

    def test_bad_filter_refused(self, db_session):
        eff = self._enabled(user_search_filter="(uid=fixed)")
        with pytest.raises(Exception, match="username"):
            validate_effective_ldap_settings(eff)

class TestPublicSettingsSurface:
    """P2: unauthenticated /auth/settings/public/ + local register gate."""

    def test_public_settings_shape_and_defaults(self, client):
        r = client.get("/api/auth/settings/public/")
        assert r.status_code == 200
        body = r.json()
        assert body["local_register_enabled"] is True
        assert body["ldap_enabled"] is False
        assert body["login_hint"] == ""
        # No secrets or per-account data on the public surface.
        assert "password" not in body and "bind" not in str(body).lower()

    def test_public_settings_reflects_enabled_ldap(self, client, db_session):
        from backend.services.config_service import upsert_config_entry

        upsert_config_entry(db_session, "auth_ldap", "enabled", True)
        upsert_config_entry(db_session, "auth_ldap", "server_uri", "ldaps://dc01:636")
        upsert_config_entry(
            db_session, "auth_ldap", "service_bind_dn", "CN=svc,DC=corp"
        )
        upsert_config_entry(
            db_session, "auth_ldap", "user_search_base_dn", "OU=Users,DC=corp"
        )
        upsert_config_entry(
            db_session, "auth_ldap", "user_search_filter",
            "(sAMAccountName={username})",
        )
        body = client.get("/api/auth/settings/public/").json()
        assert body["ldap_enabled"] is True
        assert "directory" in body["login_hint"]

        # Kill-switch: enabled + login_disabled → not advertised.
        upsert_config_entry(db_session, "auth_ldap", "login_disabled", True)
        assert client.get("/api/auth/settings/public/").json()["ldap_enabled"] is False

    def test_register_403_when_local_register_disabled(self, client, db_session):
        from backend.services.config_service import upsert_config_entry

        upsert_config_entry(
            db_session, "auth_ldap", "local_register_enabled", False
        )
        r = client.post(
            "/api/auth/register/",
            json={
                "username": "newp2user",
                "email": "newp2@test.local",
                "password": "SecurePass123",
                "display_name": "New P2",
                "department": None,
            },
        )
        assert r.status_code == 403
        assert "Self-registration is disabled" in r.json()["detail"]

    def test_register_allowed_by_default(self, client, db_session):
        # local_register_enabled defaults True (today's behavior preserved).
        r = client.post(
            "/api/auth/register/",
            json={
                "username": "p2okuser",
                "email": "p2ok@test.local",
                "password": "SecurePass123",
                "display_name": "P2 OK",
                "department": None,
            },
        )
        assert r.status_code == 200
        assert r.json()["username"] == "p2okuser"
        assert r.json()["auth_provider"] == "local"

    def test_user_response_carries_auth_provider(self, client, db_session):
        # /me (or the admin listing) must expose auth_provider for the
        # admin table's provider column (0.2.0 P2).
        from backend.models.use_case import User

        row = User(
            username="ldaprow",
            email="ldaprow@test.local",
            hashed_password=None,
            is_active=1,
            approved=1,
            auth_provider="ldap",
            external_id="guid-hex-p2",
        )
        db_session.add(row)
        db_session.commit()
        db_session.refresh(row)
        d = row.to_dict()
        assert d["auth_provider"] == "ldap"

    def test_disabled_settings_skip_validation(self, db_session):
        from backend.services.ldap_settings import LdapSettings

        eff = LdapSettings(
            enabled=False, server_uri="", service_bind_dn="",
            service_bind_password="", user_search_base_dn="",
            user_search_filter="", start_tls=False, require_tls=True,
            ssl_verify="full", ssl_ca_bundle="", timeout_seconds=5.0,
            email_attr="mail", display_name_attr="displayName",
            department_attr="department", external_id_attr="objectGUID",
            auto_approve=True, default_role="admin",  # ignored when disabled
            login_disabled=False, local_register_enabled=True,
        )
        validate_effective_ldap_settings(eff)  # must not raise
