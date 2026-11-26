"""LDAP/AD directory authentication backend.

Directory auth maps into the existing
local ``User`` row (federated identity with a local identity anchor). This
module owns the ldap3 mechanics:

* bind as the configured service account → parameterized search (injection
  guarded — §3.6 rule 2) → bind as the found user DN with the user's
  password. Two consecutive operations: the service account may not have
  rights to authenticate arbitrary users on AD, so the user-password verify
  is a separate bind.
* AD ``objectGUID`` (16-byte BLOB) → hex string = ``external_id``; generic
  LDAP may point ``external_id_attr`` at ``entryUUID`` (string) instead.
* Transport (user direction 2026-09-14 — **both first-class**):
  ``ldaps://…:636`` = implicit TLS; ``ldap://…:389`` = plain socket with
  optional ``start_tls`` upgrade. The connection trust model comes from
  P0b's ``ssl_trust`` seam (full/skip/ca — custom CA bundle).

Error discipline (plan §3.6 rule 1): the backend never leaks
"which" failure — a wrong password and an unknown username both surface as
:class:`LdapAuthError` (route → unified 401); only a directory OUTAGE
surfaces as :class:`LdapUnavailable` (route → 503) so ops knows the
directory link failed without revealing anything about accounts.
"""

from __future__ import annotations

import binascii
import logging
import math
import re
from typing import Any

import ldap3
from ldap3 import Connection, Server, Tls
from ldap3.core import exceptions as ldap3_errors

from backend.services.ldap_settings import LdapSettings
from backend.services.ssl_trust import validate_pem

logger = logging.getLogger(__name__)

# Filter-template validation (§3.6 rule 2): exactly one {username}
# placeholder, the template must be a single balanced LDAP filter.
_USERNAME_RE = re.compile(r"\{username\}")
_FILTER_TEMPLATE_RE = re.compile(r"^[^(]*\((?:[^()]*|\([^()]*\))*\)$")


class LdapUnavailable(RuntimeError):
    """The directory could not be reached (or TLS/StartTLS failed). → 503."""


class LdapAuthError(RuntimeError):
    """Directory auth failed (unified — no existence oracle). → 401."""


class LdapConfigError(ValueError):
    """Settings are invalid (surfaced as 422 at save time)."""


def validate_filter_template(template: str) -> None:
    """§3.6 rule 2 — reject injection-capable search templates at save.

    Exactly one ``{username}`` placeholder, nothing else parameterized, and
    the template must be a single balanced LDAP filter.
    """
    if not template or not template.strip():
        raise LdapConfigError("user_search_filter is required")
    count = _USERNAME_RE.subn("", template)[1]
    if count != 1:
        raise LdapConfigError(
            "user_search_filter must contain exactly one {username} placeholder"
        )
    # Any OTHER {…} placeholder (beyond the single {username}) is rejected —
    # only the library's bound value may be parameterized.
    if re.search(r"\{[^}]*\}", _USERNAME_RE.sub("", template)):
        raise LdapConfigError(
            "user_search_filter may only parameterize {username}"
        )
    body = _USERNAME_RE.sub("", template)
    if not _FILTER_TEMPLATE_RE.match(body):
        raise LdapConfigError(
            "user_search_filter must be a balanced LDAP filter "
            "(e.g. (sAMAccountName={username}))"
        )


def validate_username_for_search(username: str) -> None:
    """§3.6 rule 2 — validate the value bound into the filter.

    Even though the library parameterizes the substitution, control
    characters are rejected up front (defense in depth; the plan's
    allowlist) and the 100-char cap of ``User.username`` is enforced.
    Raises :class:`LdapAuthError` — a rejected lookup is auth-failure
    shaped, never a config/leak message.
    """
    if not username or len(username) > 100:
        raise LdapAuthError("username not allowed")
    if re.search(r"[*()\\<>{}]", username):
        raise LdapAuthError("username not allowed")


