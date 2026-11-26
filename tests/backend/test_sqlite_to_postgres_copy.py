"""Synthetic end-to-end transfer into the guarded PostgreSQL test database."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine.create import create_engine

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('sail_copy_test', ROOT / 'scripts/migrate_sqlite_to_postgres.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture_source(path):
    url = f'sqlite:///{path}'
    env = {**os.environ, 'DATABASE_URL': url, 'SAIL_DATABASE_URL': url}
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    source = create_engine(url)
    with source.begin() as c:
        c.execute(sa.text("INSERT INTO customers (id, name) VALUES (11, 'Synthetic copy')"))
        c.execute(sa.text("INSERT INTO customers (id, name) VALUES (800, 'Deleted identity')"))
        c.execute(sa.text('DELETE FROM customers WHERE id=800'))
        c.execute(sa.text("INSERT INTO users (id, username, is_admin, approved, is_active, auth_provider) VALUES (12, 'copy-user', 0, 1, 1, 'local')"))
        c.execute(sa.text("INSERT INTO customer_users (id, customer_id, user_id, role) VALUES (13, 11, 12, 'owner')"))
        c.execute(sa.text("INSERT INTO departments (id, customer_id, name) VALUES (14, 11, 'Synthetic department')"))
        c.execute(sa.text("INSERT INTO use_cases (id, customer_id, department_id, title, status, goals) VALUES (15, 11, 14, 'Synthetic use case', 'draft', '[\"first\"]')"))
        c.execute(sa.text("INSERT INTO audit_logs (id, user_id, username, action, customer_id, created_at) VALUES (16, 12, 'copy-user', 'score', 999, '2026-01-01 00:00:00')"))
    source.dispose()


def test_copy_guards_fail_before_connecting(tmp_path, monkeypatch):
    source = tmp_path / 'source.db'
    source.touch()
    monkeypatch.setattr(module.sa, 'create_engine', lambda *_args, **_kwargs: pytest.fail('unsafe target must not connect'))
    with pytest.raises(ValueError):
        module.migrate(source, 'postgresql://localhost/production', force=True)


def test_fixture_transfer_preserves_ids_values_and_highwater(tmp_path, db_session):
    if db_session.bind.dialect.name != 'postgresql':
        # SQLite-only runs verify fail-closed target selection; actual transfer
        # must use the PostgreSQL-selected suite.
        with pytest.raises(ValueError):
            module.migrate(tmp_path / 'missing', 'sqlite:///wrong')
        return
    path = tmp_path / 'synthetic-source.db'
    fixture_source(path)
    target = os.environ['TEST_DATABASE_URL']
    db_session.rollback()
    before = db_session.scalar(sa.text('SELECT count(*) FROM users'))
    db_session.rollback()
    inspection = module.preflight(path, target)
    assert inspection['source_rows']['customers'] == 1
    assert db_session.scalar(sa.text('SELECT count(*) FROM users')) == before
    db_session.rollback()
    # Fixture setup creates an admin user: populated target must be preserved.
    with pytest.raises(ValueError, match='contains data'):
        module.migrate(path, target)
    assert db_session.scalar(sa.text("SELECT count(*) FROM users WHERE username='admin'")) == 1
    db_session.rollback()
    result = module.migrate(path, target, force=True)
    assert result['counts']['customers'] == 1
    assert result['counts']['use_cases'] == 1
    assert {'customers', 'users', 'customer_users'} <= result['hierarchy_checksums'].keys()
    db_session.expire_all()
    assert db_session.execute(sa.text("SELECT title, customer_id, goals FROM use_cases WHERE id=15")).one() == ('Synthetic use case', 11, ['first'])
    new_id = db_session.scalar(sa.text("INSERT INTO customers(name) VALUES ('After copy') RETURNING id"))
    assert new_id > 999  # retained audit reference exceeds SQLite sequence 800
    db_session.rollback()


def test_copy_to_empty_migrated_target_needs_no_force(tmp_path, db_session):
    if db_session.bind.dialect.name != 'postgresql':
        with pytest.raises(ValueError):
            module.migrate(tmp_path / 'unused', 'sqlite:///wrong')
        return
    from tests.backend.database_support import reset_tables

    path = tmp_path / 'synthetic-source.db'
    fixture_source(path)
    reset_tables(db_session)
    result = module.migrate(path, os.environ['TEST_DATABASE_URL'])
    assert result['counts']['customers'] == 1
    assert db_session.scalar(sa.text("SELECT name FROM customers WHERE id=11")) == 'Synthetic copy'
    db_session.rollback()


def test_force_copy_rolls_back_on_verification_failure(tmp_path, db_session, monkeypatch):
    if db_session.bind.dialect.name != 'postgresql':
        with pytest.raises(ValueError):
            module.migrate(tmp_path / 'unused', 'sqlite:///wrong', force=True)
        return
    path = tmp_path / 'synthetic-source.db'
    fixture_source(path)
    target = os.environ['TEST_DATABASE_URL']
    db_session.rollback()
    module.migrate(path, target, force=True)
    db_session.rollback()
    original = module._checksum
    calls = [0]

    def mismatch(*args):
        calls[0] += 1
        return 'synthetic-mismatch' if calls[0] == 2 else original(*args)

    monkeypatch.setattr(module, '_checksum', mismatch)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        module.migrate(path, target, force=True)
    db_session.expire_all()
    assert db_session.scalar(sa.text("SELECT count(*) FROM customers WHERE id=11 AND name='Synthetic copy'")) == 1
    assert db_session.scalar(sa.text('SELECT count(*) FROM use_cases WHERE id=15 AND customer_id=11')) == 1
    db_session.rollback()


def test_source_uri_escapes_filename_and_is_read_only(tmp_path):
    path = tmp_path / 'source ? and # signs.sqlite'
    engine = create_engine(sa.URL.create('sqlite', database=str(path)))
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE sentinel (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO sentinel VALUES (1)'))
    engine.dispose()
    readonly = module._source_engine(path)
    try:
        with readonly.connect() as connection:
            assert connection.scalar(sa.text('SELECT COUNT(*) FROM sentinel')) == 1
            with pytest.raises(sa.exc.OperationalError):
                connection.execute(sa.text('INSERT INTO sentinel VALUES (2)'))
    finally:
        readonly.dispose()
