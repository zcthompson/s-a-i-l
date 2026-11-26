"""Effective LDAP/AD directory-auth settings.

Env is the source for secrets; SystemConfig
(category ``auth_ldap``) holds the non-secret values the admin UI edits.
``effective_ldap_settings(db)`` = env default → DB override (the
inference-config precedent), then ``validate_effective_ldap_settings``
applies the §3.6 security rules at the seams that need them (save-time in
the admin route; login-time in the route's provider resolution — a bad
directory config must never 500 ``/login/``).

The service bind password is env/Secret-only by design — it is NEVER read
from SystemConfig, persisted, or returned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.collaboration import SystemConfig

LDAP_KEYS = (
    "enabled",
    "server_uri",
    "service_bind_dn",
    "user_search_base_dn",
    "user_search_filter",
    "start_tls",
    "require_tls",
    "ssl_verify",
    "ssl_ca_bundle",
    "timeout_seconds",
    "email_attr",
    "display_name_attr",
    "department_attr",
    "external_id_attr",
    "auto_approve",
    "default_role",
    "login_disabled",
    "local_register_enabled",
)

#: admin may never be granted from the directory (§3.6 rule 5).
_ADMIN_ROLES = {"admin"}


@dataclass
class LdapSettings:
    """Resolved directory-auth settings (what the provider consumes).

    ``service_bind_password`` comes from the env only — the dataclass has
    no SystemConfig origin for it.
    """

    enabled: bool
    server_uri: str
    service_bind_dn: str
    service_bind_password: str
    user_search_base_dn: str
    user_search_filter: str
    start_tls: bool
    require_tls: bool
    ssl_verify: str
    ssl_ca_bundle: str
    timeout_seconds: float
    email_attr: str
    display_name_attr: str
    department_attr: str
    external_id_attr: str
    auto_approve: bool
    default_role: str
    login_disabled: bool
    # Local self-registration toggle (default true — current behavior).
    local_register_enabled: bool


def get_ldap_overrides(db: Session | None) -> dict[str, Any]:
    """Active DB overrides for the 'auth_ldap' category (empty/None skipped).

    The service bind password key is intentionally NOT in ``LDAP_KEYS``, so
    even if it ever reached the table it would never be read back.
    """
    if db is None:
        return {}
    rows = db.query(SystemConfig).filter(
        and_(SystemConfig.category == "auth_ldap", SystemConfig.is_active == 1)
    ).all()
    overrides: dict[str, Any] = {}
    for row in rows:
        if row.key not in LDAP_KEYS:
            continue
        value = row.to_dict().get("value")
        if value is None or value == "":
            continue
        overrides[str(row.key)] = value
    return overrides


def effective_ldap_settings(db: Session | None) -> LdapSettings:
    """Merge env defaults with DB overrides (DB wins when set)."""
    base = get_settings()
    ov = get_ldap_overrides(db)

    def _s(key: str, default: str) -> str:
        v = ov.get(key)
        return str(v) if v not in (None, "") else default

    def _b(key: str, default: bool) -> bool:
        v = ov.get(key)
        if v in (None, ""):
            return default
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() in ("1", "true", "yes", "on")

    def _f(key: str, default: float) -> float:
        v = ov.get(key)
        try:
            return float(v) if v not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return LdapSettings(
        enabled=_b("enabled", base.auth_ldap_enabled),
        server_uri=_s("server_uri", base.auth_ldap_server_uri),
        service_bind_dn=_s("service_bind_dn", base.auth_ldap_service_bind_dn),
        service_bind_password=base.auth_ldap_service_bind_password,
        user_search_base_dn=_s("user_search_base_dn", base.auth_ldap_user_search_base_dn),
        user_search_filter=_s("user_search_filter", base.auth_ldap_user_search_filter),
        start_tls=_b("start_tls", base.auth_ldap_start_tls),
        require_tls=_b("require_tls", base.auth_ldap_require_tls),
        ssl_verify=_s("ssl_verify", base.auth_ldap_ssl_verify or "full"),
        ssl_ca_bundle=_s("ssl_ca_bundle", base.auth_ldap_ssl_ca_bundle),
        timeout_seconds=_f("timeout_seconds", base.auth_ldap_timeout_seconds or 5.0),
        email_attr=_s("email_attr", base.auth_ldap_email_attr or "mail"),
        display_name_attr=_s(
            "display_name_attr", base.auth_ldap_display_name_attr or "displayName"
        ),
        department_attr=_s("department_attr", base.auth_ldap_department_attr or "department"),
        external_id_attr=_s("external_id_attr", base.auth_ldap_external_id_attr or "objectGUID"),
        auto_approve=_b("auto_approve", base.auth_ldap_auto_approve),
        default_role=_s("default_role", base.auth_ldap_default_role or "user"),
        login_disabled=_b("login_disabled", base.auth_ldap_login_disabled),
        local_register_enabled=_b(
            "local_register_enabled", base.auth_ldap_local_register_enabled
        ),
    )


def validate_effective_ldap_settings(settings: LdapSettings) -> None:
    """§3.6 rules 2/4/5 — a misconfigured directory is a config error, never
    a login-path crash. Raises :class:`LdapConfigError` (mapped to 422 at
    save time; to 503 at login time — the directory is "unavailable", ops
    must fix it).

    * rule 2: the search filter template is balanced + single-placeholder.
    * rule 4: ``require_tls`` (default) refuses a plaintext ``ldap://`` URI
      with no StartTLS — fails fast here, not mid-login.
    * rule 5: the directory can never grant admin (default_role in
      ``_ADMIN_ROLES`` is refused; JIT re-checks in the route).
    """
    from backend.services.ldap_provider import LdapConfigError, validate_filter_template

    if not settings.enabled:
        return  # disabled: nothing to validate (local-only)

    if not settings.server_uri:
        raise LdapConfigError("auth_ldap.server_uri is required when enabled")
    if not settings.service_bind_dn:
        raise LdapConfigError("auth_ldap.service_bind_dn is required when enabled")
    if not settings.user_search_base_dn:
        raise LdapConfigError("auth_ldap.user_search_base_dn is required when enabled")

    try:
        validate_filter_template(settings.user_search_filter)
    except Exception as exc:
        raise LdapConfigError(str(exc)) from exc

    plaintext = settings.server_uri.lower().startswith("ldap://")
    if plaintext and settings.require_tls and not settings.start_tls:
        raise LdapConfigError(
            "require_tls is on but the directory URI is plaintext ldap:// "
            "without StartTLS — use ldaps:// (636) or set start_tls=true "
            "(389); set require_tls=false only for explicit dev opt-in"
        )

    if settings.default_role in _ADMIN_ROLES:
        raise LdapConfigError(
            "default_role=admin is refused — admin is granted locally by an "
            "admin, never from the directory (§3.6 rule 5)"
        )
