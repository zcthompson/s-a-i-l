"""Conflict-aware inserts for the supported SQL dialects."""


def insert_for(session, model):
    dialect = session.get_bind().dialect.name
    if dialect == 'sqlite':
        from sqlalchemy.dialects.sqlite import insert
    elif dialect == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        raise ValueError(f'Unsupported conflict-insert database dialect: {dialect}')
    return insert(model)
