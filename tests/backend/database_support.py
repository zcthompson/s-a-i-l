"""One selected integration engine and dialect-aware fixture cleanup."""
import sqlalchemy as sa

# Set by conftest after guarded PostgreSQL migration setup / SQLite create_all.
engine = None


def reset_tables(session, *, reset_ids=True):
    from backend.models.use_case import Base

    if session.bind.dialect.name == 'postgresql':
        tables = ', '.join(session.bind.dialect.identifier_preparer.quote(t.name)
                           for t in Base.metadata.sorted_tables)
        identity = ' RESTART IDENTITY' if reset_ids else ''
        session.execute(sa.text(f'TRUNCATE {tables}{identity} CASCADE'))
    else:
        session.execute(sa.text('PRAGMA foreign_keys=OFF'))
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        if reset_ids and sa.inspect(session.connection()).has_table('sqlite_sequence'):
            session.execute(sa.text('DELETE FROM sqlite_sequence'))
    session.commit()
