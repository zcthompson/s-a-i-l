"""Part 14 (A2/A3) — customer alias write surface.

- write rules: empty / own name / another customer's name → exact 422;
  duplicate (any customer, normalized) → exact 409, race-safe via the
  unique constraint + IntegrityError fallback;
- gate matrix: admin + owner read/write; member + auditor read-only
  (exact 403 on writes); outsider and missing customer → byte-identical
  404 "Customer not found" on every verb (no existence oracle);
- list ordering (raw codepoint) and delete semantics.

Run: pytest tests/backend/test_part14_alias_api.py -v
"""

import os
from urllib.parse import quote

import pytest

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

from backend.auth import create_access_token  # noqa: E402
from backend.models.customer_alias import CustomerAlias  # noqa: E402
from backend.models.use_case import Customer, CustomerUser, User  # noqa: E402
from backend.services import customer_alias_service  # noqa: E402

WRITE_REQUIRED = "Customer owner, sales admin, or admin required"
NOT_FOUND = {"detail": "Customer not found"}


def _headers(username: str) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': username})}"}


def _url(name: str, alias_id: int | None = None) -> str:
    base = f"/api/customers/{quote(name)}/aliases/"
    return base if alias_id is None else f"{base}{alias_id}/"


def _user(db_session, username: str, junctions=(), role="user", sales_role=None):
    user = User(username=username, email=f"{username}@test.local", hashed_password="unused",
                display_name=username, department="Sales", is_admin=0, approved=1,
                is_active=1, role=role, sales_role=sales_role)
    db_session.add(user)
    db_session.flush()
    for customer, role in junctions:
        db_session.add(CustomerUser(customer_id=customer.id, user_id=user.id, role=role))
    return user


def _alias(db_session, customer, alias):
    row = CustomerAlias(customer_id=customer.id, alias=alias,
                        alias_norm=customer_alias_service.normalize_alias(alias),
                        created_by="admin")
    db_session.add(row)
    db_session.commit()
    return row


@pytest.fixture()
def world(db_session):
    zeta = Customer(name="Zeta Co")
    other = Customer(name="Other Inc")
    bare = Customer(name="Bare LLC")
    db_session.add_all([zeta, other, bare])
    db_session.flush()
    _user(db_session, "al_owner", [(zeta, "owner")])
    _user(db_session, "al_member", [(zeta, "member")])
    _user(db_session, "al_auditor", [(zeta, "auditor")])
    _user(db_session, "al_outsider", [(other, "owner")])
    # 2026-11-01 directive: the sales admin manages aliases — sales_admin is
    # a SALES_ROLE value (effective_role, the central source of truth); a
    # global one (no junction row on Zeta Co) plus one who is ALSO a member
    # (the sales role, not a junction leg, is what confers the write).
    _user(db_session, "al_sales_admin", sales_role="sales_admin")
    _user(db_session, "al_sales_admin_member", [(zeta, "member")], sales_role="sales_admin")
    db_session.commit()
    zeta_alias = _alias(db_session, zeta, "Zeta Holdings")
    other_alias = _alias(db_session, other, "Other Group")
    return {"zeta": zeta, "other": other, "bare": bare,
            "zeta_alias_id": zeta_alias.id, "other_alias_id": other_alias.id}


def _post(client, name, alias, user="admin"):
    return client.post(_url(name), json={"alias": alias}, headers=_headers(user))


def _norms(db_session):
    db_session.expire_all()
    return sorted(row.alias_norm for row in db_session.query(CustomerAlias).all())


# ── write rules ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("alias", ["", "   ", "\t \n"])
def test_empty_alias_is_service_422(client, world, alias):
    resp = _post(client, "Zeta Co", alias)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Alias must not be empty"}


def test_missing_field_is_stock_422(client, world):
    resp = client.post(_url("Zeta Co"), json={}, headers=_headers("admin"))
    assert resp.status_code == 422
    assert resp.json()["detail"] != "Alias must not be empty"


@pytest.mark.parametrize("alias", ["Zeta Co", "  ZETA  co "])
def test_own_name_is_422(client, world, db_session, alias):
    resp = _post(client, "Zeta Co", alias)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Alias must differ from the customer name"}
    assert _norms(db_session) == ["other group", "zeta holdings"]


