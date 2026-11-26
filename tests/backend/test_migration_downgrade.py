"""Regression coverage for a one-shot head-to-base Alembic downgrade."""

import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]


def _alembic(db_url: str, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["DATABASE_URL"] = db_url
    env["SAIL_DATABASE_URL"] = db_url
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    return output


def test_head_downgrades_to_base_and_upgrades_again(tmp_path):
    db_path = tmp_path / "migration-roundtrip.db"
    db_url = f"sqlite:///{db_path}"

    _alembic(db_url, "upgrade", "head")
    downgrade_output = _alembic(db_url, "downgrade", "base")
    assert "Running downgrade 87bff5e2a7ed -> bf4d3068b073" in downgrade_output
    _alembic(db_url, "upgrade", "head")

    engine = create_engine(db_url)
    try:
        assert inspect(engine).has_table("use_cases")
    finally:
        engine.dispose()


def test_aliases_0017_to_0018_idempotent_and_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'aliases-migration.db'}"
    _alembic(db_url, "upgrade", "0017_add_assessment_type")
    _alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("customer_aliases")
        assert inspector.get_unique_constraints("customer_aliases") == [
            {"name": "uq_customer_aliases_alias_norm", "column_names": ["alias_norm"]}]
        assert "ix_customer_aliases_customer_id" in {
            i["name"] for i in inspector.get_indexes("customer_aliases")}
        # Inspector-guarded: stamp-back + re-upgrade is a no-op on the
        # existing table, and `check` stays clean at the head.
        _alembic(db_url, "stamp", "0017_add_assessment_type")
        _alembic(db_url, "upgrade", "head")
        _alembic(db_url, "check")
        _alembic(db_url, "downgrade", "0017_add_assessment_type")
        assert not inspect(engine).has_table("customer_aliases")
        _alembic(db_url, "upgrade", "head")
        assert "0018_add_customer_aliases" in _alembic(db_url, "history")
        _alembic(db_url, "check")
    finally:
        engine.dispose()


def test_import_amount_issues_0018_to_0019_idempotent_and_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'amount-issues-migration.db'}"
    _alembic(db_url, "upgrade", "0018_add_customer_aliases")
    _alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)

    def columns():
        return {c["name"]: c for c in inspect(engine).get_columns("intelligence_imports")}

    try:
        assert columns()["amount_issues"]["nullable"] is True
        # Inspector-guarded: stamp-back + re-upgrade is a no-op on the
        # existing column, and `check` stays clean at the head.
        _alembic(db_url, "stamp", "0018_add_customer_aliases")
        _alembic(db_url, "upgrade", "head")
        _alembic(db_url, "check")
        _alembic(db_url, "downgrade", "0018_add_customer_aliases")
        assert "amount_issues" not in columns()
        _alembic(db_url, "upgrade", "head")
        assert "0019_add_import_amount_issues" in _alembic(db_url, "history")
        _alembic(db_url, "check")
    finally:
        engine.dispose()


def test_contacts_0013_to_0014_idempotent_and_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'contacts-migration.db'}"
    _alembic(db_url, "upgrade", "0013_add_customer_sales_structure")
    _alembic(db_url, "upgrade", "head")
    engine = create_engine(db_url)
    try:
        inspector = inspect(engine)
        assert inspector.has_table("customer_contacts")
        assert inspector.get_unique_constraints("contact_buying_roles") == [
            {"name": "uq_contact_buying_role", "column_names": ["contact_id", "role"]}]
        for table, column in (("customer_contacts", "customer_id"), ("contact_buying_roles", "contact_id"),
                              ("contact_notes", "contact_id"), ("contact_use_cases", "contact_id"),
                              ("contact_technologies", "contact_id")):
            assert f"ix_{table}_{column}" in {i["name"] for i in inspector.get_indexes(table)}
        _alembic(db_url, "stamp", "0013_add_customer_sales_structure")
        _alembic(db_url, "upgrade", "head")
        _alembic(db_url, "downgrade", "0013_add_customer_sales_structure")
        assert not inspect(engine).has_table("customer_contacts")
        _alembic(db_url, "upgrade", "head")
        _alembic(db_url, "check")
    finally:
        engine.dispose()


