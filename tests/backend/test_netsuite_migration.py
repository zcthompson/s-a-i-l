"""Revision 0029 preserves existing data and matches model metadata."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def _script_head():
    """The current Alembic head — durable across new revisions (0029, 0030, …)."""
    return ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()


def test_netsuite_migration_disposable_roundtrip(tmp_path):
    path = tmp_path / "netsuite-migration.db"
    env = {**os.environ, "SAIL_DATABASE_URL": f"sqlite:///{path}", "DATABASE_URL": f"sqlite:///{path}"}

    def run(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT,
                                env=env, capture_output=True, text=True, timeout=90)
        assert result.returncode == 0, result.stdout + result.stderr

    run("upgrade", "0028_user_appearance")
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO customers(id, name) VALUES (900001, 'Synthetic migration sentinel')")
    run("upgrade", "head")
    run("check")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM customers WHERE id=900001").fetchone() == ("Synthetic migration sentinel",)
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (_script_head(),)
        columns = {row[1] for row in db.execute("PRAGMA table_info(netsuite_imports)")}
        assert not {"file_data", "amount", "currency", "price", "cost"} & columns
        for table in ("netsuite_imports", "netsuite_import_rows", "netsuite_import_notes"):
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
            assert "AUTOINCREMENT" in sql
    run("downgrade", "0028_user_appearance")
    with sqlite3.connect(path) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name LIKE 'netsuite_import%'").fetchall()
        assert db.execute("SELECT COUNT(*) FROM customers WHERE id=900001").fetchone() == (1,)
    run("upgrade", "head")
    run("check")
