"""The SAIL_AUTH_ENABLED feature switch.

SAIL_API_KEYS reads like a credential but used to double as the auth
feature switch (non-empty → AUTH_ENABLED). The ruling: split it into an
explicit enable flag with a legacy fallback — the flag wins when set
(true→ON, false→OFF, anything else fails at import); when unset, the
legacy non-empty-keys behavior applies. The deploy wrappers default the
flag to `true`; the literal default key is kept as-is (ruling).
"""

import pytest
from backend.auth import API_KEYS, AUTH_ENABLED, resolve_auth_enabled
from backend.config import get_settings


def test_flag_unset_keys_set_auth_on():
    assert resolve_auth_enabled("", "key-a,key-b") is True
    assert resolve_auth_enabled("   ", "key-a") is True


def test_flag_unset_keys_empty_auth_off():
    assert resolve_auth_enabled("", "") is False
    assert resolve_auth_enabled("", "   ") is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True", "yes", "YES", "on", "On"])
def test_flag_on_values_enable_auth_even_without_keys(value):
    assert resolve_auth_enabled(value, "") is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "NO", "off", "OFF"])
def test_flag_off_values_disable_auth_even_with_keys(value):
    assert resolve_auth_enabled(value, "key-a") is False


@pytest.mark.parametrize("value", ["maybe", "2", "enabled", ""])
def test_flag_invalid_value_fails(value):
    if value == "":
        # "" is the unset sentinel — falls back to the legacy rule,
        # it is NOT an invalid value.
        assert resolve_auth_enabled(value, "key-a") is True
        return
    with pytest.raises(RuntimeError, match="SAIL_AUTH_ENABLED"):
        resolve_auth_enabled(value, "key-a")


def test_invalid_error_names_accepted_values():
    with pytest.raises(RuntimeError) as exc:
        resolve_auth_enabled("yes-please", "k")
    message = str(exc.value)
    assert "1/true/yes/on" in message
    assert "0/false/no/off" in message


def test_module_auth_enabled_consistent_with_resolver():
    """The import-time AUTH_ENABLED must equal the resolver applied to
    the live settings (whichever env the process runs under)."""
    settings = get_settings()
    assert AUTH_ENABLED is resolve_auth_enabled(settings.auth_enabled, API_KEYS)
    assert API_KEYS == settings.api_keys
