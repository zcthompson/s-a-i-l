"""Guards for destructive PostgreSQL tests; never used by the application."""
from sqlalchemy.engine import make_url


def guarded_test_url(value: str, *, reset: bool = False) -> str:
    try:
        url = make_url(value)
    except Exception:
        raise ValueError("Invalid PostgreSQL test URL") from None
    import os
    restricted = (os.environ.get("SAIL_RESTRICTED_PERMCHECK") == "1"
                  and url.database == "sail_permcheck"
                  and url.username == "sail_permcheck_role"
                  and url.host in {"localhost", "127.0.0.1", "::1"})
    if url.get_backend_name() not in {"postgresql", "postgres"} or (url.database != "sail_test" and not restricted):
        raise ValueError("PostgreSQL tests require the explicit sail_test database")
    if reset:
        if os.environ.get("SAIL_ALLOW_TEST_SCHEMA_RESET") != url.database:
            raise ValueError("Explicit test-schema reset authorization is required")
    from backend.database import normalized_url
    return normalized_url(value)
