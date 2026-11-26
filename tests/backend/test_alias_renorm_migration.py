"""Revision 0030 re-normalizes stored alias norms (gap #6) and preserves data.

Disposable round-trip (the test_netsuite_migration.py pattern): seed aliases
in the LEGACY norm at 0029, upgrade to head, and pin the re-normalization —
ASCII norms untouched, full-width norms recomputed, an oldest-id-wins
collision dedupe, and the removal of a row whose new norm equals a customer
name. Downgrade restores the legacy norms for survivors; deleted rows are
unrecoverable; re-upgrade is stable (fixed-point).
"""
import os
import sqlite3
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _new_norm(value):
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _old_norm(value):
    return " ".join((value or "").lower().split())


def _run(env, *args):
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr


def _rows(db):
    return {r[0]: (r[1], r[2]) for r in
            db.execute("SELECT id, alias, alias_norm FROM customer_aliases").fetchall()}


def test_renormalize_migration_disposable_roundtrip(tmp_path):
    path = tmp_path / "renorm-migration.db"
    env = {**os.environ, "SAIL_DATABASE_URL": f"sqlite:///{path}", "DATABASE_URL": f"sqlite:///{path}"}

    _run(env, "upgrade", "0029_netsuite_import")
    with sqlite3.connect(path) as db:
        db.executescript("""
            INSERT INTO customers(id, name) VALUES (900101, 'Alpha Co');
            INSERT INTO customers(id, name) VALUES (900102, 'Beta Co');
            INSERT INTO customers(id, name) VALUES (900103, 'Strasse');
            -- ASCII alias: the norm is unchanged by the re-normalization.
            INSERT INTO customer_aliases(id, customer_id, alias, alias_norm, created_by, created_at)
            VALUES (1, 900101, 'Alpha Group', 'alpha group', 'admin', '2026-01-01 00:00:00');
            -- Full-width alias: stored in the legacy (lowered full-width) norm.
            INSERT INTO customer_aliases(id, customer_id, alias, alias_norm, created_by, created_at)
            VALUES (2, 900102, 'ＢＥＴＡ ＧＲＯＵＰ', 'ｂｅｔａ ｇｒｏｕｐ', 'admin', '2026-01-02 00:00:00');
            -- Collision pair under the NEW norm (distinct under the legacy norm).
            INSERT INTO customer_aliases(id, customer_id, alias, alias_norm, created_by, created_at)
            VALUES (3, 900101, 'Omega Ｃｏ', 'omega ｃｏ', 'admin', '2026-01-03 00:00:00');
            INSERT INTO customer_aliases(id, customer_id, alias, alias_norm, created_by, created_at)
            VALUES (4, 900102, 'Omega Co', 'omega co', 'admin', '2026-01-04 00:00:00');
            -- Name collision: the NEW norm equals customer 900103's name norm.
            INSERT INTO customer_aliases(id, customer_id, alias, alias_norm, created_by, created_at)
            VALUES (5, 900101, 'Straße', 'straße', 'admin', '2026-01-05 00:00:00');
        """)
        # Sanity: the seeded legacy norms are exactly what the old code stored.
        assert _old_norm("ＢＥＴＡ ＧＲＯＵＰ") == "ｂｅｔａ ｇｒｏｕｐ"
        assert _old_norm("Omega Ｃｏ") == "omega ｃｏ"
        assert _old_norm("Straße") == "straße"

    _run(env, "upgrade", "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0030_renormalize_customer_aliases",)
        rows = _rows(db)
        assert sorted(rows) == [1, 2, 3]
        assert rows[1] == ("Alpha Group", "alpha group")
        assert rows[2] == ("ＢＥＴＡ ＧＲＯＵＰ", _new_norm("ＢＥＴＡ ＧＲＯＵＰ"))
        assert rows[2][1] == "beta group"
        assert rows[3] == ("Omega Ｃｏ", "omega co")  # oldest id keeps the norm
    _run(env, "check")

    _run(env, "downgrade", "0029_netsuite_import")
    with sqlite3.connect(path) as db:
        rows = _rows(db)
        assert sorted(rows) == [1, 2, 3]  # the deleted rows do not come back
        assert rows[1] == ("Alpha Group", "alpha group")
        assert rows[2] == ("ＢＥＴＡ ＧＲＯＵＰ", "ｂｅｔａ ｇｒｏｕｐ")  # legacy norm restored
        assert rows[3] == ("Omega Ｃｏ", "omega ｃｏ")  # legacy norm restored
    _run(env, "upgrade", "head")
    with sqlite3.connect(path) as db:
        rows = _rows(db)
        assert sorted(rows) == [1, 2, 3]
        assert rows[2][1] == "beta group"
        assert rows[3] == ("Omega Ｃｏ", "omega co")
    _run(env, "check")