def encode_guid(value: Any) -> str | None:
    """AD ``objectGUID`` (16-byte BLOB) → 32-char hex ``external_id``.

    Generic LDAP may hand us ``entryUUID`` (already a string) — passed
    through. Non-BLOB/non-string values yield ``None``.
    """
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        if len(value) != 16:
            return None
        try:
            return binascii.hexlify(bytes(value)).decode("ascii")
        except (ValueError, TypeError):
            return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _tls_config(settings: LdapSettings) -> Tls:
    """Build the ldap3 TLS object from the P0b trust model.

    ``full`` → verify chain + hostname (system CA store); ``skip`` →
    verification off (high-risk, admin-explicit); ``ca`` → the uploaded
    bundle only. ldap3 2.x ``Tls.validate`` takes stdlib ``ssl`` VerifyMode
    values (CERT_REQUIRED / CERT_NONE); for ``ca`` the PEM bundle goes via
    ``ca_certs_data=`` (ldap3's native path — verified working with a real
    self-signed cert). For a plain ``ldap://`` URI with start_tls the same
    object is attached to the server before StartTLS.
    """
    import ssl

    if settings.ssl_verify == "skip":
        return Tls(validate=ssl.CERT_NONE)
    if settings.ssl_verify == "ca":
        validate_pem(settings.ssl_ca_bundle)  # precise ValueError on bad PEM
        return Tls(validate=ssl.CERT_REQUIRED, ca_certs_data=settings.ssl_ca_bundle)
    return Tls(validate=ssl.CERT_REQUIRED)


def _build_server(settings: LdapSettings) -> Server:
    uri = (settings.server_uri or "").strip()
    if not uri:
        raise LdapConfigError("auth_ldap.server_uri is required")
    if uri.lower().startswith("ldaps://"):
        return Server(uri, use_ssl=True, tls=_tls_config(settings), get_info=ldap3.NONE)
    return Server(uri, tls=_tls_config(settings) if settings.start_tls else None, get_info=ldap3.NONE)


def _maybe_start_tls(conn: Connection, settings: LdapSettings) -> None:
    if not settings.start_tls:
        return
    try:
        if not conn.start_tls():
            raise LdapUnavailable("StartTLS failed")
    except Exception as exc:  # TLS upgrade failure = outage, not auth failure
        raise LdapUnavailable(f"StartTLS failed: {_short(exc)}") from exc


def _short(exc: BaseException, limit: int = 160) -> str:
    """One-line exception summary safe for logs (no secrets — §3.6 rule 3)."""
    text = " ".join(str(exc).split()) or exc.__class__.__name__
    return text[:limit]


def _receive_timeout(seconds: float | None) -> int | None:
    """ldap3 ``receive_timeout`` must be an INTEGER on non-Windows hosts.

    ldap3 (2.9.1) feeds the value straight to ``struct.pack('LL', ...)``
    for the ``SO_RCVTIMEO`` socket option on Linux; a float raises
    ``struct.error`` during connection open — before StartTLS — and every
    directory call surfaces as "directory unreachable" (controlled
    real-wire acceptance 2026-11-06, OpenLDAP 2.6.8). ``ceil`` keeps the
    bound conservative (never shorter than configured); zero/None means
    no explicit receive timeout.
    """
    if seconds is None or seconds <= 0:
        return None
    return int(math.ceil(seconds))


