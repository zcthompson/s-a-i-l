
"""Shared test database setup for all backend test modules.

Patches create_engine so ALL code paths use the same test engine, whether
they create engines themselves (get_session) or import them.

Run: pytest tests/backend/ -v
"""

import atexit
import os
import tempfile
from unittest.mock import patch as _patch

import pytest

# Load .env so the AI endpoint/model/key configured there are functional in
# tests too (same .env the app reads). Then force DB + JWT to test values:
# hard-set (not setdefault) so a .env DATABASE_URL can never leak the dev DB
# into the test run.
from dotenv import load_dotenv as _load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine as _orig_create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_load_dotenv()


def _fresh_test_db_path():
    """A new, empty database file per test session, removed at exit.

    A fixed persistent path let existing tables survive between runs, and
    ``create_all()`` never rebuilds an existing table, so local runs could
    test an outdated schema (for example without AUTOINCREMENT) while CI built
    a fresh one. A per-session file also keeps concurrent runs isolated.
    """
    fd, path = tempfile.mkstemp(prefix="sail_test_", suffix=".db")
    os.close(fd)
    os.unlink(path)  # SQLite creates the file on first connect.

    def _cleanup():
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                os.unlink(path + suffix)
            except FileNotFoundError:
                pass

    atexit.register(_cleanup)
    return path


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
IS_POSTGRES = bool(TEST_DATABASE_URL)
if IS_POSTGRES:
    from backend.test_database import guarded_test_url
    TEST_DATABASE_URL = guarded_test_url(TEST_DATABASE_URL, reset=True)
TEST_DB_PATH = _fresh_test_db_path()
os.environ["SAIL_TEST_DB_PATH"] = TEST_DB_PATH
os.environ["SAIL_JWT_SECRET"] = "test-secret-for-unit-tests-only-00000000"
os.environ["SAIL_DATABASE_URL"] = TEST_DATABASE_URL or f"sqlite:///{TEST_DB_PATH}"
if IS_POSTGRES:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL
else:
    os.environ.pop("DATABASE_URL", None)
# Run customer-knowledge normalization inline (same test connection, no
# background thread) instead of the production worker thread:
# deterministic under the StaticPool test DB, and exercises the exact
# same normalize_record code path (see
# customer_knowledge_service._dispatch). One test exercises the real
# worker-thread path explicitly.
os.environ["SAIL_KNOWLEDGE_ASYNC"] = "0"

# Deterministic default: knowledge normalization tests must NOT call the
# configured LLM. Enrichment-specific tests set this to "1"
# and mock AIClient instead.
os.environ["SAIL_KNOWLEDGE_ENRICHMENT"] = "0"

# Monkey-patch hash_password (avoids bcrypt crashes on Python 3.12)
import backend.auth

backend.auth.hash_password = (
    lambda pw: "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
)