@pytest.mark.parametrize("alias", ["Other Inc", " other   INC"])
def test_other_customer_name_is_422(client, world, db_session, alias):
    resp = _post(client, "Zeta Co", alias)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "Alias matches an existing customer name"}
    assert _norms(db_session) == ["other group", "zeta holdings"]


@pytest.mark.parametrize("alias", ["Zeta Holdings", " zeta   HOLDINGS ", "Other Group", "other group"])
def test_duplicate_alias_any_customer_is_409(client, world, db_session, alias):
    resp = _post(client, "Zeta Co", alias)
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Alias already in use"}
    assert _norms(db_session) == ["other group", "zeta holdings"]


def test_duplicate_race_integrity_fallback_is_409(client, world, db_session, monkeypatch):
    """The pre-check misses (a concurrent insert landed after it): the unique
    constraint fires, the pending insert is rolled back, and the route still
    answers the same 409."""
    calls = []

    def miss(db, alias_norm):
        calls.append(alias_norm)
        return None

    monkeypatch.setattr(customer_alias_service, "_find_by_norm", miss)
    resp = _post(client, "Zeta Co", "  OTHER group")
    assert calls == ["other group"]
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Alias already in use"}
    assert _norms(db_session) == ["other group", "zeta holdings"]
    # The session is usable after the rollback: a fresh alias still lands.
    assert _post(client, "Zeta Co", "Zeta North").status_code == 201


def test_add_stores_raw_alias_norm_and_creator(client, world, db_session):
    resp = _post(client, "Zeta Co", "Zeta  NORTH", user="al_owner")
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == {"id", "alias", "created_by", "created_at"}
    assert body["alias"] == "Zeta  NORTH"
    assert body["created_by"] == "al_owner"
    assert body["created_at"]
    db_session.expire_all()
    row = db_session.get(CustomerAlias, body["id"])
    assert (row.customer_id, row.alias_norm) == (world["zeta"].id, "zeta north")


# ── gate matrix ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("user", ["admin", "al_owner"])
def test_admin_and_owner_read_and_write(client, world, user):
    hdr = _headers(user)
    listed = client.get(_url("Zeta Co"), headers=hdr)
    assert listed.status_code == 200
    assert [a["alias"] for a in listed.json()] == ["Zeta Holdings"]
    created = client.post(_url("Zeta Co"), json={"alias": f"Zeta {user}"}, headers=hdr)
    assert created.status_code == 201
    deleted = client.delete(_url("Zeta Co", created.json()["id"]), headers=hdr)
    assert deleted.status_code == 204


@pytest.mark.parametrize("user", ["al_member", "al_auditor"])
def test_member_and_auditor_read_only(client, world, db_session, user):
    hdr = _headers(user)
    listed = client.get(_url("Zeta Co"), headers=hdr)
    assert listed.status_code == 200
    assert [a["alias"] for a in listed.json()] == ["Zeta Holdings"]
    created = client.post(_url("Zeta Co"), json={"alias": "Zeta New"}, headers=hdr)
    assert created.status_code == 403
    assert created.json() == {"detail": WRITE_REQUIRED}
    deleted = client.delete(_url("Zeta Co", world["zeta_alias_id"]), headers=hdr)
    assert deleted.status_code == 403
    assert deleted.json() == {"detail": WRITE_REQUIRED}
    assert _norms(db_session) == ["other group", "zeta holdings"]


@pytest.mark.parametrize("user", ["al_sales_admin", "al_sales_admin_member"])
def test_sales_admin_writes_aliases(client, world, db_session, user):
    """2026-11-01 operator directive: admin, the account owner, and the
    sales admin all manage the alias section. The global sales_admin has
    NO junction row on Zeta Co (role-based write, read-all scope); the
    member+junction sales_admin proves the role, not the junction,
    confers the write."""
    hdr = _headers(user)
    listed = client.get(_url("Zeta Co"), headers=hdr)
    assert listed.status_code == 200
    created = client.post(_url("Zeta Co"), json={"alias": f"Zeta {user}"}, headers=hdr)
    assert created.status_code == 201
    assert created.json()["created_by"] == user
    deleted = client.delete(_url("Zeta Co", created.json()["id"]), headers=hdr)
    assert deleted.status_code == 204
    assert _norms(db_session) == ["other group", "zeta holdings"]


