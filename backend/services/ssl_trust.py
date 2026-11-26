"""Connection trust model (SSL/TLS) — one seam for every outbound connection.

docs/archive/PLAN_LDAP_AD_AUTH.md §3.4 / P0b (user direction 2026-09-14): inference,
Docling Serve, and LDAP/AD each get an independent ``ssl_verify`` mode plus a
custom CA bundle:

* ``full`` (default) — verify chain + hostname exactly as today (``httpx``
  default, ``ssl.create_default_context()``). **No behavior change.**
* ``skip`` — TLS stays ON when the scheme is ``https``/``ldaps``, but
  certificate verification is OFF. High-risk (MITM); the admin UI labels it
  as such. For httpx: ``verify=False``.
* ``ca`` — verify against an uploaded CA bundle ONLY (custom/self-signed
  internal CAs). The PEM is written to a process-local tempfile and loaded
  via ``cafile=`` (the stdlib ``cadata=`` kwarg has a parsing quirk that
  rejects otherwise-valid certs — ``cafile`` is the verified path).

Stdlib ``ssl`` only — no new dependency. ``full`` returns plain ``True`` so
callers can pass the value straight into httpx's ``verify=``.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import tempfile
from functools import lru_cache

SSL_VERIFY_MODES = ("full", "skip", "ca")

# Bounded cache of built SSLContexts keyed by (mode, pem sha256). Clients are
# constructed per request in this app (AIClient/DoclingService take no shared
# state), so building a tempfile + context per call would be wasteful; the
# PEM rarely changes (admin edit), so an LRU keeps this O(1) per call.
@lru_cache(maxsize=8)
def _build_ca_context(pem: str, pem_sha: str) -> ssl.SSLContext:
    """Build a verifying context from a CA bundle PEM (via tempfile+cafile)."""
    # 0600 so the bundle never sits world-readable on a shared host, even
    # transiently. The bundle is a trust anchor (not a credential), but we do
    # not publish it needlessly.
    fd, path = tempfile.mkstemp(prefix="sil-ca-bundle-", suffix=".pem")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(pem)
        ctx = ssl.create_default_context(cafile=path)
    finally:
        os.unlink(path)  # context retains its own copy of the trust store
    return ctx


def validate_pem(pem: str) -> None:
    """Raise ``ValueError`` unless ``pem`` is a loadable CA bundle.

    Called at settings-save time so a broken bundle 422s immediately with a
    precise reason instead of failing mid-login/mid-conversion in production.
    Empty/whitespace-only is accepted (it means "no custom bundle" — only
    meaningful when the mode is not ``ca``).
    """
    if not pem or not pem.strip():
        return
    ctx = ssl.create_default_context()
    fd, path = tempfile.mkstemp(prefix="sil-ca-validate-", suffix=".pem")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(pem)
        ctx.load_verify_locations(cafile=path)
    except ssl.SSLError as exc:  # precise, actionable
        raise ValueError(
            f"Invalid CA bundle: {exc}. Expected one or more PEM-encoded "
            "X.509 certificates between -----BEGIN CERTIFICATE----- and "
            "-----END CERTIFICATE----- markers."
        ) from exc
    finally:
        os.unlink(path)


def resolve_verify(
    verify_mode: str = "full", ca_bundle_pem: str = ""
) -> bool | ssl.SSLContext:
    """Resolve the trust mode into an httpx ``verify=`` value.

    Returns ``True`` (full), ``False`` (skip), or a built ``ssl.SSLContext``
    (ca). ``validate_pem`` is applied to the ``ca`` bundle so a bad PEM raises
    ``ValueError`` here (the admin route maps that to 422).
    """
    mode = (verify_mode or "").strip().lower()
    if not mode:
        # Unset/empty/whitespace normalizes to the safe default. Callers
        # (AIClient/DoclingService) already coalesce None→"full" before the
        # seam, and DB overrides never store empty strings, so this only
        # guards the direct/edge path — keep it consistent with "full".
        mode = "full"
    if mode not in SSL_VERIFY_MODES:
        raise ValueError(
            f"ssl_verify must be one of {SSL_VERIFY_MODES} (got {mode!r})"
        )
    if mode == "full":
        return True
    if mode == "skip":
        return False
    # mode == "ca"
    validate_pem(ca_bundle_pem)
    pem = (ca_bundle_pem or "").strip()
    if not pem:
        raise ValueError("ssl_verify='ca' requires a CA bundle PEM")
    return _build_ca_context(pem, hashlib.sha256(pem.encode("utf-8")).hexdigest())
