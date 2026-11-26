"""PostgreSQL allocation floors for retained references and imported IDs."""

import sqlalchemy as sa


def reserve_ids(bind, table: str, references=(), extra_floor: int = 0) -> None:
    """Advance an owned sequence without lowering its existing high-water mark.

    Table/column/filter inputs are trusted migration constants, never user SQL.
    The caller must prevent concurrent writes while importing existing records.
    """
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return
    sequence = bind.execute(sa.text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table}).scalar()
    if sequence is None:
        return
    quote = bind.dialect.identifier_preparer.quote
    maximum = bind.execute(sa.text(f'SELECT COALESCE(MAX(id), 0) FROM {quote(table)}')).scalar_one()
    candidates = [0, maximum, extra_floor]
    # pg_get_serial_sequence returns a server-generated, quoted qualified name.
    current, called = bind.exec_driver_sql(f"SELECT last_value, is_called FROM {sequence}").one()
    candidates.append(current if called else current - 1)
    for child, column, condition in references:
        if not inspector.has_table(child) or column not in {c['name'] for c in inspector.get_columns(child)}:
            continue
        where = f" WHERE {condition}" if condition else ""
        candidates.append(bind.execute(sa.text(
            f'SELECT COALESCE(MAX({quote(column)}), 0) FROM {quote(child)}{where}'
        )).scalar_one())
    floor = max(candidates)
    bind.execute(sa.text("SELECT setval(CAST(:sequence AS regclass), :value, :called)"),
                 {"sequence": sequence, "value": max(1, floor), "called": floor > 0})
