"""Migration regression tests for c7d8e9f0a1b2 (LDAP/directory auth fields, 0.2.0 P0).

docs/archive/PLAN_LDAP_AD_AUTH.md §5, gate: existing-DB copy —
  * ``upgrade`` keeps every row + its ``id`` + ``hashed_password`` intact;
  * new columns present with correct defaults (``auth_provider`` backfilled to
    'local', ``external_id``/``last_directory_login_at`` NULL, unique constraint
    on ``external_id``);
  * ``downgrade`` REFUSES while any ``auth_provider='ldap'`` row exists
    (preservation-first — plan §3.6 rule 8), and succeeds once none do.

Deterministic: runs against a scratch DB (not the dev DB, not production data
— charter §6). The alembic CLI is driven via subprocess with ``DATABASE_URL``
pointed at the scratch file (``env.py`` honours it over .env).
"""

import os
import subprocess
import sys

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PRE_LDAP_HEAD = "f3a4b5c6d7e8"  # single head immediately before c7d8e9f0a1b2
LDAP_REV = "c7d8e9f0a1b2"

FAKE_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _alembic(db_url: str, *args: str) -> str:
    """Run an alembic CLI command against ``db_url``; return combined output."""
    env = {**os.environ, "DATABASE_URL": db_url}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.stdout + proc.stderr


def _seed_users(db_path: str, n: int = 3) -> None:
    """Seed local users at the pre-LDAP head schema."""
    engine = create_engine(f"sqlite:///{db_path}", poolclass=None)
    with engine.connect() as conn:
        for i in range(1, n + 1):
            conn.execute(
                text(
                    "INSERT INTO users (username, email, hashed_password, display_name,"
                    " department, is_active, is_admin, approved, role)"
                    " VALUES (:u, :e, :h, :d, NULL, 1, :a, 1, 'user')"
                ),
                {
                    "u": f"legacyuser{i}",
                    "e": f"legacy{i}@test.local",
                    "h": FAKE_HASH,
                    "d": f"Legacy {i}",
                    "a": 1 if i == 1 else 0,
                },
            )
        conn.commit()
    engine.dispose()


def _tables(db_path: str):
    engine = create_engine(f"sqlite:///{db_path}", poolclass=None)
    try:
        return {t["name"]: t for t in inspect(engine).get_columns("users")}
    finally:
        engine.dispose()


def _query(db_path: str, sql: str):
    engine = create_engine(f"sqlite:///{db_path}", poolclass=None)
    try:
        with engine.connect() as conn:
            return conn.execute(text(sql)).fetchall()
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def scratch_db(tmp_path_factory):
    """Fresh scratch DB built to the pre-LDAP head, with seeded users."""
    root = tmp_path_factory.mktemp("ldap-mig")
    db_path = root / "scratch.db"
    db_url = f"sqlite:///{db_path}"
    out = _alembic(db_url, "upgrade", PRE_LDAP_HEAD)
    assert "Running upgrade" in out, out
    _seed_users(str(db_path))
    return db_url, db_path


def test_single_head_descends_from_ldap_revision():
    """The linear migration graph has one head and retains the LDAP ancestor."""
    out = _alembic("sqlite:///:memory:", "heads")
    scripts = ScriptDirectory.from_config(Config(os.path.join(REPO_ROOT, "alembic.ini")))
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert out.strip() == f"{heads[0]} (head)"
    assert LDAP_REV in {revision.revision for revision in scripts.walk_revisions(
        base=LDAP_REV, head=heads[0],
    )}


def test_upgrade_preserves_rows_ids_and_passwords(scratch_db):
    db_url, db_path = scratch_db
    before = _query(
        str(db_path),
        "SELECT id, username, hashed_password FROM users ORDER BY id",
    )
    assert len(before) == 3

    out = _alembic(db_url, "upgrade", "head")
    assert LDAP_REV in out, out

    after = _query(
        str(db_path),
        "SELECT id, username, hashed_password FROM users ORDER BY id",
    )
    # Every row, original ids, and the original hashes survive the batch rebuild.
    assert after == before

    # New columns present with the right shape/defaults.
    cols = _tables(str(db_path))
    assert cols["auth_provider"]["nullable"] is False
    assert cols["hashed_password"]["nullable"] is True
    assert cols["external_id"]["nullable"] is True
    assert cols["last_directory_login_at"]["nullable"] is True
    # Backfill: pre-existing rows are 'local'.
    providers = _query(str(db_path), "SELECT auth_provider FROM users")
    assert all(p[0] == "local" for p in providers)

    # external_id is UNIQUE (idempotent JIT link depends on it). SQLite reflects
    # a batch-rebuild UNIQUE constraint as an index on the column with origin
    # 'u' (auto-generated name, or the named index in some paths) — assert the
    # invariant (a unique index covering external_id), not a literal index name.
    idx = _query(str(db_path), "PRAGMA index_list(users)")
    unique_cols = set()
    engine = create_engine(f"sqlite:///{db_path}", poolclass=None)
    try:
        for r in idx:
            name, unique = r[1], r[2]
            if unique:
                for col in _query(str(db_path), f"PRAGMA index_info('{name}')"):
                    unique_cols.add(col[2])
    finally:
        engine.dispose()
    assert "external_id" in unique_cols


def test_upgrade_is_idempotent_on_rerun(scratch_db):
    db_url, _ = scratch_db
    out = _alembic(db_url, "upgrade", "head")
    # Second run at the same head is a no-op.
    assert "No upgrade path applied" in out or "Running upgrade" not in out


def test_downgrade_refuses_while_ldap_rows_exist(scratch_db):
    db_url, db_path = scratch_db
    # A directory-managed row (NULL local hash) blocks the downgrade.
    engine = create_engine(f"sqlite:///{db_path}", poolclass=None)
    with engine.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO users (username, email, hashed_password, display_name,"
                " is_active, is_admin, approved, role, auth_provider, external_id)"
                " VALUES ('diruser', 'dir@test.local', NULL, 'Dir User', 1, 0, 1,"
                " 'user', 'ldap', 'guid-hex-123')"
            )
        )
        conn.commit()
    engine.dispose()

    out = _alembic(db_url, "downgrade", PRE_LDAP_HEAD)
    assert "Refusing to downgrade" in out, out
    # Columns must still be present (the failed downgrade left the schema alone).
    assert "auth_provider" in _tables(str(db_path))


def test_downgrade_succeeds_without_ldap_rows(tmp_path):
    """Clean path: with no 'ldap' rows the downgrade restores the old schema."""
    db_path = tmp_path / "clean.db"
    db_url = f"sqlite:///{db_path}"
    out = _alembic(db_url, "upgrade", "head")
    assert LDAP_REV in out, out

    out = _alembic(db_url, "downgrade", PRE_LDAP_HEAD)
    assert "Refusing to downgrade" not in out, out
    cols = _tables(str(db_path))
    assert "auth_provider" not in cols
    assert "external_id" not in cols
    assert "last_directory_login_at" not in cols
    assert cols["hashed_password"]["nullable"] is False
