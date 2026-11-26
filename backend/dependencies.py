"""Request-owned resources; manual service workers keep their own factories."""
from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.models.use_case import get_session


def get_db() -> Generator[Session, None, None]:
    """Return every request's connection to its pool, including on failure."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
