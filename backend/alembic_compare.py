"""Precise comparison of legacy SQLite unnamed unique constraints."""


def include_legacy_unique(inspector, dialect, obj, type_, reflected, compare_to):
    if (dialect == 'sqlite' and type_ == 'unique_constraint'
            and not reflected and compare_to is None):
        columns = tuple(column.name for column in obj.columns)
        return not any(item.get('name') is None and tuple(item['column_names']) == columns
                       for item in inspector.get_unique_constraints(obj.table.name))
    return True
