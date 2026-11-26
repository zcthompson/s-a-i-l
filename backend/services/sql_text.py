"""SQL expressions matching Python's whitespace trimming on supported stores."""
from sqlalchemy import func

# Python's Unicode whitespace definition, supplied as a bound parameter.
PYTHON_WHITESPACE = ''.join(chr(value) for value in range(0x110000) if chr(value).isspace())


def strip_expression(db, column):
    if db.get_bind().dialect.name == 'postgresql':
        return func.btrim(func.coalesce(column, ''), PYTHON_WHITESPACE)
    return func.sail_strip(column)
