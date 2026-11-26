#!/usr/bin/env python3
"""Copy a current SQLite snapshot into disposable PostgreSQL sail_test.

Source is opened read-only. --force replaces all target application rows and
is restricted to sail_test. No production target or live cutover is supported.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.migration_sequences import reserve_ids  # noqa: E402
from backend.test_database import guarded_test_url  # noqa: E402

HIERARCHY = ('customers', 'users', 'customer_users', 'account_memberships',
             'sales_reporting', 'inside_sales_assignments', 'sales_ops_assignments')
BATCH_SIZE = 500


def _source_engine(source):
    path = Path(source).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError('Source must be an existing SQLite file')
    # Escaping URI delimiters in the filename prevents a crafted path from
    # changing SQLite's read-only connection options.
    return sa.create_engine(sa.URL.create('sqlite', database=f'file:{quote(str(path), safe="/")}',
                                         query={'mode': 'ro', 'uri': 'true'}), poolclass=NullPool)


def _target_engine(target):
    return sa.create_engine(guarded_test_url(target), poolclass=NullPool, connect_args={'connect_timeout': 10})


def _revision(connection):
    return connection.scalar(sa.text('SELECT version_num FROM alembic_version')) if sa.inspect(connection).has_table('alembic_version') else None


def _application_tables(connection):
    return sorted(set(sa.inspect(connection).get_table_names()) - {'alembic_version', 'sqlite_sequence'})


def _counts(connection, names):
    quote = connection.dialect.identifier_preparer.quote
    return {name: connection.scalar(sa.text(f'SELECT COUNT(*) FROM {quote(name)}')) for name in names}


def preflight(source, target):
    target = guarded_test_url(target)
    src = _source_engine(source)
    dst = _target_engine(target)
    try:
        with src.connect() as sc, dst.connect() as dc:
            dc.execute(sa.text('SET TRANSACTION READ ONLY'))
            if dc.scalar(sa.text('SELECT current_database()')) != 'sail_test':
                raise ValueError('Unexpected target database identity')
            names = _application_tables(sc)
            targets = _application_tables(dc)
            return {'mode': 'preflight', 'source_backend': 'sqlite', 'target_database': 'sail_test',
                    'source_revision': _revision(sc), 'target_revision': _revision(dc),
                    'source_rows': _counts(sc, names), 'target_rows': _counts(dc, targets),
                    'missing_target_tables': sorted(set(names) - set(targets))}
    finally:
        src.dispose()
        dst.dispose()


def _migration_module(prefix):
    path = next((ROOT / 'alembic/versions').glob(prefix + '*.py'))
    spec = importlib.util.spec_from_file_location('sail_' + prefix, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _checksum(connection, table):
    # Hierarchy IDs and relationships are the cross-backend contract; hash
    # canonical tuples, sorted independently of DB row order.
    columns = [c for c in table.columns if c.name == 'id' or c.name.endswith('_id') or c.name in ('username', 'name', 'role')]
    rows = connection.execute(sa.select(*columns)).all()
    encoded = sorted(json.dumps(list(row), ensure_ascii=False, default=str, separators=(',', ':')) for row in rows)
    return hashlib.sha256(('\n'.join(encoded)).encode()).hexdigest()


def migrate(source, target, *, force=False):
    target = guarded_test_url(target)
    src = _source_engine(source)
    dst = _target_engine(target)
    try:
        head = ScriptDirectory.from_config(Config(str(ROOT / 'alembic.ini'))).get_current_head()
        with src.connect() as sc:
            sc.exec_driver_sql('BEGIN')  # one consistent, read-only SQLite snapshot
            if _revision(sc) != head:
                raise ValueError('Source must already be at the current Alembic head')
            if sc.exec_driver_sql('PRAGMA foreign_key_check').first() is not None:
                raise ValueError('Source contains foreign-key violations; repair or review first')
            source_names = _application_tables(sc)
            source_counts = _counts(sc, source_names)
            source_metadata = sa.MetaData()
            source_metadata.reflect(bind=sc, only=source_names)
            highwater = dict(sc.execute(sa.text('SELECT name, seq FROM sqlite_sequence')).all()) if sa.inspect(sc).has_table('sqlite_sequence') else {}
            with dst.connect() as dc:
                dc.execute(sa.text('SET TRANSACTION READ ONLY'))
                if dc.scalar(sa.text('SELECT current_database()')) != 'sail_test':
                    raise ValueError('Unexpected target database identity')
                initial_names = _application_tables(dc)
                if initial_names and any(_counts(dc, initial_names).values()) and not force:
                    raise ValueError('Target contains data; explicit --force is required')
                initially_empty = not initial_names
            env = {**os.environ, 'DATABASE_URL': target, 'SAIL_DATABASE_URL': target}
            # Avoid logging credentials or SQL parameters from failed subprocesses.
            result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT, env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                raise RuntimeError('Target migration failed')
            with dst.begin() as dc:
                dc.execute(sa.text("SET LOCAL lock_timeout = '10s'"))
                target_names = _application_tables(dc)
                if set(source_names) != set(target_names):
                    raise ValueError('Source and target tables differ')
                target_metadata = sa.MetaData()
                target_metadata.reflect(bind=dc, only=target_names)
                dependencies = list(sa.schema.sort_tables_and_constraints(target_metadata.tables.values()))
                if any(table is None and constraints for table, constraints in dependencies):
                    raise ValueError('Target contains cyclic foreign keys; safe copy order is unavailable')
                ordered = [table for table, _ in dependencies if table is not None]
                if len(ordered) != len(target_names):
                    raise ValueError('Could not determine foreign-key order')
                quote = dc.dialect.identifier_preparer.quote
                table_list = ', '.join(quote(table.name) for table in ordered)
                dc.execute(sa.text(f'LOCK TABLE {table_list} IN ACCESS EXCLUSIVE MODE'))
                target_counts = _counts(dc, target_names)
                # Fresh upgrade seeds pipeline stages; it is safe to remove
                # only when the target had no application tables before DDL.
                if any(target_counts.values()) and not force:
                    if not initially_empty or any(count for name, count in target_counts.items() if name != 'pipeline_stages'):
                        raise ValueError('Target acquired data; refusing copy')
                    stages = _migration_module('0026_').DEFAULT_STAGES
                    expected_stages = {(key, label, cls, position, True, probability)
                                       for key, label, cls, position, probability in stages}
                    actual_stages = set(dc.execute(sa.text(
                        'SELECT key, label, stage_class, position, active, default_probability FROM pipeline_stages'
                    )).all())
                    if actual_stages != expected_stages:
                        raise ValueError('Target has unexpected pipeline stage data; refusing copy')
                for table in ordered:
                    source_table = source_metadata.tables[table.name]
                    if set(source_table.c.keys()) != set(table.c.keys()):
                        raise ValueError(f'Source and target columns differ for {table.name}')
                dc.execute(sa.text(f'TRUNCATE TABLE {table_list} RESTART IDENTITY'))
                for table in ordered:
                    source_table = source_metadata.tables[table.name]
                    result = sc.execute(sa.select(source_table))
                    while rows := result.fetchmany(BATCH_SIZE):
                        dc.execute(table.insert(), [dict(row._mapping) for row in rows])
                actual_counts = _counts(dc, target_names)
                if source_counts != actual_counts:
                    raise RuntimeError('Copied row counts do not match')
                checksums = {}
                for name in HIERARCHY:
                    if name in source_names:
                        before = _checksum(sc, source_metadata.tables[name])
                        after = _checksum(dc, target_metadata.tables[name])
                        if before != after:
                            raise RuntimeError(f'Hierarchy checksum mismatch: {name}')
                        checksums[name] = before
                users = _migration_module('0024_')
                records = _migration_module('0025_')
                refs = {'customers': [('audit_logs', 'customer_id', None)],
                        'users': [(t, c, None) for t, c in users.USER_REFERENCES] + [
                            ('audit_logs', 'target_id', "action IN ('add_user', 'remove_user', 'set_manager', 'set_primary_rep')")],
                        **records.REFERENCES}
                for table in ordered:
                    if 'id' in table.c:
                        reserve_ids(dc, table.name, refs.get(table.name, ()), int(highwater.get(table.name, 0)))
            return {'mode': 'copied', 'target_database': 'sail_test', 'revision': head,
                    'counts': source_counts, 'hierarchy_checksums': checksums}
    finally:
        src.dispose()
        dst.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, help='Existing SQLite file (read-only)')
    parser.add_argument('--target', default=os.environ.get('TEST_DATABASE_URL'), help='Explicit PostgreSQL test URL; environment variable preferred')
    parser.add_argument('--dry-run', action='store_true', help='Inspect without writing')
    parser.add_argument('--force', action='store_true', help='Replace populated sail_test application data')
    args = parser.parse_args(argv)
    if not args.target:
        parser.error('Provide --target or TEST_DATABASE_URL')
    if args.dry_run and args.force:
        parser.error('--dry-run cannot be combined with --force')
    try:
        print(json.dumps(preflight(args.source, args.target) if args.dry_run else migrate(args.source, args.target, force=args.force), indent=2, sort_keys=True))
    except Exception as exc:
        # SQLAlchemy/driver errors can contain connection strings or row values.
        if isinstance(exc, ValueError):
            print(f'Migration refused: {exc}', file=sys.stderr)
        else:
            print(f'Migration failed ({type(exc).__name__}); no row copy was committed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
