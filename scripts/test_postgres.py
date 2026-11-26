#!/usr/bin/env python3
"""Run the selected PostgreSQL suite, then leave sail_test's schema empty.

Uses the existing server only. Never creates a database or starts a container.
Usage: .venv/bin/python scripts/test_postgres.py [pytest arguments...]
"""
import fcntl
import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.test_database import guarded_test_url  # noqa: E402


def clear_test_schema(url):
    selected = guarded_test_url(url, reset=True)
    engine = sa.create_engine(selected, poolclass=sa.pool.NullPool, connect_args={"connect_timeout": 10})
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
            connection.execute(sa.text("SET LOCAL statement_timeout = '30s'"))
            if connection.execute(sa.text('SELECT current_database()')).scalar_one() != 'sail_test':
                raise RuntimeError('Unexpected database identity; refusing test cleanup')
            connection.execute(sa.text('DROP SCHEMA public CASCADE'))
            connection.execute(sa.text('CREATE SCHEMA public'))
    finally:
        engine.dispose()


def main(args=None):
    os.umask(0o077)
    config = {**dotenv_values(ROOT / '.env.pg.local'), **os.environ}
    value = config.get('TEST_DATABASE_URL')
    if not value:
        raise SystemExit('Set TEST_DATABASE_URL in the environment or ignored .env.pg.local; no container fallback.')
    # Invocation of this destructive test command is the explicit reset opt-in.
    os.environ['SAIL_ALLOW_TEST_SCHEMA_RESET'] = 'sail_test'
    selected = guarded_test_url(value, reset=True)
    env = {**config, 'TEST_DATABASE_URL': selected, 'DATABASE_URL': selected,
           'SAIL_DATABASE_URL': selected, 'SAIL_ALLOW_TEST_SCHEMA_RESET': 'sail_test'}
    env = {key: value for key, value in env.items() if value is not None}
    pytest_args = list(sys.argv[1:] if args is None else args) or ['tests/', '-q', '--tb=short']
    with open('/tmp/sail-postgres-test.lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another PostgreSQL test run is active; refusing concurrent schema reset.') from None
        print('Selected PostgreSQL integration backend: sail_test (schema reset before/after suite).', flush=True)
        try:
            result = subprocess.run([sys.executable, '-m', 'pytest', *pytest_args], cwd=ROOT, env=env)
            return result.returncode
        finally:
            clear_test_schema(selected)
            print('PostgreSQL test schema reset after suite.', flush=True)


if __name__ == '__main__':
    sys.exit(main())
