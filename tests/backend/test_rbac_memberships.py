"""RBAC core: account memberships, resolver semantics, ownership transfer,
section grants, audit trail, ownership-review queue, migration backfill."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from backend.services import sales_access as sa

ROOT = Path(__file__).resolve().parents[2]


def _headers(username: str) -> dict:
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': False})}"}


def _admin_headers(db) -> dict:
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db.query(User).filter(User.is_admin == 1).first()
    return {"Authorization": f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"}


def _mk_user(db, username, sales_role=None, is_admin=0):
    from backend.models.use_case import User

    u = User(
        username=username, email=f"{username}@test.local", hashed_password="unused",
        display_name=username.title(), department="Sales", is_admin=is_admin,
        approved=1, is_active=1, sales_role=sales_role,
    )
    db.add(u)
    db.flush()
    return u


def _ctx(db, user) -> dict:
    from backend.services import membership_service as svc

    return svc.actor_context(db, user.id)


def _mem(db, customer, user, role, grants=None):
    from backend.models.account_membership import AccountMembership

    db.add(AccountMembership(
        user_id=user.id, customer_id=customer.id, role=role, section_grants=grants,
    ))
    db.commit()


@pytest.fixture()
def w(db_session):
    from backend.models.use_case import Customer, CustomerUser

    x = type("W", (), {})()
    x.acme = Customer(name="Acme Corp")
    x.other = Customer(name="Other Corp")
    db_session.add_all([x.acme, x.other])
    db_session.flush()
    x.po = _mk_user(db_session, "po_user", "rep")
    x.po2 = _mk_user(db_session, "po_two", "rep")
    x.co = _mk_user(db_session, "co_user", "rep")
    x.ops = _mk_user(db_session, "ops_user", "sales_ops")
    x.ins = _mk_user(db_session, "ins_user", "inside_sales")
    x.sadmin = _mk_user(db_session, "sadmin_user", "sales_admin")
    x.nobody = _mk_user(db_session, "nobody_user")
    db_session.add(CustomerUser(customer_id=x.acme.id, user_id=x.po.id, role="owner"))
    db_session.commit()
    _mem(db_session, x.acme, x.po, "primary_owner")
    _mem(db_session, x.acme, x.co, "co_owner")
    _mem(db_session, x.acme, x.ops, "sales_ops")
    _mem(db_session, x.acme, x.ins, "inside_sales")
    return x


def _url(c, tail):
    return f"/api/customers/{c.name.replace(' ', '%20')}/{tail}"


def _audit(db, action):
    from backend.models.collaboration import AuditLog

    db.expire_all()
    return db.query(AuditLog).filter(AuditLog.action == action).order_by(AuditLog.id).all()


# ── resolver (unit level) ──────────────────────────────────────────────────


class TestResolverMemberships:
    def test_primary_owner_caps(self, db_session, w):
        u = _ctx(db_session, w.po)
        for cap in (sa.CAP_READ, sa.CAP_EXPORT, sa.CAP_EDIT, sa.CAP_NOTES, sa.CAP_KNOWLEDGE,
                    sa.CAP_METADATA, sa.CAP_MANAGE_COOWNERS, sa.CAP_INSIDE_GRANTS,
                    sa.CAP_CREATE_SECTION, sa.CAP_OWN_ITEMS, sa.CAP_TRANSFER_OWNERSHIP):
            assert sa.can(u, db_session, cap, w.acme.id), cap
        assert not sa.can(u, db_session, sa.CAP_READ, w.other.id)

    def test_sales_ops_is_owner_alias_without_transfer(self, db_session, w):
        u = _ctx(db_session, w.ops)
        assert sa._customer_level(u, db_session, w.acme.id) == "owner"
        assert sa.can(u, db_session, sa.CAP_EDIT, w.acme.id)
        assert sa.can(u, db_session, sa.CAP_MANAGE_COOWNERS, w.acme.id)
        assert sa.can(u, db_session, sa.CAP_INSIDE_GRANTS, w.acme.id)
        assert not sa.can(u, db_session, sa.CAP_TRANSFER_OWNERSHIP, w.acme.id)

    def test_co_owner_cannot_manage_coowners_or_transfer(self, db_session, w):
        u = _ctx(db_session, w.co)
        assert sa.can(u, db_session, sa.CAP_EDIT, w.acme.id)
        assert sa.can(u, db_session, sa.CAP_INSIDE_GRANTS, w.acme.id)
        assert not sa.can(u, db_session, sa.CAP_MANAGE_COOWNERS, w.acme.id)
        assert not sa.can(u, db_session, sa.CAP_TRANSFER_OWNERSHIP, w.acme.id)

    def test_inside_sales_defaults_to_read_only(self, db_session, w):
        u = _ctx(db_session, w.ins)
        assert sa.can(u, db_session, sa.CAP_READ, w.acme.id)
        assert not sa.can(u, db_session, sa.CAP_EDIT, w.acme.id)
        for section in ("notes", "contacts"):
            assert not sa.can(u, db_session, sa.CAP_NOTES, w.acme.id, section=section)
            assert not sa.can(u, db_session, sa.CAP_CREATE_SECTION, w.acme.id, section=section)
        assert not sa.can(u, db_session, sa.CAP_NOTES, w.acme.id)  # no section = deny

    def test_inside_sales_contribute_is_per_section(self, db_session, w):
        from backend.models.account_membership import AccountMembership

        row = db_session.query(AccountMembership).filter_by(user_id=w.ins.id).one()
        row.section_grants = {"notes": "contribute", "contacts": "read"}
        db_session.commit()
        u = _ctx(db_session, w.ins)
        assert sa.can(u, db_session, sa.CAP_CREATE_SECTION, w.acme.id, section="notes")
        assert sa.can(u, db_session, sa.CAP_NOTES, w.acme.id, section="notes", is_own_item=True)
        assert not sa.can(u, db_session, sa.CAP_CREATE_SECTION, w.acme.id, section="contacts")
        assert not sa.can(u, db_session, sa.CAP_CREATE_SECTION, w.acme.id, section="forecasts")
        assert not sa.can(u, db_session, sa.CAP_EDIT, w.acme.id, section="notes")

    def test_expired_membership_ignored(self, db_session, w):
        from datetime import datetime, timedelta

        from backend.models.account_membership import AccountMembership

        row = db_session.query(AccountMembership).filter_by(user_id=w.co.id).one()
        row.expires_at = datetime.utcnow() - timedelta(days=1)
        db_session.commit()
        u = _ctx(db_session, w.co)
        assert not sa.can(u, db_session, sa.CAP_READ, w.acme.id)

    def test_sales_admin_scope_all_content_caps_denied(self, db_session, w):
        u = _ctx(db_session, w.sadmin)
        assert sa.effective_role(u) == "sales_admin"
        assert sa.is_unrestricted(u) is False
        assert sa.customer_scope(u, db_session) >= {w.acme.id, w.other.id}
        assert not sa.can(u, db_session, sa.CAP_EXPORT, w.acme.id)
        assert not sa.can(u, db_session, sa.CAP_EDIT, w.acme.id)
        assert not sa.can(u, db_session, sa.CAP_NOTES, w.acme.id)

    def test_may_grant_role_policy(self, db_session, w):
        admin = {"username": "a", "is_admin": 1}
        assert sa.may_grant_role(admin, "auditor")
        sadmin = _ctx(db_session, w.sadmin)
        for r in ("primary_owner", "co_owner", "sales_ops", "inside_sales"):
            assert sa.may_grant_role(sadmin, r), r
        for r in ("auditor", "admin", "sales_admin"):
            assert not sa.may_grant_role(sadmin, r), r
        cid = w.acme.id
        po, ops, co = (_ctx(db_session, x) for x in (w.po, w.ops, w.co))
        assert sa.may_grant_role(po, "co_owner", cid, db_session)
        assert sa.may_grant_role(po, "inside_sales", cid, db_session)
        assert sa.may_grant_role(ops, "co_owner", cid, db_session)
        assert not sa.may_grant_role(ops, "sales_ops", cid, db_session)
        assert sa.may_grant_role(co, "inside_sales", cid, db_session)
        assert not sa.may_grant_role(co, "co_owner", cid, db_session)
        assert not sa.may_grant_role(co, "primary_owner", cid, db_session)
        assert not sa.may_grant_role(co, "inside_sales", w.other.id, db_session)


# ── routes ─────────────────────────────────────────────────────────────────


class TestMembershipRoutes:
    def test_list_requires_read_and_exposes_grants(self, client, db_session, w):
        r = client.get(_url(w.acme, "memberships/"), headers=_headers(w.po.username))
        assert r.status_code == 200, r.text
        members = {(m["username"], m["role"]) for m in r.json()["members"]}
        assert ("co_user", "co_owner") in members and ("ins_user", "inside_sales") in members
        assert "hashed_password" not in r.text
        # 404-first: no read scope is the same 404 as a missing customer.
        assert client.get(_url(w.acme, "memberships/"),
                          headers=_headers(w.nobody.username)).status_code == 404
        assert client.get(_url(w.acme, "memberships/")).status_code == 401
        assert client.get("/api/customers/Nope/memberships/",
                          headers=_admin_headers(db_session)).status_code == 404

    def test_add_and_remove_audited(self, client, db_session, w):
        h = _headers(w.po.username)
        r = client.post(_url(w.acme, "memberships/"), headers=h,
                        json={"user_id": w.nobody.id, "role": "co_owner"})
        assert r.status_code == 201, r.text
        rows = _audit(db_session, "membership.add")
        assert len(rows) == 1
        assert rows[0].username == w.po.username and rows[0].user_id == w.po.id
        assert rows[0].customer_id == w.acme.id and rows[0].target_id == w.nobody.id
        d = json.loads(rows[0].details)
        assert {"user_id": w.nobody.id, "role": "co_owner", "section_grants": None} in d["after"]
        assert {"user_id": w.nobody.id, "role": "co_owner", "section_grants": None} not in d["before"]

        r = client.delete(_url(w.acme, f"memberships/{w.nobody.id}/?role=co_owner"), headers=h)
        assert r.status_code == 200, r.text
        assert len(_audit(db_session, "membership.remove")) == 1
        again = client.delete(_url(w.acme, f"memberships/{w.nobody.id}/?role=co_owner"), headers=h)
        assert again.status_code == 404

    def test_duplicate_and_unknown_user(self, client, db_session, w):
        h = _headers(w.po.username)
        assert client.post(_url(w.acme, "memberships/"), headers=h,
                           json={"user_id": w.co.id, "role": "co_owner"}).status_code == 409
        assert client.post(_url(w.acme, "memberships/"), headers=h,
                           json={"user_id": 99999, "role": "co_owner"}).status_code == 404

    def test_second_primary_owner_is_409_use_transfer(self, client, db_session, w):
        r = client.post(_url(w.acme, "memberships/"), headers=_admin_headers(db_session),
                        json={"user_id": w.po2.id, "role": "primary_owner"})
        assert r.status_code == 409

    def test_co_owner_cannot_manage_coowners_no_self_escalation(self, client, db_session, w):
        h = _headers(w.co.username)
        r = client.post(_url(w.acme, "memberships/"), headers=h,
                        json={"user_id": w.co.id, "role": "co_owner"})
        assert r.status_code == 403
        r = client.post(_url(w.acme, "memberships/"), headers=h,
                        json={"user_id": w.nobody.id, "role": "co_owner"})
        assert r.status_code == 403
        r = client.delete(_url(w.acme, f"memberships/{w.co.id}/?role=co_owner"), headers=h)
        assert r.status_code == 403
        # but a co_owner may grant inside-sales access
        r = client.post(_url(w.acme, "memberships/"), headers=h,
                        json={"user_id": w.nobody.id, "role": "inside_sales"})
        assert r.status_code == 201, r.text

    def test_nobody_cannot_grant(self, client, db_session, w):
        r = client.post(_url(w.acme, "memberships/"), headers=_headers(w.nobody.username),
                        json={"user_id": w.nobody.id, "role": "inside_sales"})
        # nobody has no read scope on acme: 404-first.
        assert r.status_code == 404

    def test_sales_admin_grant_limits(self, client, db_session, w):
        h = _headers(w.sadmin.username)
        r = client.post(_url(w.acme, "memberships/"), headers=h,
                        json={"user_id": w.nobody.id, "role": "sales_ops"})
        assert r.status_code == 201, r.text

    def test_sales_ops_route_matrix(self, client, db_session, w):
        h = _headers(w.ops.username)
        r = client.post(_url(w.acme, "transfer-ownership/"), headers=h, json={"user_id": w.po2.id})
        assert r.status_code == 403
        r = client.post(_url(w.acme, "memberships/"), headers=h,
                        json={"user_id": w.nobody.id, "role": "co_owner"})
        assert r.status_code == 201, r.text

    def test_last_primary_owner_cannot_be_removed(self, client, db_session, w):
        r = client.delete(_url(w.acme, f"memberships/{w.po.id}/?role=primary_owner"),
                          headers=_admin_headers(db_session))
        assert r.status_code == 409


class TestTransfer:
    def test_transfer_demotes_old_owner_to_co_owner(self, client, db_session, w):
        from backend.models.account_membership import AccountMembership
        from backend.models.use_case import CustomerUser

        r = client.post(_url(w.acme, "transfer-ownership/"), headers=_headers(w.po.username),
                        json={"user_id": w.po2.id})
        assert r.status_code == 200, r.text
        db_session.expire_all()
        roles = {(m.user_id, m.role) for m in
                 db_session.query(AccountMembership).filter_by(customer_id=w.acme.id)}
        assert (w.po2.id, "primary_owner") in roles
        assert (w.po.id, "co_owner") in roles
        assert (w.po.id, "primary_owner") not in roles
        jr = {c.user_id: c.role for c in db_session.query(CustomerUser).filter_by(customer_id=w.acme.id)}
        assert jr[w.po2.id] == "owner" and jr[w.po.id] == "member"
        rows = _audit(db_session, "ownership.transfer")
        assert len(rows) == 1 and rows[0].username == w.po.username
        d = json.loads(rows[0].details)
        assert w.po.id in d["previous_owners"] and d["before"] != d["after"]
        assert d["new_username"] == w.po2.username
        timeline = client.get(f"/api/customers/{w.acme.id}/timeline/", headers=_admin_headers(db_session))
        assert timeline.status_code == 200
        transfers = [item for item in timeline.json()["items"]
                     if item["kind"] == "membership" and item["title"].startswith("Ownership transferred")]
        assert [item["title"] for item in transfers] == [f"Ownership transferred to {w.po2.username}"]
        # the former owner can no longer transfer
        r = client.post(_url(w.acme, "transfer-ownership/"), headers=_headers(w.po.username),
                        json={"user_id": w.po.id})
        assert r.status_code == 403

    def test_co_owner_cannot_transfer_or_self_escalate(self, client, db_session, w):
        h = _headers(w.co.username)
        assert client.post(_url(w.acme, "transfer-ownership/"), headers=h,
                           json={"user_id": w.co.id}).status_code == 403

    def test_sales_admin_and_admin_may_transfer(self, client, db_session, w):
        r = client.post(_url(w.acme, "transfer-ownership/"), headers=_headers(w.sadmin.username),
                        json={"user_id": w.po2.id})
        assert r.status_code == 200, r.text
        r = client.post(_url(w.acme, "transfer-ownership/"), headers=_admin_headers(db_session),
                        json={"user_id": w.po.id})
        assert r.status_code == 200, r.text

    def test_transfer_to_existing_co_owner_and_noop(self, client, db_session, w):
        from backend.models.account_membership import AccountMembership

        h = _admin_headers(db_session)
        assert client.post(_url(w.acme, "transfer-ownership/"), headers=h,
                           json={"user_id": w.co.id}).status_code == 200
        db_session.expire_all()
        roles = [(m.user_id, m.role) for m in
                 db_session.query(AccountMembership).filter_by(customer_id=w.acme.id, user_id=w.co.id)]
        assert roles == [(w.co.id, "primary_owner")]  # superseded, not duplicated
        assert client.post(_url(w.acme, "transfer-ownership/"), headers=h,
                           json={"user_id": w.co.id}).status_code == 409
        assert client.post(_url(w.acme, "transfer-ownership/"), headers=h,
                           json={"user_id": 99999}).status_code == 404


class TestSectionGrants:
    def test_put_grants_then_resolver_follows(self, client, db_session, w):
        r = client.put(_url(w.acme, f"memberships/{w.ins.id}/grants/"),
                       headers=_headers(w.co.username),
                       json={"section_grants": {"notes": "contribute", "contacts": "read"}})
        assert r.status_code == 200, r.text
        u = _ctx(db_session, w.ins)
        assert sa.can(u, db_session, sa.CAP_NOTES, w.acme.id, section="notes")
        assert not sa.can(u, db_session, sa.CAP_NOTES, w.acme.id, section="contacts")
        rows = _audit(db_session, "membership.grants")
        assert len(rows) == 1 and rows[0].username == w.co.username

    def test_validation_and_authz(self, client, db_session, w):
        url = _url(w.acme, f"memberships/{w.ins.id}/grants/")
        h = _headers(w.po.username)
        assert client.put(url, headers=h, json={"section_grants": {"bogus": "read"}}).status_code == 400
        assert client.put(url, headers=h, json={"section_grants": {"notes": "write"}}).status_code == 400
        assert client.put(url, headers=_headers(w.ins.username),
                          json={"section_grants": {"notes": "contribute"}}).status_code == 403
        # out of scope: the same 404 as a missing customer (404-first)
        assert client.put(url, headers=_headers(w.nobody.username),
                          json={"section_grants": {"notes": "contribute"}}).status_code == 404


# ── global admin guard ─────────────────────────────────────────────────────


class TestLastGlobalAdmin:
    def test_guard_function(self, db_session, w):
        from backend.models.use_case import User
        from backend.services import membership_service as svc

        admin = db_session.query(User).filter(User.is_admin == 1).one()
        assert svc.block_global_admin_change(db_session, admin.id) is True
        assert svc.block_global_admin_change(db_session, w.po.id) is False  # not an admin
        second = _mk_user(db_session, "admin_two", is_admin=1)
        db_session.commit()
        assert svc.block_global_admin_change(db_session, admin.id) is False
        assert svc.block_global_admin_change(db_session, second.id) is False

    def test_route_self_demotion_still_rejected(self, client, db_session, w):
        from backend.models.use_case import User

        admin = db_session.query(User).filter(User.is_admin == 1).one()
        r = client.put(f"/api/auth/users/{admin.id}/", headers=_admin_headers(db_session),
                       json={"role": "user"})
        assert r.status_code == 400
        db_session.expire_all()
        assert db_session.query(User).filter_by(id=admin.id).one().is_admin == 1


# ── ownership review ───────────────────────────────────────────────────────


class TestOwnershipReview:
    def test_queue_and_resolve(self, client, db_session, w):
        from backend.models.use_case import Customer

        c = db_session.query(Customer).filter_by(id=w.other.id).one()
        c.ownership_status = "needs_review"
        db_session.commit()
        h = _admin_headers(db_session)
        r = client.get("/api/admin/ownership-review/", headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["items"] == [{
            "customer_id": w.other.id, "name": "Other Corp", "current_owner": None,
            "current_owner_user_id": None, "placeholder": True,
        }]
        assert client.get("/api/admin/ownership-review/",
                          headers=_headers(w.po.username)).status_code == 403
        r = client.post(f"/api/admin/ownership-review/{w.other.id}/", headers=h,
                        json={"user_id": w.po2.id})
        assert r.status_code == 200, r.text
        db_session.expire_all()
        assert db_session.query(Customer).filter_by(id=w.other.id).one().ownership_status is None
        assert client.get("/api/admin/ownership-review/", headers=h).json()["items"] == []
        rows = _audit(db_session, "ownership.transfer")
        assert len(rows) == 1 and json.loads(rows[0].details)["cleared_needs_review"] is True
        # resolving a non-flagged account is a 409
        assert client.post(f"/api/admin/ownership-review/{w.other.id}/", headers=h,
                           json={"user_id": w.po2.id}).status_code == 409

    def test_customer_dict_exposes_ownership_status(self, db_session, w):
        assert w.acme.to_dict()["ownership_status"] is None


# ── seed helper + sales-team editor sync ───────────────────────────────────


class TestSeedAndSync:
    def test_seed_membership_audited_and_idempotent(self, db_session, w):
        from backend.models.use_case import User
        from backend.services import membership_service as svc

        admin = db_session.query(User).filter(User.is_admin == 1).one()
        out = svc.add_seed_membership(
            db_session, w.other.id, w.po2.id, "primary_owner", source="import",
            details={"file": "accounts_v3.csv", "row": 7}, actor_id=admin.id,
        )
        assert out["source"] == "import"
        again = svc.add_seed_membership(db_session, w.other.id, w.po2.id, "primary_owner")
        assert again["id"] == out["id"]
        rows = _audit(db_session, "seed.membership")
        assert len(rows) == 1 and rows[0].user_id == admin.id
        assert json.loads(rows[0].details)["details"] == {"file": "accounts_v3.csv", "row": 7}

    def test_sales_team_editor_keeps_memberships_in_sync(self, client, db_session, w):
        from backend.models.account_membership import AccountMembership

        r = client.put(_url(w.acme, "sales-team/"), headers=_admin_headers(db_session), json={
            "primary_rep_user_id": w.po2.id, "manager_user_id": None,
            "inside_sales_user_ids": [w.ins.id], "sales_ops_user_ids": [],
        })
        assert r.status_code == 200, r.text
        db_session.expire_all()
        roles = {(m.user_id, m.role) for m in
                 db_session.query(AccountMembership).filter_by(customer_id=w.acme.id)}
        assert (w.po2.id, "primary_owner") in roles
        assert (w.po.id, "co_owner") in roles
        assert (w.ops.id, "sales_ops") not in roles
        assert (w.ins.id, "inside_sales") in roles


# ── migration backfill ─────────────────────────────────────────────────────


def _alembic(db_path, *args):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["SAIL_DATABASE_URL"] = f"sqlite:///{db_path}"
    res = subprocess.run([sys.executable, "-m", "alembic", *args],
                         cwd=ROOT, env=env, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


def _memberships(db_path):
    con = sqlite3.connect(db_path)
    try:
        return sorted(con.execute(
            "SELECT user_id, customer_id, role, source, section_grants FROM account_memberships"
        ).fetchall())
    finally:
        con.close()


def test_migration_backfill_idempotent_and_roundtrip(tmp_path):
    db_path = tmp_path / "rbac.db"
    _alembic(db_path, "upgrade", "a2b3c4d5e6f7")
    con = sqlite3.connect(db_path)
    for i in (1, 2, 3, 4):
        con.execute(
            "INSERT INTO users (id, username, email, hashed_password, role, is_admin, approved, is_active) "
            "VALUES (?, ?, ?, 'x', 'user', 0, 1, 1)", (i, f"u{i}", f"u{i}@t.local"))
    con.execute("INSERT INTO customers (id, name) VALUES (1, 'C1')")
    con.execute("INSERT INTO customers (id, name) VALUES (2, 'C2')")
    con.execute("INSERT INTO customer_users (customer_id, user_id, role) VALUES (1, 1, 'owner')")
    con.execute("INSERT INTO customer_users (customer_id, user_id, role) VALUES (1, 4, 'member')")
    con.execute("INSERT INTO inside_sales_assignments (inside_sales_user_id, customer_id, rep_user_id) "
                "VALUES (2, 1, 1)")
    con.execute("INSERT INTO sales_ops_assignments (user_id, customer_id) VALUES (3, 2)")
    # a user who is both owner and ops on C1 ends up with two legal rows
    con.execute("INSERT INTO sales_ops_assignments (user_id, customer_id) VALUES (1, 1)")
    con.commit()
    con.close()

    _alembic(db_path, "upgrade", "head")
    first = _memberships(db_path)
    assert first == [
        (1, 1, "primary_owner", "migration", None),
        (1, 1, "sales_ops", "migration", None),
        (2, 1, "inside_sales", "migration", None),
        (3, 2, "sales_ops", "migration", None),
    ]

    # re-run the data migration: stamp back, upgrade again -> no new rows
    _alembic(db_path, "stamp", "a2b3c4d5e6f7")
    _alembic(db_path, "upgrade", "head")
    assert _memberships(db_path) == first

    # downgrade drops table + column; upgrade restores; alembic check clean
    _alembic(db_path, "downgrade", "a2b3c4d5e6f7")
    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {r[1] for r in con.execute("PRAGMA table_info(customers)")}
    con.close()
    assert "account_memberships" not in tables and "ownership_status" not in cols
    _alembic(db_path, "upgrade", "head")
    assert _memberships(db_path) == first
    _alembic(db_path, "check")
