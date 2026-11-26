"""The backend probe must select one real integration database, never fallback."""
import importlib.util
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from tests.backend import database_support
from tests.backend._shared import engine


def test_shared_integration_engine_matches_selected_backend(db_session, request):
    assert engine is database_support.engine is db_session.get_bind()
    expected = 'postgresql' if os.environ.get('TEST_DATABASE_URL') else 'sqlite'
    assert engine.dialect.name == expected
    request.node.user_properties.append(('verified_integration_backend', expected))
    if expected == 'postgresql':
        assert db_session.scalar(text('SELECT current_database()')) == 'sail_test'
        assert db_session.scalar(text('SELECT version_num FROM alembic_version')) == '0027_deal_vendor_evidence'


def test_runner_cleanup_refuses_unrelated_database_before_connecting(monkeypatch):
    spec = importlib.util.spec_from_file_location('sail_pg_runner', Path(__file__).parents[2] / 'scripts/test_postgres.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    create = Mock()
    monkeypatch.setattr(module.sa, 'create_engine', create)
    for value in ('sqlite:///sail_test', 'postgresql://localhost/sail', 'postgresql://localhost/other_test'):
        with pytest.raises(ValueError):
            module.clear_test_schema(value)
    create.assert_not_called()


def test_restricted_scratch_guard_requires_explicit_role_and_opt_in(monkeypatch):
    from backend.test_database import guarded_test_url

    scratch = 'postgresql://sail_permcheck_role@localhost/sail_permcheck'
    monkeypatch.delenv('SAIL_RESTRICTED_PERMCHECK', raising=False)
    with pytest.raises(ValueError):
        guarded_test_url(scratch)
    monkeypatch.setenv('SAIL_RESTRICTED_PERMCHECK', '1')
    monkeypatch.setenv('SAIL_ALLOW_TEST_SCHEMA_RESET', 'sail_permcheck')
    assert guarded_test_url(scratch, reset=True).startswith('postgresql+psycopg:')
    for unsafe in ('postgresql://other@localhost/sail_permcheck',
                   'postgresql://sail_permcheck_role@remote.example/sail_permcheck',
                   'postgresql://sail_permcheck_role@localhost/sail'):
        with pytest.raises(ValueError):
            guarded_test_url(unsafe, reset=True)