def test_outsider_404_byte_identical_to_missing_on_all_verbs(client, world, db_session):
    hdr = _headers("al_outsider")
    missing = "No Such Customer"
    pairs = [
        (client.get(_url("Zeta Co"), headers=hdr), client.get(_url(missing), headers=hdr)),
        (client.post(_url("Zeta Co"), json={"alias": "Zeta New"}, headers=hdr),
         client.post(_url(missing), json={"alias": "Zeta New"}, headers=hdr)),
        (client.delete(_url("Zeta Co", world["zeta_alias_id"]), headers=hdr),
         client.delete(_url(missing, world["zeta_alias_id"]), headers=hdr)),
    ]
    for scoped, absent in pairs:
        assert scoped.status_code == absent.status_code == 404
        assert scoped.content == absent.content
        assert scoped.json() == NOT_FOUND
    assert _norms(db_session) == ["other group", "zeta holdings"]


def test_outsider_get_leaks_no_alias_content(client, world):
    resp = client.get(_url("Zeta Co"), headers=_headers("al_outsider"))
    assert resp.status_code == 404
    assert b"Zeta Holdings" not in resp.content
    assert b"zeta holdings" not in resp.content.lower()


@pytest.mark.parametrize("method", ["get", "post", "delete"])
def test_missing_customer_is_404_even_for_admin(client, world, method):
    hdr = _headers("admin")
    if method == "get":
        resp = client.get(_url("No Such Customer"), headers=hdr)
    elif method == "post":
        resp = client.post(_url("No Such Customer"), json={"alias": "x"}, headers=hdr)
    else:
        resp = client.delete(_url("No Such Customer", 1), headers=hdr)
    assert resp.status_code == 404
    assert resp.json() == NOT_FOUND


def test_unauthenticated_is_401(client, world):
    assert client.get(_url("Zeta Co")).status_code == 401
    assert client.post(_url("Zeta Co"), json={"alias": "x"}).status_code == 401
    assert client.delete(_url("Zeta Co", world["zeta_alias_id"])).status_code == 401


# ── list ordering + delete ───────────────────────────────────────────────

def test_list_order_is_raw_codepoint(client, world):
    hdr = _headers("admin")
    for alias in ("b", "A", "c"):
        assert client.post(_url("Bare LLC"), json={"alias": alias}, headers=hdr).status_code == 201
    resp = client.get(_url("Bare LLC"), headers=hdr)
    assert resp.status_code == 200
    assert [a["alias"] for a in resp.json()] == ["A", "b", "c"]


def test_customer_without_aliases_lists_empty(client, world):
    resp = client.get(_url("Bare LLC"), headers=_headers("admin"))
    assert resp.status_code == 200
    assert resp.json() == []


def test_delete_removes_row_and_repeat_is_404(client, world, db_session):
    hdr = _headers("al_owner")
    alias_id = world["zeta_alias_id"]
    resp = client.delete(_url("Zeta Co", alias_id), headers=hdr)
    assert resp.status_code == 204
    assert resp.content == b""
    db_session.expire_all()
    assert db_session.get(CustomerAlias, alias_id) is None
    assert client.get(_url("Zeta Co"), headers=hdr).json() == []
    again = client.delete(_url("Zeta Co", alias_id), headers=hdr)
    assert again.status_code == 404
    assert again.json() == {"detail": "Alias not found"}


def test_delete_other_customers_alias_id_is_404(client, world, db_session):
    resp = client.delete(_url("Zeta Co", world["other_alias_id"]), headers=_headers("admin"))
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Alias not found"}
    assert _norms(db_session) == ["other group", "zeta holdings"]


def test_deleted_alias_frees_the_slot(client, world):
    hdr = _headers("admin")
    assert client.delete(_url("Other Inc", world["other_alias_id"]), headers=hdr).status_code == 204
    resp = client.post(_url("Zeta Co"), json={"alias": "OTHER GROUP"}, headers=hdr)
    assert resp.status_code == 201