def authenticate(settings: LdapSettings, username: str, password: str) -> dict[str, Any]:
    """Directory-bind a username/password pair.

    Returns ``{"dn", "external_id", "attributes"}`` on success.

    * :class:`LdapAuthError` — wrong password, unknown user, or a username
      the directory refused to search (unified; route → 401).
    * :class:`LdapUnavailable` — directory unreachable / TLS failure
      (route → 503).
    * :class:`LdapConfigError` — settings invalid (route → 503, logged; a
      misconfigured directory must not 500 the login endpoint).
    """
    validate_username_for_search(username)
    # Some directories permit an unauthenticated bind with an empty password.
    if not password:
        raise LdapAuthError("directory authentication failed")
    from ldap3.utils.conv import escape_filter_chars

    conn: Connection | None = None
    try:
        validate_filter_template(settings.user_search_filter)
        conn = Connection(
            _build_server(settings),
            user=settings.service_bind_dn,
            password=settings.service_bind_password,
            auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if settings.start_tls else True,
            raise_exceptions=True,
            receive_timeout=_receive_timeout(settings.timeout_seconds),
        )
        search_filter = (
            settings.user_search_filter
            .replace("{username}", escape_filter_chars(username))
        )
        try:
            ok = conn.search(
                search_base=settings.user_search_base_dn,
                search_filter=search_filter,
                search_scope=ldap3.SUBTREE,
                attributes=list(dict.fromkeys([
                    settings.external_id_attr,
                    settings.email_attr,
                    settings.display_name_attr,
                    settings.department_attr,
                    "givenName",
                    "sn",
                ])),
                size_limit=1,
                time_limit=int(max(1, settings.timeout_seconds)),
            )
        except ldap3_errors.LDAPInvalidFilterError as exc:
            logger.warning("ldap: bad search filter: %s", _short(exc))
            raise LdapConfigError("invalid user_search_filter") from exc
        if not ok or not conn.entries:
            raise LdapAuthError("directory authentication failed")

        entry = conn.entries[0]
        dn = entry.entry_dn
        raw = dict(entry.entry_raw_attributes or {})

        def _first_raw(attr):
            # ldap3 raw_attributes values are lists; unwrap to the first.
            v = raw.get(attr)
            if isinstance(v, (list, tuple)):
                return v[0] if v else None
            return v

        external_id = encode_guid(_first_raw(settings.external_id_attr)) or encode_guid(_first_raw("entryUUID"))
        if external_id is None:
            logger.warning(
                "ldap: entry %s has no %s/entryUUID — cannot form external_id",
                dn, settings.external_id_attr,
            )
            raise LdapConfigError("directory entry has no stable id attribute")

        # User-password verify bind — a separate operation: the service
        # account may lack rights to authenticate others on AD.
        user_conn = Connection(
            conn.server,
            user=dn,
            password=password,
            auto_bind=False,
            receive_timeout=_receive_timeout(settings.timeout_seconds),
        )
        try:
            _maybe_start_tls(user_conn, settings)
            if not user_conn.bind():
                result = user_conn.result or {}
                if result.get("result") == 49:
                    raise LdapAuthError("directory authentication failed")
                raise LdapUnavailable("directory bind failed")
        except ldap3_errors.LDAPInvalidCredentialsResult:
            raise LdapAuthError("directory authentication failed")
        finally:
            try:
                user_conn.unbind()
            except Exception:
                pass

        return {
            "dn": dn,
            "external_id": external_id,
            "attributes": {
                "email": _first(entry, settings.email_attr),
                "display_name": _first(entry, settings.display_name_attr)
                or _display_name_fallback(entry, settings),
                "department": _first(entry, settings.department_attr),
            },
        }
    except (LdapAuthError, LdapConfigError):
        raise
    except ldap3_errors.LDAPExceptionError as exc:
        logger.warning("ldap: directory operation failed: %s", _short(exc))
        raise LdapUnavailable("directory unavailable") from exc
    except Exception as exc:
        logger.warning("ldap: unexpected error: %s", _short(exc))
        raise LdapUnavailable("directory unavailable") from exc
    finally:
        if conn is not None:
            try:
                conn.unbind()
            except Exception:
                pass


def _first(entry: Any, attr: str) -> str | None:
    try:
        values = getattr(entry, attr, None)
        if values:
            return str(values[0])
    except Exception:
        pass
    return None


def _display_name_fallback(entry: Any, settings: LdapSettings) -> str | None:
    """givenName + sn fallback (plan: display_name_attr default fallback)."""
    given = _first(entry, "givenName")
    sn = _first(entry, "sn")
    if given or sn:
        return " ".join(x for x in (given, sn) if x)
    return None


def _service_bind_ok(settings: LdapSettings) -> bool:
    """Bind as the service account only (the P2 test-connection probe).

    Raises :class:`LdapUnavailable` on any failure so the route returns a
    fixed unavailable message — never credentials, never the raw ldap3 text
    beyond the one-line summary logged server-side (§3.6 rule 3).
    """
    validate_filter_template(settings.user_search_filter)
    try:
        conn = Connection(
            _build_server(settings),
            user=settings.service_bind_dn,
            password=settings.service_bind_password,
            auto_bind=ldap3.AUTO_BIND_TLS_BEFORE_BIND if settings.start_tls else True,
            raise_exceptions=True,
            receive_timeout=_receive_timeout(settings.timeout_seconds),
        )
    except (LdapAuthError, LdapConfigError):
        raise
    except Exception as exc:
        logger.warning("ldap: service-account bind failed: %s", _short(exc))
        raise LdapUnavailable("directory unreachable") from exc
    try:
        return True
    finally:
        try:
            conn.unbind()
        except Exception:
            pass


