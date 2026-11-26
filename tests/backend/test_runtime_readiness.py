"""Runtime, storage, database selection and fail-fast bootstrap contracts."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from backend.config import Settings
from backend.test_database import guarded_test_url

from backend import database, entrypoint, runtime, storage


def settings(tmp_path, **overrides):
    values = dict(database_url=f"sqlite:///{tmp_path}/nested/sail.db", files_dir="")
    values.update(overrides)
    return SimpleNamespace(**values)


def test_storage_parent_creation_and_escape_rejection(tmp_path):
    config = settings(tmp_path)
    root = storage.prepare_directories(config)
    assert root == tmp_path / 'nested/files'
    assert (tmp_path / 'nested').is_dir()
    assert storage.persistent_path('exports/a.json', config) == root / 'exports/a.json'
    for path in ('../../escape', '/tmp/escape'):
        with pytest.raises(ValueError):
            storage.persistent_path(path, config)
    (root / 'outside').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError):
        storage.persistent_path('outside/escape', config)


def test_postgres_alias_tls_and_pool_policy():
    assert 'postgresql+psycopg://' in database.normalized_url('postgres://user:pw@host/sail')
    assert 'sslmode=require' in database.normalized_url('postgresql://host/sail')
    assert 'sslmode=disable' in database.normalized_url('postgresql://host/sail?sslmode=disable')
    assert 'sslmode=verify-full' in database.normalized_url('postgresql://host/sail?sslmode=disable', 'verify-full')
    factory = Mock()
    database._engine('postgresql+psycopg://host/sail', False, 3, 2, factory)
    assert factory.call_args.kwargs == dict(pool_pre_ping=True, pool_recycle=1800,
        pool_size=3, max_overflow=2, pool_timeout=10, connect_args={'connect_timeout': 10})
    factory.reset_mock()
    database._engine('sqlite://', False, 3, 2, factory)
    assert factory.call_args.kwargs == {'pool_pre_ping': True}


def test_sqlite_network_pragmas_only_when_selected(tmp_path):
    # Use the real factory, independent of the application-engine test seam.
    from sqlalchemy.engine.create import create_engine
    engine = database._engine(f'sqlite:///{tmp_path}/network.db', True, 5, 5, create_engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql('PRAGMA journal_mode').scalar() == 'delete'
        assert connection.exec_driver_sql('PRAGMA foreign_keys').scalar() == 1
        assert connection.exec_driver_sql('PRAGMA busy_timeout').scalar() == 10000
        assert connection.exec_driver_sql('PRAGMA synchronous').scalar() == 2
    engine.dispose()


def test_settings_alias_precedence(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'postgresql://canonical/sail')
    monkeypatch.setenv('SAIL_DATABASE_URL', 'sqlite:///legacy.db')
    monkeypatch.setenv('DOCLING_URL', 'http://localhost:5001')
    config = Settings(_env_file=None)
    assert config.database_url == 'postgresql://canonical/sail'
    assert config.docling_server_url == 'http://localhost:5001'
    monkeypatch.delenv('DATABASE_URL')
    assert Settings(_env_file=None).database_url == 'sqlite:///legacy.db'


def test_guard_rejects_non_test_or_unapproved_targets(monkeypatch):
    for url in ('sqlite:///sail_test', 'postgresql://localhost/sail', 'postgresql://localhost/vme_test', 'invalid'):
        with pytest.raises(ValueError):
            guarded_test_url(url)
    monkeypatch.delenv('SAIL_ALLOW_TEST_SCHEMA_RESET', raising=False)
    with pytest.raises(ValueError):
        guarded_test_url('postgresql://localhost/sail_test', reset=True)
    monkeypatch.setenv('SAIL_ALLOW_TEST_SCHEMA_RESET', 'sail_test')
    assert guarded_test_url('postgresql://localhost/sail_test', reset=True).startswith('postgresql+psycopg:')


def test_readiness_degraded_docling_and_private_errors(tmp_path, monkeypatch):
    config = settings(tmp_path)
    monkeypatch.setattr(runtime, 'get_settings', lambda: config)
    engine = Mock()
    monkeypatch.setattr(runtime, 'create_engine', lambda _: engine)
    engine.connect.return_value.__enter__ = Mock(return_value=Mock())
    engine.connect.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr('backend.services.docling_service.DoclingService.health', Mock(side_effect=RuntimeError('secret-url')))
    payload, status = runtime.readiness()
    assert status == 200
    assert payload == dict(status='ready', database_backend='sqlite', database='ok', files='ok', docling='unavailable')
    engine.connect.side_effect = RuntimeError('password=hidden')
    payload, status = runtime.readiness()
    assert status == 503 and payload['database'] == 'unavailable'
    assert 'hidden' not in str(payload) and str(tmp_path) not in str(payload)
    monkeypatch.setattr(runtime, 'prepare_directories', Mock(side_effect=PermissionError('private path')))
    assert runtime.readiness()[0]['files'] == 'unavailable'


def test_bootstrap_fail_fast_and_migration_opt_out(monkeypatch):
    monkeypatch.setattr(entrypoint, 'prepare_runtime', Mock())
    config = SimpleNamespace(run_migrations_on_start=True)
    monkeypatch.setattr(entrypoint, 'get_settings', lambda: config)
    run, execute = Mock(side_effect=RuntimeError('migration failed')), Mock()
    monkeypatch.setattr(entrypoint.subprocess, 'run', run)
    monkeypatch.setattr(entrypoint.os, 'execvp', execute)
    with pytest.raises(RuntimeError):
        entrypoint.main(['uvicorn', 'backend.main:app'])
    assert run.call_count == 1
    execute.assert_not_called()
    config.run_migrations_on_start = False
    entrypoint.main(['uvicorn', 'backend.main:app'])
    execute.assert_called_once_with('uvicorn', ['uvicorn', 'backend.main:app'])


def test_health_routes_public_and_readiness_status(client, monkeypatch):
    monkeypatch.setattr(runtime, 'readiness', lambda: ({'status': 'unavailable'}, 503))
    assert client.get('/healthz').status_code == 200
    response = client.get('/readyz')
    assert response.status_code == 503 and response.json() == {'status': 'unavailable'}
