"""Legacy-name comparisons suppress only proven equivalent SQLite uniques."""
from unittest.mock import Mock

import sqlalchemy as sa
from backend.alembic_compare import include_legacy_unique
from backend.models.use_case import NAMING_CONVENTION


def test_sqlite_unnamed_unique_matches_ordered_identity_only():
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)
    table = sa.Table('example', metadata, sa.Column('a', sa.Integer), sa.Column('b', sa.Integer),
                     sa.UniqueConstraint('a', 'b'))
    unique = next(c for c in table.constraints if isinstance(c, sa.UniqueConstraint))
    inspector = Mock()
    inspector.get_unique_constraints.return_value = [{'name': None, 'column_names': ['a', 'b']}]
    assert not include_legacy_unique(inspector, 'sqlite', unique, 'unique_constraint', False, None)
    inspector.get_unique_constraints.return_value = [{'name': None, 'column_names': ['b', 'a']}]
    assert include_legacy_unique(inspector, 'sqlite', unique, 'unique_constraint', False, None)
    inspector.get_unique_constraints.return_value = [{'name': 'custom', 'column_names': ['a', 'b']}]
    assert include_legacy_unique(inspector, 'sqlite', unique, 'unique_constraint', False, None)
    inspector.get_unique_constraints.return_value = []
    assert include_legacy_unique(inspector, 'sqlite', unique, 'unique_constraint', False, None)
    assert include_legacy_unique(inspector, 'postgresql', unique, 'unique_constraint', False, None)
    assert include_legacy_unique(inspector, 'sqlite', unique, 'index', False, None)


def test_current_metadata_names_are_unique_and_within_postgres_limit():
    import importlib
    import pkgutil

    import backend.models
    from backend.models.use_case import Base
    from sqlalchemy.dialects import postgresql

    for module in pkgutil.iter_modules(backend.models.__path__):
        importlib.import_module(f'backend.models.{module.name}')
    preparer = postgresql.dialect().identifier_preparer
    schema_names = set()
    for table in Base.metadata.sorted_tables:
        table_names = set()
        for constraint in table.constraints:
            if not constraint.name:
                continue
            name = preparer.truncate_and_render_constraint_name(constraint.name)
            assert len(name.encode()) <= 63
            assert name not in table_names, f'duplicate constraint name on {table.name}: {name}'
            table_names.add(name)
            if isinstance(constraint, (sa.PrimaryKeyConstraint, sa.UniqueConstraint)):
                assert name not in schema_names, f'duplicate index-backed constraint name: {name}'
                schema_names.add(name)
        for index in table.indexes:
            name = preparer.truncate_and_render_index_name(index.name)
            assert len(name.encode()) <= 63 and name not in schema_names
            schema_names.add(name)


def test_real_sqlite_comparison_detects_missing_unique(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    engine = sa.create_engine(f'sqlite:///{tmp_path / "constraints.db"}')
    target = sa.MetaData(naming_convention=NAMING_CONVENTION)
    sa.Table('example', target, sa.Column('id', sa.Integer, primary_key=True),
             sa.Column('a', sa.Integer), sa.Column('b', sa.Integer), sa.UniqueConstraint('a', 'b'))
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE example (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER, UNIQUE (a, b))')
            inspector = sa.inspect(connection)
            def include(obj, name, type_, reflected, compare_to):
                return include_legacy_unique(inspector, 'sqlite', obj, type_, reflected, compare_to)
            context = MigrationContext.configure(connection, opts={'include_object': include})
            assert not any(op[0] == 'add_constraint' for op in compare_metadata(context, target) if isinstance(op, tuple))
            connection.exec_driver_sql('DROP TABLE example')
            connection.exec_driver_sql('CREATE TABLE example (id INTEGER PRIMARY KEY, a INTEGER, b INTEGER)')
            inspector = sa.inspect(connection)
            context = MigrationContext.configure(connection, opts={'include_object': include})
            assert any(op[0] == 'add_constraint' for op in compare_metadata(context, target) if isinstance(op, tuple))
    finally:
        engine.dispose()
