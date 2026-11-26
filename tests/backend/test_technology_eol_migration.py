"""E5 migration preserves technology rows and tolerates already-added columns."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_eol_upgrade_preservation_idempotency_and_guarded_downgrade(tmp_path):
    path = tmp_path / "e5-migration.sqlite"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}", "SAIL_DATABASE_URL": f"sqlite:///{path}"}
    env.pop("PYTHONPATH", None)

    def alembic(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", *args],
                                cwd=Path(__file__).resolve().parents[2], env=env,
                                text=True, capture_output=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr

    alembic("upgrade", "0020_add_saved_views")
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO customers (id, name) VALUES (1, 'Synthetic migration account')")
        con.execute("INSERT INTO customer_technologies (id, customer_id, name, category, verification_state) "
                    "VALUES (1, 1, 'Synthetic retained technology', 'software', 'unverified')")
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT name, end_of_support_date, eol_source FROM customer_technologies").fetchone() == (
            "Synthetic retained technology", None, None)
        con.execute("UPDATE customer_technologies SET end_of_support_date='2027-01-31', eol_source='Synthetic notice'")
    # Re-enter the guarded upgrade while columns and data already exist.
    alembic("stamp", "0020_add_saved_views")
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT end_of_support_date, eol_source FROM customer_technologies").fetchone() == (
            "2027-01-31", "Synthetic notice")
        assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    alembic("downgrade", "0020_add_saved_views")
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT name FROM customer_technologies").fetchone()[0] == "Synthetic retained technology"
        assert not {"end_of_support_date", "eol_source"} & {
            row[1] for row in con.execute("PRAGMA table_info(customer_technologies)")}
    # Guarded downgrade also tolerates columns already absent.
    alembic("stamp", "0021_add_technology_eol_fields")
    alembic("downgrade", "0020_add_saved_views")
    alembic("upgrade", "head")
    alembic("check")
