"""Auth provider seam (LDAP/AD federated identity).

A pluggable provider layer so directory
(LDAP/AD) authentication runs ALONGSIDE local (bcrypt) auth without
weakening or touching the local path (never weaken auth).

The seam is deliberately thin and lives in the service layer (business
logic, never routes). ``routes/auth.py`` resolves a backend and
calls ``authenticate``; everything downstream (is_active, approval gate, JWT
shape, ``CustomerUser`` authorization) is UNCHANGED — directory login maps
into the same local ``User`` row (federated identity with a local identity
anchor, §3.1).

Provider resolution (§3.1 table):
* local row with ``auth_provider='local'`` (or default)  → LOCAL ONLY —
  local-first precedence; a local account can never be directory-taken.
* local row with ``auth_provider='ldap'``                → DIRECTORY ONLY.
* no local row                                           → DIRECTORY when
  enabled+configured (JIT create), else LOCAL (today's exact path — unknown
  usernames fail uniformly through LocalBackend's 401).
* directory disabled/unconfigured                        → LOCAL, and local
  rows with NULL hash (future directory rows) fail uniformly — the local
  path must not accidentally authenticate a directory identity.

``LdapBackend.authenticate`` returns a :class:`DirectoryIdentity` on
success (the route performs JIT row link/create), ``None`` on auth
failure, and raises :class:`AuthUnavailable` when the directory is
unreachable/misconfigured (route → fixed 503 message).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sqlalchemy.orm import Session

# Import the module (not the symbol) so ``verify_password`` is resolved as
# an attribute on ``backend.auth`` at CALL time. The auth regression tests
# patch ``backend.auth.verify_password`` (and ``backend.routes.auth.
# verify_password``) with a deterministic double; an import-bound
# ``from backend.auth import verify_password`` would capture the real bcrypt
# verifier and bypass those patches, causing 401s against the known fake
# test hashes. Resolving through the module object keeps the local path
# byte-identical to the pre-seam ``routes/auth.py`` behaviour AND honors the
# established test seam (P0 gate: existing auth tests are the regression
# gate — local login must be unchanged).
import backend.auth
from backend.models.use_case import User
from backend.services.user_service import UserService


class AuthUnavailable(RuntimeError):
    """The directory provider is unreachable or misconfigured (route → 503).

    Carries a fixed, non-revealing message: ops knows the directory link
    failed; a login attempt learns nothing about accounts (§3.6 rule 1).
    """

    MESSAGE = "Directory authentication unavailable; local accounts can still sign in."

    def __init__(self, detail: str = ""):
        super().__init__(detail)
        self.detail = detail


@dataclass
class DirectoryIdentity:
    """A verified directory identity (not yet mapped to a local row).

    The route links by ``external_id`` (idempotent) or JIT-creates the local
    ``User`` row from ``email``/``display_name``/``department``.
    """

    dn: str
    external_id: str
    email: str | None
    display_name: str | None
    department: str | None


@runtime_checkable
class AuthBackend(Protocol):
    """A login provider.

    ``authenticate`` returns the authenticated identity — a local ``User``
    row for :class:`LocalBackend`, a :class:`DirectoryIdentity` for
    :class:`LdapBackend` — or ``None`` on failure (the route maps that to a
    unified 401 + a recorded failed attempt — no existence/provider oracle).
    May raise :class:`AuthUnavailable` for directory outages (503).
    """

    name: str

    def authenticate(self, db: Session, username: str, password: str) -> User | DirectoryIdentity | None:
        ...


class LocalBackend:
    """The existing local (bcrypt/sha512) login path, moved verbatim.

    Behavior-preserving (P0 gate): ``get_by_username`` + ``verify_password``
    exactly as ``routes/auth.py`` did before the seam. A ``None``
    ``hashed_password`` (directory-managed rows) is a failure, never an
    error — local rows always carry a hash.
    """

    name = "local"

    def authenticate(self, db: Session, username: str, password: str) -> User | None:
        user = UserService.get_by_username(db, username)
        if user is None:
            return None
        if user.hashed_password is None:
            return None
        # Resolve ``verify_password`` on ``backend.auth`` at call time (not the
        # import-bound symbol) so test doubles that patch the module attribute
        # take effect — see the module-import note above.
        if not backend.auth.verify_password(password, user.hashed_password):
            return None
        return user


class LdapBackend:
    """Directory (LDAP/AD) login — verify against the directory (§3.1).

    Reads the effective settings at call time (env → SystemConfig ``auth_ldap``
    overrides). ``LdapConfigError`` from settings/provider is an outage
    shape for the login path (fixed 503 — a misconfigured directory must
    not 500 login or reveal configuration details).
    """

    name = "ldap"

    def authenticate(self, db: Session, username: str, password: str) -> DirectoryIdentity | None:
        from backend.services import ldap_provider
        from backend.services.ldap_settings import (
            effective_ldap_settings,
            validate_effective_ldap_settings,
        )

        try:
            settings = effective_ldap_settings(db)
            validate_effective_ldap_settings(settings)
            result = ldap_provider.authenticate(settings, username, password)
        except ldap_provider.LdapAuthError:
            return None
        except (ldap_provider.LdapUnavailable, ldap_provider.LdapConfigError) as exc:
            raise AuthUnavailable(str(exc)) from exc
        return DirectoryIdentity(
            dn=result["dn"],
            external_id=result["external_id"],
            email=result["attributes"]["email"],
            display_name=result["attributes"]["display_name"],
            department=result["attributes"]["department"],
        )


def resolve_auth_backend(db: Session, username: str) -> AuthBackend:
    """Return the login backend for ``username`` (§3.1 resolution table).

    * local row, ``auth_provider='local'`` (incl. NULL/default) → LOCAL ONLY.
    * local row, ``auth_provider='ldap'`` → DIRECTORY ONLY.
    * no local row → DIRECTORY when enabled+validated, else LOCAL (the
      unknown username then 401s through the local path — no oracle).
    """
    row = UserService.get_by_username(db, username)
    if row is not None:
        if (row.auth_provider or "local") == "ldap":  # type: ignore[operator]
            return LdapBackend()
        return LocalBackend()

    # Unknown username — directory only when it is actually usable.
    try:
        from backend.services.ldap_settings import (
            effective_ldap_settings,
            validate_effective_ldap_settings,
        )

        settings = effective_ldap_settings(db)
        if settings.enabled and not settings.login_disabled:
            validate_effective_ldap_settings(settings)
            return LdapBackend()
    except Exception:
        # Misconfigured/disabled directory: fall through to the local path
        # (unknown user → uniform 401). Never leak the config problem into
        # the login response shape.
        pass
    return LocalBackend()


def link_or_create_directory_user(
    db: Session,
    identity: DirectoryIdentity,
    username: str,
    *,
    auto_approve: bool,
    default_role: str,
) -> User:
    """Map a verified :class:`DirectoryIdentity` to the local ``User`` row.

    * existing row with the same ``external_id`` → re-login (touch
      ``last_directory_login_at`` only);
    * existing row with the same ``username`` and NULL hash → idempotent JIT
      link (fill ``external_id``);
    * otherwise JIT create — ``auth_provider='ldap'``, ``hashed_password``
      NULL (the directory is the password authority), ``approved`` per the
      auto-approve policy, role = ``default_role`` (``admin`` is refused —
      §3.6 rule 5, re-checked here as defense in depth).

    ``CustomerUser`` is never touched (directory groups grant nothing —
    customer access stays admin-driven).
    """
    from datetime import UTC, datetime

    from sqlalchemy.exc import IntegrityError

    if default_role == "admin":
        default_role = "user"  # rule 5 — the route validates settings too

    by_external = (
        db.query(User).filter(User.external_id == identity.external_id).first()
        if identity.external_id
        else None
    )
    if by_external is not None:
        # Idempotent re-login (second and later directory sign-ins).
        try:
            by_external.last_directory_login_at = datetime.now(UTC)
            db.commit()
            db.refresh(by_external)
        except IntegrityError:
            db.rollback()
        return by_external

    existing = UserService.get_by_username(db, username)
    if existing is not None:
        if existing.hashed_password is not None:
            # Local account owns this username — local-first precedence
            # already prevented directory resolution here; a directory login
            # must NOT overwrite a local identity (deterministic "local
            # wins", surfaced as a failure, not a merge).
            raise AuthUnavailable(
                "username collision: local account wins (directory link refused)"
            )
        # NULL-hash row with the same name — link it (admin re-link path too).
        try:
            existing.external_id = identity.external_id
            existing.auth_provider = "ldap"
            existing.last_directory_login_at = datetime.now(UTC)
            db.commit()
            db.refresh(existing)
        except IntegrityError:
            # external_id already claimed by another row — do not merge.
            db.rollback()
            raise AuthUnavailable(
                "external_id conflict: directory identity already linked "
                "to another account"
            )
        return existing

    user = User(
        username=username,
        email=identity.email or f"{username}@directory.local",
        hashed_password=None,  # directory-managed: no local hash
        display_name=identity.display_name or username,
        department=identity.department,
        role=default_role,
        is_admin=0,
        approved=1 if auto_approve else 0,
        is_active=1,
        auth_provider="ldap",
        external_id=identity.external_id,
        last_directory_login_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except IntegrityError:
        # email/username/external_id uniqueness — a directory identity
        # colliding with an existing account must 401 (via the route's
        # AuthUnavailable mapping), never 500 the login endpoint.
        db.rollback()
        raise AuthUnavailable(
            "username collision: an account already owns this identity"
        )
    return user
