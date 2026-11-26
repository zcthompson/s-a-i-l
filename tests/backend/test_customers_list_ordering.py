"""Customer list ordering regression (newest-first).

Regression: a just-created customer was persisted and returned by the API
but was NOT visible in the UI. Root cause: the list was returned in
unsorted rowid order, so a fresh customer (the highest id) landed at the END
of a long, 20-per-page list and was invisible on page 1.

Fix: `list_all_customers` / `get_accessible_customers` order newest-first
(created_at DESC, id DESC). These tests pin that ordering — a new customer
is the FIRST row, regardless of its (highest) rowid.
"""

import os
from datetime import datetime

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest
from backend.models.use_case import Customer, CustomerUser, User
from backend.services.customers_service import (
    get_accessible_customers,
    list_all_customers,
)

_T1 = datetime(2026, 1, 1, 0, 0, 0)
_T2 = datetime(2026, 6, 1, 0, 0, 0)
_T3 = datetime(2026, 9, 1, 0, 0, 0)


@pytest.fixture
def ordered(db_session):
    # Create in T1, T2, T3 order so rowid == (T1 < T2 < T3). The newest-first
    # list must therefore be the REVERSE of insertion/rowid order: T3, T2, T1.
    admin = User(username="order_admin", email="order_admin@test.local",
                 hashed_password="x", display_name="Order Admin",
                 department="IT", is_admin=1, approved=1, is_active=1)
    rep = User(username="order_rep", email="order_rep@test.local",
               hashed_password="x", display_name="Order Rep",
               department="IT", is_admin=0, approved=1, is_active=1)
    db_session.add_all([admin, rep])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(rep)

    old = Customer(name="Order Old", created_at=_T1)
    mid = Customer(name="Order Mid", created_at=_T2)
    new = Customer(name="Order New", created_at=_T3)
    db_session.add_all([old, mid, new])
    db_session.commit()
    db_session.refresh(old)
    db_session.refresh(mid)
    db_session.refresh(new)

    # Rowid order (sanity): old < mid < new.
    assert old.id < mid.id < new.id

    # rep is scoped to all three (junction membership) to also exercise the
    # junction branch of get_accessible_customers.
    for c in (old, mid, new):
        db_session.add(CustomerUser(customer_id=c.id, user_id=rep.id, role="member",
                                    granted_by=admin.id))
    db_session.commit()
    return {"admin": admin, "rep": rep, "old": old, "mid": mid, "new": new}


def test_admin_list_is_newest_first(db_session, ordered):
    rows = list_all_customers(db_session)
    names = [c.name for c in rows]
    # Newest-first: T3 (Order New) is the FIRST row even though it has the
    # highest rowid (last inserted).
    assert names[0] == "Order New"
    # The full set is present, just reordered.
    assert set(names) >= {"Order Old", "Order Mid", "Order New"}
    # Reverse of insertion/rowid order for the three.
    assert names.index("Order New") < names.index("Order Mid") < names.index("Order Old")


def test_junction_list_is_newest_first(db_session, ordered):
    rep = ordered["rep"]
    # The real request-building path (get_user_from_request) resolves the
    # junction rows into user["customer_ids"]; mirror that here.
    from backend.models.use_case import CustomerUser as _CU
    junction_ids = [
        r.customer_id for r in db_session.query(_CU)
        .filter(_CU.user_id == rep.id).all()
    ]
    user = {"user_id": rep.id, "id": rep.id, "is_admin": 0,
            "username": "order_rep", "customer_ids": junction_ids}
    rows = get_accessible_customers(db_session, user)
    names = [c.name for c in rows]
    assert names[0] == "Order New"
    assert names.index("Order New") < names.index("Order Mid") < names.index("Order Old")


def test_newest_first_at_http_layer(client, db_session, ordered):
    """The route (not just the service) surfaces the new customer first."""
    from backend.auth import create_access_token

    hdr = {"Authorization": f"Bearer {create_access_token({'sub': 'order_admin', 'is_admin': True})}"}
    # The HTTP auth path resolves the real user; seed a matching active user.
    rows = client.get("/api/customers/", headers=hdr)
    assert rows.status_code == 200
    body = rows.json()
    assert isinstance(body, list)
    assert body[0]["name"] == "Order New"
