"""SEC-01 regression tests: JWT signing-secret startup hardening.

The public default secret that shipped in ``docker-compose.yml``
(``changeme-changeme-changeme-changeme``) was accepted by the backend
startup guard, so a deployment started without an override could have
JWTs forged with a known key. These tests pin the hardened behavior:

- ``backend.auth.validate_jwt_secret`` rejects empty, documented
  placeholder, and too-short secrets, and accepts a proper random one.
- Importing ``backend.auth`` in a fresh interpreter fails fast (before
  any route is mounted) for every rejected secret value.
- ``docker-compose.yml`` no longer contains the public default and
  requires the variable (``:?`` form, no ``:-`` fallback).

Run: pytest tests/backend/test_jwt_secret_startup.py -v
"""

import os
import subprocess
import sys

import pytest
import yaml
from backend.auth import validate_jwt_secret

# The secret that was committed as the compose default. It must be
# rejected at startup now, not merely documented as "change me".
PUBLIC_COMPOSE_DEFAULT = "changeme-changeme-changeme-changeme"
LEGACY_PLACEHOLDER = "change-me-in-production"

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Unit-level: validate_jwt_secret
# ---------------------------------------------------------------------------


class TestValidateJwtSecret:
    @pytest.mark.parametrize(
        "secret",
        [
            "",
            LEGACY_PLACEHOLDER,
            PUBLIC_COMPOSE_DEFAULT,
        ],
        ids=["empty", "legacy-placeholder", "public-compose-default"],
    )
    def test_rejects_empty_and_documented_placeholders(self, secret):
        with pytest.raises(RuntimeError, match="SAIL_JWT_SECRET"):
            validate_jwt_secret(secret)

    @pytest.mark.parametrize(
        "secret",
        [
            "a" * 31,
            "x" * 20,
            PUBLIC_COMPOSE_DEFAULT[:31],
        ],
        ids=["31-chars", "20-chars", "public-default-truncated-to-31"],
    )
    def test_rejects_short_secrets(self, secret):
        assert secret not in (LEGACY_PLACEHOLDER, PUBLIC_COMPOSE_DEFAULT)
        with pytest.raises(RuntimeError, match="too short"):
            validate_jwt_secret(secret)

    def test_accepts_a_proper_random_length_secret(self):
        # Mirrors `openssl rand -hex 32` (64 hex chars) without any
        # dependency on openssl at test time.
        validate_jwt_secret("0f8d3c2a1b9e7f4a6c5d8e2f1a0b9c3d5e6f7081a2b3c4d5")

    def test_accepts_the_test_suite_secret(self):
        # The shared test constant must keep passing the guard so the
        # suite itself cannot go red when the minimum is tightened.
        validate_jwt_secret("test-secret-for-unit-tests-only-00000000")


# ---------------------------------------------------------------------------
# Import-time enforcement in a fresh interpreter (process isolation:
# backend.auth is already imported in the pytest process, so the real
# startup behavior can only be observed in a subprocess).
# ---------------------------------------------------------------------------

_IMPORT_PROBE = "import backend.auth"


@pytest.mark.parametrize(
    ("secret", "match"),
    [
        (None, "SAIL_JWT_SECRET is not set"),
        (LEGACY_PLACEHOLDER, "documented placeholder value"),
        (PUBLIC_COMPOSE_DEFAULT, "documented placeholder value"),
        ("short", "too short"),
    ],
    ids=["unset", "legacy-placeholder", "public-compose-default", "short"],
)
def test_fresh_import_refuses_bad_secret(secret, match):
    env = dict(os.environ)
    env.pop("SAIL_JWT_SECRET", None)
    if secret is not None:
        env["SAIL_JWT_SECRET"] = secret
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode != 0, (
        f"import backend.auth must fail with secret={secret!r}; "
        f"stderr: {result.stderr[-800:]}"
    )
    assert match in result.stderr, (
        f"expected refusal message {match!r}; stderr: {result.stderr[-800:]}"
    )


def test_fresh_import_accepts_valid_secret():
    env = dict(os.environ)
    env["SAIL_JWT_SECRET"] = "ci-seed-only-not-a-real-secret-0000000000"
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        env=env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"import backend.auth must succeed for a valid secret; "
        f"stderr: {result.stderr[-800:]}"
    )


# ---------------------------------------------------------------------------
# Deployment configuration: docker-compose.yml
# ---------------------------------------------------------------------------


def test_compose_requires_secret_without_public_default():
    path = os.path.join(REPO_ROOT, "docker-compose.yml")
    with open(path, "r", encoding="utf-8") as fh:
        compose = yaml.safe_load(fh)

    environment = compose["services"]["app"]["environment"]
    jwt_entries = [line for line in environment if line.startswith("SAIL_JWT_SECRET=")]
    assert jwt_entries, "docker-compose.yml must pass SAIL_JWT_SECRET"
    entry = jwt_entries[0]

    # No `:-` default may remain (that is what supplied the public key).
    assert ":-" not in entry, f"compose must not supply a JWT secret default: {entry}"
    # The variable form must require the value (:?) so compose itself
    # refuses to start without an override.
    assert ":?" in entry, f"compose must require the JWT secret: {entry}"
    # The previously committed public value must not appear anywhere in
    # the compose file.
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read()
    assert PUBLIC_COMPOSE_DEFAULT not in raw