# Create the shared test engine FIRST, before importing any models
if IS_POSTGRES:
    import subprocess
    engine = _orig_create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        assert connection.dialect.name == "postgresql"
        from sqlalchemy.engine import make_url
        assert connection.execute(text("SELECT current_database()")).scalar_one() == make_url(TEST_DATABASE_URL).database
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    subprocess.run([os.sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
else:
    engine = _orig_create_engine(
        f"sqlite:///{TEST_DB_PATH}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

from tests.backend import database_support

database_support.engine = engine

# Patch create_engine globally so any create_engine() call returns our engine
def _test_create_engine(*args, **kwargs):
    return engine

import importlib
import pkgutil

import backend.models

with _patch("sqlalchemy.create_engine", _test_create_engine):
    with _patch("sqlalchemy.engine.create_engine", _test_create_engine):
        with _patch("backend.models.use_case.create_engine", _test_create_engine):
            # Import models AFTER patching. Import EVERY model module (not a
            # hand-maintained list) so every table is registered in
            # Base.metadata before create_all below. A hand-maintained list
            # silently drops tables from the test database when new model
            # files are added (customer_knowledge / sales_evaluation caused
            # "no such table" fixture errors in the six db_session fixtures).
            for _module in pkgutil.iter_modules(backend.models.__path__):
                importlib.import_module(f"backend.models.{_module.name}")
            from backend.models.use_case import Base, User

# Create tables (after patching, all create_engine calls go to our engine)
if not IS_POSTGRES:
    Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def _route_runtime_engines_to_test_engine(monkeypatch, db_session):
    """Keep manual route/auth sessions on the instrumented fixture engine."""
    def runtime_engine(*args, **kwargs):
        return db_session.get_bind()

    monkeypatch.setattr("backend.models.use_case.create_engine", runtime_engine)
    monkeypatch.setattr("backend.database.create_engine", runtime_engine)


def pytest_collection_modifyitems(config, items):
    """Skip `real_inference` tests when SAIL_SKIP_REAL_INFERENCE=1.

    Real-inference tests (marked `real_inference`) call a live model
    endpoint — the dev LAN vLLM — so they cannot pass in environments
    without that endpoint (e.g. GitHub CI runners). Dev/local runs leave
    the flag unset, so the model-liveness tests run there as usual.
    """
    if os.environ.get("SAIL_SKIP_REAL_INFERENCE") == "1":
        skip_marker = pytest.mark.skip(
            reason=(
                "real_inference: requires a live model endpoint "
                "(SAIL_AI_ENDPOINT) that is not reachable in this "
                "environment; leave SAIL_SKIP_REAL_INFERENCE unset "
                "to run them"
            )
        )
        for item in items:
            if item.get_closest_marker("real_inference") is not None:
                item.add_marker(skip_marker)


@pytest.fixture(autouse=True)
def _mock_docling_by_default():
    """Deterministic Docling mock for the knowledge processing path.

    Automated tests must never call the real Docling endpoint The service module's ``DoclingService`` reference is
    replaced with a deterministic fake (success + Markdown). Test files
    that need a specific failure class (unavailable / timeout /
    failure / partial / empty) re-patch ``cks.DoclingService`` per test.
    ``test_docling_service.py`` is unaffected — it exercises the real
    class against its own ``httpx.MockTransport``.
    """
    from unittest.mock import patch as _p

    import backend.services.customer_knowledge_service as cks
    from backend.services.docling_service import DoclingConversionResult

    class _FakeDocling:
        name = "docling"

        def supported_extensions(self):
            from backend.services.docling_service import DOCLING_SUPPORTED_EXTENSIONS

            return frozenset(DOCLING_SUPPORTED_EXTENSIONS)

        def convert(self, file_bytes, filename, content_type="application/octet-stream"):
            res = self.convert_to_markdown(file_bytes, filename, content_type)
            res.processor = "docling"
            return res

        def __init__(self, *args, **kwargs):
            pass

        def convert_to_markdown(self, file_bytes, filename, content_type="application/octet-stream"):
            return DoclingConversionResult(
                markdown=f"# Normalized {filename}\n\nconverted: {len(file_bytes)} bytes\n",
                status="success",
                partial=False,
                processing_time_seconds=0.01,
            )

        def health(self):
            return {"status": "ok"}

    with _p.object(cks, "build_converter", lambda db: _FakeDocling()):
        yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the global in-memory rate limiter between tests.

    The limiter is process-global state in ``backend.main`` (imported from
    ``backend.rate_limit``); with ``SAIL_API_KEYS`` set in the dev
    ``.env`` it counts every API request across the whole suite and trips
    its 1000/hour budget partway through a full run — 429s on unrelated
    tests (observed: test_user_management + later files flaking at ~900th
    test). Per-test reset keeps the suite deterministic without weakening
    rate-limit behavior (the middleware's own logic is unchanged and
    still exercised per test).
    """
    from backend.rate_limit import rate_limiter

    rate_limiter.requests.clear()
    yield
    rate_limiter.requests.clear()


@pytest.fixture(scope="function")
def db_session():
    """Fresh session per test with full rollback.

    The session is bound to the ENGINE, not to a pre-begun connection
    transaction: with an engine-bound session, session.commit() issues a
    real DBAPI COMMIT. The old design (session bound to the fixture's own
    ``conn.begin()`` transaction) made session.commit() a logical-only
    no-op at the DBAPI level, leaving the per-test seed uncommitted inside
    the open driver transaction — where any ROLLBACK from another session
    on the same shared StaticPool connection (e.g. the auth
    junction-lookup session's in-request teardown) could destroy it
    mid-test (flake, layer 2). All tables are cleared (not a
    hand-maintained subset) so residue from any seeded table (e.g.
    score_history) cannot leak across tests via rowid reuse.
    """
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()

    # Foreign-key enforcement stays OFF, matching runtime SQLite (the app never
    # enables it). Declared ON DELETE actions therefore never fire, so delete
    # paths must clean up children explicitly (ER-11/ER-12). This PRAGMA runs
    # before any write opens a transaction, so it takes effect; SQLite ignores
    # foreign_keys changes inside a transaction.
    database_support.reset_tables(session)

    if session.query(User).count() == 0:
        admin = User(
            username="admin", email="admin@test.local",
            hashed_password=backend.auth.hash_password("admin"),
            display_name="Administrator", department="IT",
            is_admin=1, approved=1, is_active=1,
        )
        session.add(admin)
        session.commit()

    session.execute(text("SAVEPOINT test_savepoint"))

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client():
    """TestClient with dependency override so app uses test engine."""

    from backend.dependencies import get_db

    def override_get_db():
        sess = sessionmaker(bind=engine)()
        try:
            yield sess
        finally:
            sess.close()

    with _patch("backend.auth.hash_password", side_effect=lambda pw: "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"):
        from backend.main import app
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()
