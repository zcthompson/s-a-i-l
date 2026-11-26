"""WP19 — customer vertical field + verticals endpoint.

Deterministic TestClient tests against the temp DB (no LLM). Follows the
test_template_flow.py auth pattern: conftest `client` + `db_session`
fixtures with a local autouse `_auth_user_lookup` that keeps the JWT +
junction lookups on the shared test engine.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from unittest.mock import patch

import pytest
from backend.models.use_case import Customer, CustomerUser, User

from tests.backend.common import _token

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"

@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "department": user.department,
            "is_admin": user.is_admin,
            "role": user.role,
            "user_id": user.id,
        }

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", lambda *a, **k: shared_engine):
        yield




@pytest.fixture
def users(db_session):
    def _u(name, is_admin):
        return User(
            username=name, email=f"{name}@test.local",
            hashed_password=_FAKE_BCRYPT_HASH,
            display_name=name, department="IT",
            is_admin=is_admin, approved=1, is_active=1,
        )

    admin = _u("vert_admin", 1)
    owner = _u("vert_owner", 0)
    db_session.add_all([admin, owner])
    db_session.commit()
    return {"admin": admin, "owner": owner}


def test_create_customer_with_valid_vertical(client, users):
    r = client.post("/api/customers/", json={
        "name": "VerticalCo", "description": "d", "vertical": "Financial Services",
    }, headers=_token("vert_admin", True))
    assert r.status_code == 201
    assert r.json()["vertical"] == "Financial Services"


def test_create_customer_vertical_case_insensitive(client, users):
    r = client.post("/api/customers/", json={
        "name": "OtherCo", "vertical": "other",
    }, headers=_token("vert_admin", True))
    assert r.status_code == 201
    assert r.json()["vertical"] == "Other"


def test_create_customer_invalid_vertical_422(client, users):
    r = client.post("/api/customers/", json={
        "name": "BadCo", "vertical": "Underwater Basket Weaving",
    }, headers=_token("vert_admin", True))
    assert r.status_code == 422


def test_create_customer_no_vertical(client, users):
    r = client.post("/api/customers/", json={"name": "NoVertCo"},
                    headers=_token("vert_admin", True))
    assert r.status_code == 201
    assert r.json()["vertical"] is None


def test_list_and_detail_carry_vertical(client, users, db_session):
    client.post("/api/customers/", json={"name": "ListCo", "vertical": "Manufacturing"},
                headers=_token("vert_admin", True))
    detail = client.get("/api/customers/ListCo/", headers=_token("vert_admin", True))
    assert detail.json()["vertical"] == "Manufacturing"
    listing = client.get("/api/customers/", headers=_token("vert_admin", True))
    row = next(c for c in listing.json() if c["name"] == "ListCo")
    assert row["vertical"] == "Manufacturing"


def test_put_updates_vertical_admin(client, users):
    client.post("/api/customers/", json={"name": "PutCo", "vertical": "Education"},
                headers=_token("vert_admin", True))
    r = client.put("/api/customers/PutCo/", json={"vertical": "Insurance"},
                   headers=_token("vert_admin", True))
    assert r.status_code == 200
    assert r.json()["vertical"] == "Insurance"


def test_put_updates_vertical_owner(client, users, db_session):
    client.post("/api/customers/", json={"name": "OwnerPutCo", "vertical": "Education"},
                headers=_token("vert_admin", True))
    cust = db_session.query(Customer).filter(Customer.name == "OwnerPutCo").first()
    owner = db_session.query(User).filter(User.username == "vert_owner").first()
    db_session.add(CustomerUser(customer_id=cust.id, user_id=owner.id, role="owner"))
    db_session.commit()
    r = client.put("/api/customers/OwnerPutCo/", json={"vertical": "Retail & E-Commerce"},
                   headers=_token("vert_owner"))
    assert r.status_code == 200
    assert r.json()["vertical"] == "Retail & E-Commerce"


def test_put_invalid_vertical_422(client, users):
    client.post("/api/customers/", json={"name": "PutBadCo"},
                headers=_token("vert_admin", True))
    r = client.put("/api/customers/PutBadCo/", json={"vertical": "Nope"},
                   headers=_token("vert_admin", True))
    assert r.status_code == 422


def test_verticals_endpoint_shape(client, users):
    r = client.get("/api/customers/verticals/", headers=_token("vert_admin", True))
    assert r.status_code == 200
    data = r.json()
    assert len(data["verticals"]) == 13
    assert "Other" in data["verticals"]
    dbv = data["departments_by_vertical"]
    assert set(dbv) == set(data["verticals"])
    for name, depts in dbv.items():
        assert len(depts) == 4


def test_verticals_endpoint_anonymous_401(client):
    r = client.get("/api/customers/verticals/")
    assert r.status_code == 401
