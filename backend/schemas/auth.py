"""Pydantic schemas for the auth (directory/LDAP) admin surface.

The admin settings surface carries ONLY the
non-secret values. The service bind password is env/Secret-only: it has no
schema field, is never persisted, and never appears in any response
(§3.6 rule 3).
"""


from pydantic import BaseModel

from backend.schemas.admin_config import SslVerifyMode


class LdapSettingsResponse(BaseModel):
    """Directory-auth settings (admin-editable; DB overrides .env).

    ``service_bind_password`` is deliberately absent (secret — env/Secret
    only). ``local_register_enabled`` is a local-auth toggle surfaced here so
    the admin Application-Settings area owns the whole auth picture.
    """

    enabled: bool = False
    server_uri: str = ""
    service_bind_dn: str = ""
    user_search_base_dn: str = ""
    user_search_filter: str = ""
    start_tls: bool = False
    require_tls: bool = True
    ssl_verify: SslVerifyMode = "full"
    ssl_ca_bundle: str | None = None
    timeout_seconds: float = 5.0
    email_attr: str = "mail"
    display_name_attr: str = "displayName"
    department_attr: str = "department"
    external_id_attr: str = "objectGUID"
    auto_approve: bool = True
    default_role: str = "user"
    login_disabled: bool = False
    local_register_enabled: bool = True


class AuthPublicSettingsResponse(BaseModel):
    """Unauthenticated public auth settings (drives the Login page).

    No secrets, no per-account data.
    ``ldap_enabled`` is True only when the directory is enabled AND not
    kill-switched off — the login hint must not advertise a disabled link.
    """

    local_register_enabled: bool = True
    ldap_enabled: bool = False
    login_hint: str = ""


class LdapTestResponse(BaseModel):
    """Result of the admin test-connection probe (service-account bind +
    one controlled search). Never carries user data, never secrets (§3.6)."""

    ok: bool
    latency_ms: int = 0
    user_count_sampled: int = 0
    error: str | None = None  # fixed/short messages only (no ldap3 raw text)
