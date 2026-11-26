"""Shared plain (non-fixture) test helpers.

Importable from any test module via ``from tests.backend.common import ...``.
Pytest fixtures belong in ``tests/backend/conftest.py`` instead.
"""

from backend.auth import create_access_token


def _admin_headers(db_session) -> dict:
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db_session.query(User).filter(User.is_admin == 1).first()
    token = create_access_token({"sub": admin.username, "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


def _headers(username="admin"):
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def _mk_user(db_session, username: str, sales_role: str | None = None):
    from backend.models.use_case import User
    user = User(username=username, email=f"{username}@test.local", hashed_password="unused",
                display_name=username, department="Sales", is_admin=0, approved=1,
                is_active=1, role="user", sales_role=sales_role)
    db_session.add(user)
    db_session.flush()
    return user


def _token(username, is_admin=False):
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': is_admin})}"}