def test_engagement_0014_to_0015_idempotent_and_roundtrip(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'engagement-migration.db'}"
    _alembic(db_url, "upgrade", "0014_add_customer_contacts")
    _alembic(db_url, "upgrade", "0015_add_customer_engagement")
    engine = create_engine(db_url)
    tables = ("customer_activities", "activity_contacts", "customer_tasks",
              "task_evidence_notes", "task_evidence_activities", "task_notification_windows")
    try:
        inspector = inspect(engine)
        assert all(inspector.has_table(name) for name in tables)
        assert inspector.get_unique_constraints("customer_tasks") == [
            {"name": "uq_customer_task_source", "column_names": ["customer_id", "source_key"]}]
        assert inspector.get_unique_constraints("task_notification_windows") == [
            {"name": "uq_task_notification_window", "column_names": ["task_id", "window", "user_name"]}]
        for table in ("customer_tasks", "customer_activities"):
            assert f"ix_{table}_customer_id" in {i["name"] for i in inspector.get_indexes(table)}
        # No mid-chain `check`: 0015 is no longer the head (0016 moved it), so a
        # check at 0015 would always report the newer revision as a drift.
        _alembic(db_url, "stamp", "0014_add_customer_contacts")
        _alembic(db_url, "upgrade", "head")
        _alembic(db_url, "check")
        _alembic(db_url, "downgrade", "0014_add_customer_contacts")
        assert all(not inspect(engine).has_table(name) for name in tables)
        _alembic(db_url, "upgrade", "head")
        assert "0015_add_customer_engagement" in _alembic(db_url, "history")
        _alembic(db_url, "check")
    finally:
        engine.dispose()


def _schema_signature(engine):
    """Compare complete head schemas, including retained FK/index semantics."""
    schema = inspect(engine)
    return {
        table: {
            'columns': [(c['name'], str(c['type']), c['nullable'], str(c.get('default')))
                        for c in schema.get_columns(table)],
            'foreign_keys': sorted((tuple(fk['constrained_columns']), fk['referred_table'],
                                    tuple(fk['referred_columns']), tuple(sorted(fk['options'].items())))
                                   for fk in schema.get_foreign_keys(table)),
            'indexes': sorted((index['name'], tuple(index['column_names']), bool(index['unique']))
                              for index in schema.get_indexes(table)),
            'unique_constraints': sorted((tuple(c['column_names']), c['name'] or '')
                                         for c in schema.get_unique_constraints(table)),
        }
        for table in schema.get_table_names()
    }


def test_selected_backend_roundtrip_restores_head_schema(tmp_path, db_session):
    """PG uses only the guarded test DB; the default run uses a SQLite file."""
    from sqlalchemy import text

    if db_session.bind.dialect.name == 'postgresql':
        from backend.test_database import guarded_test_url
        url = guarded_test_url(os.environ['TEST_DATABASE_URL'], reset=True)
        engine = db_session.bind
        owns_engine = False
        assert db_session.scalar(text('SELECT current_database()')) == 'sail_test'
        # Release inspection locks before subprocess DDL.
        db_session.rollback()
    else:
        url = f"sqlite:///{tmp_path / 'selected-roundtrip.db'}"
        engine = create_engine(url)
        owns_engine = True
    try:
        _alembic(url, 'upgrade', 'head')
        before = _schema_signature(engine)
        # Applied-head upgrades must retain existing rows, including the two
        # tables whose PG downgrade ownership is repaired by this change.
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO customers(id, name) VALUES (910001, 'Roundtrip sentinel')"))
            connection.execute(text("INSERT INTO use_cases(id, title, customer_id, status) "
                                    "VALUES (910001, 'Roundtrip use case', 910001, 'draft')"))
            connection.execute(text("INSERT INTO dimension_configs(id, version, name, weight) "
                                    "VALUES (910001, 'roundtrip', 'Sentinel dimension', 1.0)"))
            connection.execute(text("INSERT INTO score_history(id, use_case_id, score, scored_at, scored_by) "
                                    "VALUES (910001, 910001, 75, '2026-11-06 00:00:00', 'roundtrip')"))
        _alembic(url, 'upgrade', 'head')
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT score FROM score_history WHERE id=910001')) == 75
            assert connection.scalar(text('SELECT name FROM dimension_configs WHERE id=910001')) == 'Sentinel dimension'
            assert connection.scalar(text('SELECT customer_id FROM use_cases WHERE id=910001')) == 910001
        # The roundtrip below tests schema restoration, not data recovery from
        # a destructive rollback. Legacy SQLite base retains score_history;
        # leave it no orphan from this test's applied-head retention probe.
        with engine.begin() as connection:
            for table in ('score_history', 'dimension_configs', 'use_cases', 'customers'):
                connection.execute(text(f'DELETE FROM {table} WHERE id=910001'))
        _alembic(url, 'downgrade', 'base')
        with engine.connect() as connection:
            assert connection.scalar(text('SELECT COUNT(*) FROM alembic_version')) == 0
        if engine.dialect.name == 'postgresql':
            assert inspect(engine).get_table_names() == ['alembic_version']
        _alembic(url, 'upgrade', 'head')
        assert _schema_signature(engine) == before
        with engine.connect() as connection:
            expected_head = ScriptDirectory.from_config(Config(str(REPO_ROOT / 'alembic.ini'))).get_current_head()
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == expected_head
    finally:
        if owns_engine:
            engine.dispose()
