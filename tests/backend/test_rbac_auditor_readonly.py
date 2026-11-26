"""RBAC model: the auditor reads the whole application and writes nothing."""

import pytest
from backend.services import sales_access as sa


def _headers(username: str) -> dict:
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': False})}"}


def _mk_user(db, username, sales_role=None, role="user"):
    from backend.models.use_case import User

    u = User(
        username=username, email=f"{username}@test.local", hashed_password="unused",
        display_name=username.title(), department="Sales", is_admin=0, approved=1,
        is_active=1, sales_role=sales_role, role=role,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def w(db_session):
    from backend.models.use_case import Customer, CustomerUser

    x = type("W", (), {})()
    x.a = Customer(name="Aud Alpha")
    x.b = Customer(name="Aud Beta")
    db_session.add_all([x.a, x.b])
    db_session.flush()
    x.aud = _mk_user(db_session, "aud_role", "auditor")
    x.legacy_aud = _mk_user(db_session, "aud_legacy", None, role="auditor")
    x.owner = _mk_user(db_session, "aud_owner", "rep")
    x.sadmin = _mk_user(db_session, "aud_sadmin", "sales_admin")
    db_session.add(CustomerUser(customer_id=x.a.id, user_id=x.owner.id, role="owner"))
    db_session.commit()
    return x


def _ctx(db, user):
    from backend.services import membership_service as svc

    return svc.actor_context(db, user.id)


def test_auditor_scope_is_all_customers(db_session, w):
    for who in (w.aud, w.legacy_aud):
        u = _ctx(db_session, who)
        assert sa.auditor_read_only(u) is True
        assert sa.customer_scope(u, db_session) >= {w.a.id, w.b.id}
        assert sa.can(u, db_session, sa.CAP_READ, w.b.id)
        assert sa.can(u, db_session, sa.CAP_EXPORT, w.a.id)


def test_auditor_has_no_write_caps(db_session, w):
    u = _ctx(db_session, w.aud)
    for cap in (sa.CAP_EDIT, sa.CAP_NOTES, sa.CAP_KNOWLEDGE, sa.CAP_MANAGE_TEAM,
                sa.CAP_TRANSFER_OWNERSHIP, sa.CAP_METADATA, sa.CAP_MANAGE_COOWNERS,
                sa.CAP_INSIDE_GRANTS, sa.CAP_CREATE_SECTION, sa.CAP_OWN_ITEMS,
                sa.CAP_SYSTEM_ADMIN):
        assert not sa.can(u, db_session, cap, w.a.id), cap
        assert not sa.can(u, db_session, cap, w.a.id, section="notes", is_own_item=True), cap
    assert sa.auditor_read_only(_ctx(db_session, w.owner)) is False


def test_auditor_reads_everything_over_api(client, db_session, w):
    h = _headers(w.aud.username)
    for c in (w.a, w.b):
        r = client.get(f"/api/customers/{c.name.replace(' ', '%20')}/", headers=h)
        assert r.status_code == 200, r.text
        assert client.get(f"/api/customers/{c.id}/sales-notes/", headers=h).status_code == 200


def test_auditor_mutations_403(client, db_session, w):
    h = _headers(w.aud.username)
    name = w.a.name.replace(" ", "%20")
    calls = [
        ("post", f"/api/customers/{w.a.id}/sales-notes/",
         {"category": "discovery", "title": "t", "content": "c"}),
        ("put", f"/api/customers/{name}/", {"description": "x"}),
        ("delete", f"/api/customers/{name}/", None),
        ("post", "/api/use-cases/", {"title": "x", "department": "d", "customer_id": w.a.id}),
        ("post", f"/api/customers/{name}/memberships/",
         {"user_id": w.owner.id, "role": "co_owner"}),
    ]
    for method, url, body in calls:
        r = getattr(client, method)(url, headers=h, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (method, url, r.status_code, r.text)
        assert r.json()["detail"] == "Auditor role is read-only"


def test_sales_admin_blocked_from_content_writes_not_memberships(client, db_session, w):
    h = _headers(w.sadmin.username)
    r = client.post(f"/api/customers/{w.a.id}/sales-notes/", headers=h,
                    json={"category": "discovery", "title": "t", "content": "c"})
    assert r.status_code == 403
    name = w.a.name.replace(" ", "%20")
    r = client.post(f"/api/customers/{name}/memberships/", headers=h,
                    json={"user_id": w.aud.id, "role": "inside_sales"})
    assert r.status_code == 201, r.text
