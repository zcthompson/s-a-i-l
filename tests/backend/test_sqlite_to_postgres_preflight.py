"""Preflight is read-only and invalid target/copy options fail closed."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

spec = importlib.util.spec_from_file_location('sail_migration_tool', Path(__file__).parents[2] / 'scripts/migrate_sqlite_to_postgres.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_preflight_rejects_target_before_connecting(tmp_path, monkeypatch):
    path = tmp_path / 'source.db'
    path.touch()
    monkeypatch.setattr(module.sa, 'create_engine', lambda *_a, **_kw: pytest.fail('must reject before connecting'))
    with pytest.raises(ValueError):
        module.preflight(path, 'postgresql://localhost/production')


@pytest.mark.parametrize('args', [['--dry-run', '--force']])
def test_unsupported_copy_modes_fail_closed(args):
    with pytest.raises(SystemExit):
        module.main(['--source', 'missing.db', '--target', 'postgresql://localhost/sail_test', *args])


def test_preflight_counts_disposable_source_on_postgres(tmp_path, db_session):
    if db_session.bind.dialect.name != 'postgresql':
        # This test still checks a meaningful, non-network SQLite guard locally.
        with pytest.raises(FileNotFoundError):
            module.preflight(tmp_path / 'missing.db', 'postgresql://localhost/sail_test')
        return
    path = tmp_path / 'source.db'
    engine = sa.create_engine(f'sqlite:///{path}')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE synthetic (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO synthetic (id) VALUES (1), (2)'))
    engine.dispose()
    import os
    result = module.preflight(path, os.environ['TEST_DATABASE_URL'])
    assert result['source_rows'] == {'synthetic': 2}
    assert result['target_database'] == 'sail_test'
    assert result['missing_target_tables'] == ['synthetic']
