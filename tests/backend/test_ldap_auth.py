"""LDAP/AD directory-auth unit tests (0.2.0 P1, docs/archive/PLAN_LDAP_AD_AUTH.md §5).

Deterministic: the ``ldap3.Connection`` class is monkeypatched in
``backend.services.ldap_provider`` (no real directory in CI — charter §6).
Covers the provider mechanics (search filter escaping, objectGUID hex,
wrong password, unknown user, directory outage → LdapUnavailable, injection
guards) and the seam integration (LdapBackend → DirectoryIdentity,
§3.1 resolution table, JIT link/create/idempotent re-login, local-wins
collision, admin-role refusal).
"""


import pytest
from backend.models.use_case import User
from backend.services import ldap_provider
from backend.services.auth_provider import (
    AuthUnavailable,
    DirectoryIdentity,
    LdapBackend,
    LocalBackend,
    link_or_create_directory_user,
    resolve_auth_backend,
)
from backend.services.ldap_settings import LdapSettings
from ldap3.core import exceptions as ldap3_errors

GUID = bytes(range(16))  # 16-byte AD objectGUID blob
GUID_HEX = GUID.hex()


def make_settings(**over) -> LdapSettings:
    base = dict(
        enabled=True,
        server_uri="ldaps://dc01.corp:636",
        service_bind_dn="CN=sil_svc,OU=ServiceAccounts,DC=corp,DC=local",
        service_bind_password="svc-secret",
        user_search_base_dn="OU=Users,DC=corp,DC=local",
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


# ── fake ldap3 ──────────────────────────────────────────────────────────


class FakeEntry:
    """Mirror the REAL ldap3 2.9.1 ``Entry`` access surface, not the provider's
    historical (broken) accesses.

    Real ``Entry`` exposes the DN via the ``entry_dn`` property and raw
    values via ``entry_raw_attributes``; any other attribute access is a
    directory-attribute lookup that raises ``LDAPCursorAttributeError``
    (a subclass of ``AttributeError``) when the attribute is absent. The
    first real-wire acceptance (2026-11-06) caught the provider reading
    ``entry.dn`` / ``entry.raw_attributes`` — a fake that exposed plain
    ``.dn`` / ``.raw_attributes`` attributes masked exactly that class of
    defect.
    """

    def __init__(self, dn, attrs):
        self._dn = dn
        self._attrs = {
            k: (v if isinstance(v, (list, tuple)) else [v])
            for k, v in attrs.items()
        }

    @property
    def entry_dn(self):
        return self._dn

    @property
    def entry_raw_attributes(self):
        return dict(self._attrs)

    @property
    def entry_attributes(self):
        return dict(self._attrs)

    def __getattr__(self, item):
        if item.startswith("_"):
            raise AttributeError(item)
        try:
            return self._attrs[item]
        except KeyError:
            raise ldap3_errors.LDAPCursorAttributeError(
                "attribute '%s' not found" % item
            )


def _ok_entry():
    return FakeEntry(
        "CN=Jane Roe,OU=Users,DC=corp,DC=local",
        {
            "objectGUID": [GUID],
            "mail": ["jane@corp.local"],
            "displayName": ["Jane Roe"],
            "department": ["Engineering"],
        },
    )


class FakeServiceConn:
    def __init__(self, server, user, password, auto_bind, raise_exceptions,
                 receive_timeout):
        self.server = server
        self.entries = []
        self.search_kwargs = None

    def search(self, **kw):
        self.search_kwargs = kw
        username = kw["search_filter"]
        if "jane" in username:
            self.entries = [_ok_entry()]
        else:
            self.entries = []
        return bool(self.entries)

    def unbind(self):
        pass

    def start_tls(self, **kw):
        pass


class FakeUserConn:
    def __init__(self, server, user, password, auto_bind):
        self.password = password

    def bind(self):
        if self.password != "jane-pass":
            raise ldap3_errors.LDAPInvalidCredentialsResult(
                "BIND", 49
            )
        return True

    def unbind(self):
        pass


def install_fakes(monkeypatch, service_error=None, user_error=False):
    """Patch ldap_provider.Connection with the fake pair (or a raiser)."""

    def factory(server, user=None, password=None, auto_bind=False, **kw):
        if service_error is not None:
            raise service_error
        if auto_bind:
            return FakeServiceConn(server, user, password, auto_bind, **kw)
        if user_error:
            class _BadUser(FakeUserConn):
                def bind(self):
                    raise ldap3_errors.LDAPInvalidCredentialsResult("BIND", 49)

            return _BadUser(server, user, password, auto_bind)
        return FakeUserConn(server, user, password, auto_bind)

    monkeypatch.setattr(ldap_provider, "Connection", factory)


# ── provider mechanics ───────────────────────────────────────────────────


class TestLdapProvider:
    def test_happy_path_returns_guid_hex_and_attrs(self, monkeypatch):
        install_fakes(monkeypatch)
        result = ldap_provider.authenticate(make_settings(), "jane", "jane-pass")
        assert result["external_id"] == GUID_HEX
        assert result["dn"].startswith("CN=Jane Roe")
        assert result["attributes"]["email"] == "jane@corp.local"
        assert result["attributes"]["display_name"] == "Jane Roe"
        assert result["attributes"]["department"] == "Engineering"

    def test_display_name_fallback_attributes_are_requested(self, monkeypatch):
        install_fakes(monkeypatch)
        requested = []
        original = FakeServiceConn.search

        def search(conn, **kwargs):
            requested.extend(kwargs["attributes"])
            result = original(conn, **kwargs)
            conn.entries = [FakeEntry("CN=Jane,DC=corp", {
                "objectGUID": [GUID], "givenName": ["Jane"], "sn": ["Roe"],
            })]
            return result

        monkeypatch.setattr(FakeServiceConn, "search", search)
        result = ldap_provider.authenticate(make_settings(), "jane", "jane-pass")
        assert {"givenName", "sn"} <= set(requested)
        assert result["attributes"]["display_name"] == "Jane Roe"

    def test_search_filter_escapes_username(self, monkeypatch):
        # Capture what the fake service conn received.
        captured = {}

        class CapService(FakeServiceConn):
            def search(self, **kw):
                captured.update(kw)
                return super().search(**kw)

        def factory(server, user=None, password=None, auto_bind=False, **kw):
            if auto_bind:
                return CapService(server, user, password, auto_bind, **kw)
            return FakeUserConn(server, user, password, auto_bind)

        monkeypatch.setattr(ldap_provider, "Connection", factory)
        ldap_provider.authenticate(
            make_settings(), "jane", "jane-pass"
        )
        # The filter kept the template shape with the (escaped) value bound
        # in — no raw concatenation, and the base DN is the configured one.
        assert captured["search_filter"].startswith("(sAMAccountName=")
        assert "jane" in captured["search_filter"]
        assert captured["search_base"] == "OU=Users,DC=corp,DC=local"

    def test_wrong_password_is_unified_auth_error(self, monkeypatch):
        install_fakes(monkeypatch, user_error=True)
        with pytest.raises(ldap_provider.LdapAuthError):
            ldap_provider.authenticate(make_settings(), "jane", "WRONG")

    @pytest.mark.parametrize("code, error", [(49, ldap_provider.LdapAuthError), (52, ldap_provider.LdapUnavailable)])
    def test_false_bind_never_authenticates(self, monkeypatch, code, error):
        class FalseBind(FakeUserConn):
            result = {"result": code}

            def bind(self):
                return False

        def factory(server, user=None, password=None, auto_bind=False, **kw):
            if auto_bind:
                return FakeServiceConn(server, user, password, auto_bind, **kw)
            return FalseBind(server, user, password, auto_bind)

        monkeypatch.setattr(ldap_provider, "Connection", factory)
        with pytest.raises(error):
            ldap_provider.authenticate(make_settings(), "jane", "wrong")

    def test_empty_password_never_contacts_directory(self, monkeypatch):
        install_fakes(monkeypatch, service_error=AssertionError("unexpected directory access"))
        with pytest.raises(ldap_provider.LdapAuthError):
            ldap_provider.authenticate(make_settings(), "jane", "")

    def test_starttls_precedes_both_password_binds(self, monkeypatch):
        calls = []

        class TlsUser(FakeUserConn):
            def start_tls(self):
                calls.append("user TLS")
                return True

            def bind(self):
                calls.append("user bind")
                return True

        def factory(server, user=None, password=None, auto_bind=False, **kw):
            if auto_bind:
                assert auto_bind == ldap_provider.ldap3.AUTO_BIND_TLS_BEFORE_BIND
                calls.append("service TLS before bind")
                return FakeServiceConn(server, user, password, auto_bind, **kw)
            return TlsUser(server, user, password, auto_bind)

        monkeypatch.setattr(ldap_provider, "Connection", factory)
        settings = make_settings(server_uri="ldap://dc01.corp:389", start_tls=True)
        ldap_provider.authenticate(settings, "jane", "jane-pass")
        assert calls == ["service TLS before bind", "user TLS", "user bind"]

    def test_failed_user_starttls_prevents_bind(self, monkeypatch):
        class TlsUser(FakeUserConn):
            def start_tls(self):
                return False

            def bind(self):
                pytest.fail("password bind must not run after StartTLS failure")

        def factory(server, user=None, password=None, auto_bind=False, **kw):
            if auto_bind:
                return FakeServiceConn(server, user, password, auto_bind, **kw)
            return TlsUser(server, user, password, auto_bind)

        monkeypatch.setattr(ldap_provider, "Connection", factory)
        with pytest.raises(ldap_provider.LdapUnavailable):
            ldap_provider.authenticate(make_settings(server_uri="ldap://dc01.corp:389", start_tls=True), "jane", "jane-pass")

    def test_unknown_user_is_unified_auth_error(self, monkeypatch):
        install_fakes(monkeypatch)
        with pytest.raises(ldap_provider.LdapAuthError):
            ldap_provider.authenticate(make_settings(), "ghost", "whatever")

    def test_directory_outage_is_unavailable(self, monkeypatch):
        install_fakes(monkeypatch, service_error=ldap3_errors.LDAPSocketOpenError())
        with pytest.raises(ldap_provider.LdapUnavailable):
            ldap_provider.authenticate(make_settings(), "jane", "jane-pass")

    def test_injection_username_rejected_before_search(self, monkeypatch):
        install_fakes(monkeypatch)
        with pytest.raises(ldap_provider.LdapAuthError):
            ldap_provider.authenticate(
                make_settings(), "admin*)(uid=*))", "x"
            )

    def test_too_long_username_rejected(self, monkeypatch):
        install_fakes(monkeypatch)
        with pytest.raises(ldap_provider.LdapAuthError):
            ldap_provider.authenticate(make_settings(), "a" * 101, "x")

    def test_filter_validation_rejects_second_placeholder(self):
        with pytest.raises(ldap_provider.LdapConfigError):
            ldap_provider.validate_filter_template("(uid={username})(sn={x})")

    def test_filter_validation_rejects_zero_placeholders(self):
        with pytest.raises(ldap_provider.LdapConfigError):
            ldap_provider.validate_filter_template("(uid=fixed)")

    def test_filter_validation_accepts_ad_template(self):
        ldap_provider.validate_filter_template("(sAMAccountName={username})")

    def test_encode_guid_round_trip(self):
        assert ldap_provider.encode_guid(GUID) == GUID_HEX
        assert ldap_provider.encode_guid("uuid-string") == "uuid-string"
        assert ldap_provider.encode_guid(b"short") is None
        assert ldap_provider.encode_guid(None) is None


# ── seam integration ─────────────────────────────────────────────────────


class TestLdapBackendSeam:
    def test_login_rejects_false_bind_without_provisioning_and_accepts_success(self, client, db_session, monkeypatch):
        import importlib

        import backend.services.ldap_settings as ls

        auth_routes = importlib.import_module("backend.routes.auth")
        monkeypatch.setattr(auth_routes, "resolve_auth_backend", lambda db, username: LdapBackend())
        monkeypatch.setattr(ls, "effective_ldap_settings", lambda db: make_settings())

        class FalseBind(FakeUserConn):
            result = {"result": 49}

            def bind(self):
                return False

        def factory(server, user=None, password=None, auto_bind=False, **kw):
            if auto_bind:
                return FakeServiceConn(server, user, password, auto_bind, **kw)
            return FalseBind(server, user, password, auto_bind)

        monkeypatch.setattr(ldap_provider, "Connection", factory)
        for password in ("wrong", ""):
            response = client.post("/api/auth/login/", json={"username": "jane", "password": password})
            assert response.status_code == 401
            assert db_session.query(User).filter_by(username="jane").first() is None

        install_fakes(monkeypatch)
        response = client.post("/api/auth/login/", json={"username": "jane", "password": "jane-pass"})
        assert response.status_code == 200 and response.json()["token"]
        assert db_session.query(User).filter_by(username="jane", external_id=GUID_HEX).one()

    def test_ldap_backend_maps_to_directory_identity(self, db_session, monkeypatch):
        install_fakes(monkeypatch)
        # Point effective_ldap_settings at an enabled+valid config so the seam's
        # validation passes (test env has no SAIL_AUTH_LDAP_* → default
        # disabled/empty). The fake Connection ignores the settings.
        import backend.services.ldap_settings as ls

        monkeypatch.setattr(
            ls, "effective_ldap_settings", lambda db: make_settings()
        )
        result = LdapBackend().authenticate(db_session, "jane", "jane-pass")
        assert isinstance(result, DirectoryIdentity)
        assert result.external_id == GUID_HEX

    def test_resolution_local_row_stays_local(self, db_session):
        db_session.add(User(username="jane", email="j@t.local",
                            hashed_password="x", is_active=1, approved=1))
        db_session.commit()
        assert isinstance(resolve_auth_backend(db_session, "jane"), LocalBackend)

    def test_resolution_ldap_row_uses_directory(self, db_session):
        db_session.add(User(username="jane", email="j@t.local",
                            hashed_password=None, is_active=1, approved=1,
                            auth_provider="ldap", external_id=GUID_HEX))
        db_session.commit()
        assert isinstance(resolve_auth_backend(db_session, "jane"), LdapBackend)

    def test_resolution_unknown_username_ldap_disabled_stays_local(self, db_session):
        # auth_ldap_enabled defaults to False in the test env → local path.
        assert isinstance(resolve_auth_backend(db_session, "nobody"), LocalBackend)


class TestJitLinkCreate:
    def _identity(self) -> DirectoryIdentity:
        return DirectoryIdentity(
            dn="CN=Jane Roe,OU=Users,DC=corp,DC=local",
            external_id=GUID_HEX,
            email="jane@corp.local",
            display_name="Jane Roe",
            department="Engineering",
        )

    def test_jit_create(self, db_session):
        user = link_or_create_directory_user(
            db_session, self._identity(), "jane",
            auto_approve=True, default_role="user",
        )
        assert user.auth_provider == "ldap"
        assert user.external_id == GUID_HEX
        assert user.hashed_password is None
        assert user.approved == 1
        assert user.role == "user"
        assert user.is_admin == 0
        assert user.is_active == 1
        assert user.last_directory_login_at is not None

    def test_jit_create_admin_role_never_granted(self, db_session):
        user = link_or_create_directory_user(
            db_session, self._identity(), "jane",
            auto_approve=True, default_role="admin",  # rule 5 — refused
        )
        assert user.is_admin == 0
        assert user.role == "user"

    def test_idempotent_relogin_by_external_id(self, db_session):
        first = link_or_create_directory_user(
            db_session, self._identity(), "jane",
            auto_approve=True, default_role="user",
        )
        second = link_or_create_directory_user(
            db_session, self._identity(), "jane",
            auto_approve=True, default_role="user",
        )
        assert second.id == first.id
        rows = db_session.query(User).filter(User.external_id == GUID_HEX).all()
        assert len(rows) == 1

    def test_null_hash_same_username_links_not_creates(self, db_session):
        stale = User(username="jane", email="jane@corp.local",
                     hashed_password=None, is_active=1, approved=1,
                     auth_provider="ldap")
        db_session.add(stale)
        db_session.commit()
        db_session.refresh(stale)
        user = link_or_create_directory_user(
            db_session, self._identity(), "jane",
            auto_approve=True, default_role="user",
        )
        assert user.id == stale.id
        assert user.external_id == GUID_HEX

    def test_local_account_collision_refused(self, db_session):
        local = User(username="jane", email="j@t.local",
                     hashed_password="local-hash", is_active=1, approved=1)
        db_session.add(local)
        db_session.commit()
        db_session.refresh(local)
        with pytest.raises(AuthUnavailable):
            link_or_create_directory_user(
                db_session, self._identity(), "jane",
                auto_approve=True, default_role="user",
            )


# ── ldap3 receive_timeout compatibility (real-wire acceptance 2026-11-06) ─


def install_capture(monkeypatch, seen):
    """Record the receive_timeout kwarg each ldap3 Connection receives."""

    def factory(server, user=None, password=None, auto_bind=False, **kw):
        seen.append(kw.get("receive_timeout"))
        if auto_bind:
            return FakeServiceConn(server, user, password, auto_bind, **kw)
        return FakeUserConn(server, user, password, auto_bind)

    monkeypatch.setattr(ldap_provider, "Connection", factory)


class TestReceiveTimeoutCompat:
    """ldap3 2.9.1 on Linux feeds receive_timeout to struct.pack('LL', ...):
    a float raises struct.error during connection open — before StartTLS —
    and the whole directory link surfaces as 'directory unreachable'. The
    provider must hand ldap3 an int (or None for no explicit timeout)."""

    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (5.0, 5),
            (4.2, 5),
            (1.0, 1),
            (0.2, 1),
            (0.0, None),
            (None, None),
            (-3.0, None),
        ],
    )
    def test_helper_converts_to_int_seconds(self, seconds, expected):
        assert ldap_provider._receive_timeout(seconds) == expected

    def test_provider_passes_int_to_service_and_user_connections(self, monkeypatch):
        seen: list = []
        install_capture(monkeypatch, seen)
        ldap_provider.authenticate(make_settings(timeout_seconds=4.2), "jane", "jane-pass")
        # service bind + user verify bind, both bounded, both int.
        assert seen == [5, 5]

    def test_provider_service_bind_path_passes_int(self, monkeypatch):
        seen: list = []
        install_capture(monkeypatch, seen)
        assert ldap_provider._service_bind_ok(make_settings(timeout_seconds=5.0)) is True
        assert seen == [5]

    def test_zero_timeout_means_no_explicit_bound(self, monkeypatch):
        seen: list = []
        install_capture(monkeypatch, seen)
        ldap_provider.authenticate(make_settings(timeout_seconds=0.0), "jane", "jane-pass")
        assert seen == [None, None]

    def test_fake_entry_mirrors_real_ldap3_access_surface(self):
        """Guard against the mock diverging from ldap3 2.9.1 again: real
        Entry exposes entry_dn/entry_raw_attributes, and bare .dn /
        .raw_attributes raise (LDAPCursorAttributeError ⊂ AttributeError).
        """
        entry = _ok_entry()
        with pytest.raises(AttributeError):
            entry.dn
        with pytest.raises(AttributeError):
            entry.raw_attributes
        assert entry.entry_dn == "CN=Jane Roe,OU=Users,DC=corp,DC=local"
        assert "objectGUID" in entry.entry_raw_attributes
        assert entry.mail == ["jane@corp.local"]
        # absent attribute: real semantics — getattr default yields None
        assert getattr(entry, "doesNotExist", None) is None
