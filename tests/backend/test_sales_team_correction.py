"""Sales Ops role + per-customer sales-team correction surface (0.2.10)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from backend.services import sales_access
from sqlalchemy import create_engine, inspect

ROOT = Path(__file__).resolve().parents[2]


def _headers(username: str) -> dict:
    from backend.auth import create_access_token

    return {"Authorization": f"Bearer {create_access_token({'sub': username, 'is_admin': False})}"}


def _admin_headers(db) -> dict:
    from backend.auth import create_access_token
    from backend.models.use_case import User

    admin = db.query(User).filter(User.is_admin == 1).first()
    return {"Authorization": f"Bearer {create_access_token({'sub': admin.username, 'is_admin': True})}"}


def _mk_user(db, username, sales_role=None):
    from backend.models.use_case import User

    u = User(
        username=username, email=f"{username}@test.local",
        hashed_password="unused", display_name=username.title(),
        department="Sales", is_admin=0, approved=1, is_active=1, sales_role=sales_role,
    )
    db.add(u)
    db.flush()
    return u


def _user_dict(db, user) -> dict:
    from backend.models.use_case import CustomerUser

    rows = db.query(CustomerUser).filter(CustomerUser.user_id == user.id).all()
    return {
        "username": user.username, "user_id": user.id, "is_admin": 0,
        "role": None, "sales_role": user.sales_role,
        "customer_ids": [r.customer_id for r in rows],
        "junction_roles": {r.customer_id: r.role for r in rows},
    }


@pytest.fixture()
def team(db_session):
    from backend.models.sales_access import (
        InsideSalesAssignment,
        SalesOpsAssignment,
        SalesReporting,
    )
    from backend.models.use_case import Customer, CustomerUser

    w = type("W", (), {})()
    w.acme = Customer(name="Acme Corp")
    w.other = Customer(name="Other Corp")
    db_session.add_all([w.acme, w.other])
    db_session.flush()
    w.rep = _mk_user(db_session, "rep_one", "rep")
    w.rep2 = _mk_user(db_session, "rep_two", "rep")
    w.mgr = _mk_user(db_session, "mgr_one", "sales_manager")
    w.mgr2 = _mk_user(db_session, "mgr_two", "sales_manager")
    w.inside = _mk_user(db_session, "inside_one", "inside_sales")
    w.inside2 = _mk_user(db_session, "inside_two", "inside_sales")
    w.ops = _mk_user(db_session, "ops_one", "sales_ops")
    w.ops2 = _mk_user(db_session, "ops_two", "sales_ops")
    w.aud = _mk_user(db_session, "aud_one", "auditor")
    w.member = _mk_user(db_session, "member_one")
    db_session.add_all([
        CustomerUser(customer_id=w.acme.id, user_id=w.rep.id, role="owner"),
        CustomerUser(customer_id=w.other.id, user_id=w.rep2.id, role="owner"),
        CustomerUser(customer_id=w.acme.id, user_id=w.aud.id, role="auditor"),
        CustomerUser(customer_id=w.acme.id, user_id=w.member.id, role="member"),
        SalesReporting(rep_user_id=w.rep.id, manager_user_id=w.mgr.id),
        SalesReporting(rep_user_id=w.rep2.id, manager_user_id=w.mgr.id),
        InsideSalesAssignment(inside_sales_user_id=w.inside.id, customer_id=w.acme.id, rep_user_id=w.rep.id),
        SalesOpsAssignment(user_id=w.ops.id, customer_id=w.acme.id),
    ])
    db_session.commit()
    return w


# ── resolver ────────────────────────────────────────────────────────────────


class TestResolver:
    def test_sales_ops_capabilities(self, db_session, team):
        u = _user_dict(db_session, team.ops)
        assert sales_access.effective_role(u) == "sales_ops"
        cid = team.acme.id
        for cap in (sales_access.CAP_READ, sales_access.CAP_EXPORT,
                    sales_access.CAP_NOTES, sales_access.CAP_KNOWLEDGE):
            assert sales_access.can(u, db_session, cap, cid), cap
        for cap in (sales_access.CAP_EDIT, sales_access.CAP_MANAGE_TEAM,
                    sales_access.CAP_TRANSFER_OWNERSHIP):
            assert not sales_access.can(u, db_session, cap, cid), cap

    def test_sales_ops_scope_only_assigned(self, db_session, team):
        u = _user_dict(db_session, team.ops)
        assert sales_access.customer_scope(u, db_session) == {team.acme.id}
        assert not sales_access.can(u, db_session, sales_access.CAP_READ, team.other.id)
        assert not sales_access.can(u, db_session, sales_access.CAP_NOTES, team.other.id)

    def test_unassigned_sales_ops_has_nothing(self, db_session, team):
        u = _user_dict(db_session, team.ops2)
        assert sales_access.customer_scope(u, db_session) == set()
        assert not sales_access.can(u, db_session, sales_access.CAP_READ, team.acme.id)

    def test_auditor_stays_read_only(self, db_session, team):
        u = _user_dict(db_session, team.aud)
        cid = team.acme.id
        assert sales_access.can(u, db_session, sales_access.CAP_READ, cid)
        assert not sales_access.can(u, db_session, sales_access.CAP_NOTES, cid)
        assert not sales_access.can(u, db_session, sales_access.CAP_KNOWLEDGE, cid)

    def test_member_and_owner_keep_notes_and_knowledge(self, db_session, team):
        for who in (team.member, team.rep):
            u = _user_dict(db_session, who)
            assert sales_access.can(u, db_session, sales_access.CAP_NOTES, team.acme.id)
            assert sales_access.can(u, db_session, sales_access.CAP_KNOWLEDGE, team.acme.id)
        owner = _user_dict(db_session, team.rep)
        assert sales_access.can(owner, db_session, sales_access.CAP_EDIT, team.acme.id)

    def test_sales_ops_read_scope_includes_assigned(self, db_session, team):
        """A sales_ops user with an assignment (and NO junction row) is read-
        scoped to that account. Regression for the primary read-scope fix:
        check_customer_access / get_accessible_customers route through the
        resolver's central customer_scope (junction + sales_ops assignments
        + memberships + team scope)."""
        from backend.services.customers_service import (
            check_customer_access,
            get_accessible_customers,
        )
        ops = _user_dict(db_session, team.ops)
        assert ops["customer_ids"] == []  # no junction row
        assert check_customer_access(db_session, team.acme, ops) is True
        assert check_customer_access(db_session, team.other, ops) is False
        names = {c.name for c in get_accessible_customers(db_session, ops)}
        assert names == {team.acme.name}


# ── sales-team endpoints ───────────────────────────────────────────────────


def _url(team):
    return f"/api/customers/{team.acme.name.replace(' ', '%20')}/sales-team/"


class TestSalesTeamEndpoints:
    def test_get_reflects_seeded_state(self, client, db_session, team):
        r = client.get(_url(team), headers=_admin_headers(db_session))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["customer_id"] == team.acme.id
        assert body["primary_rep"] == {
            "user_id": team.rep.id, "name": "Rep_One", "sales_role": "rep",
        }
        assert body["manager"] == {
            "user_id": team.mgr.id, "name": "Mgr_One",
            "auto_linked": False, "link_reason": None,
        }
        assert body["inside_sales"] == [{
            "user_id": team.inside.id, "name": "Inside_One",
            "auto_linked": False, "link_reason": None,
        }]
        assert body["sales_ops"] == [{
            "user_id": team.ops.id, "name": "Ops_One",
            "auto_linked": False, "link_reason": None,
        }]

    def test_put_changes_everything(self, client, db_session, team):
        from backend.models.collaboration import AuditLog
        from backend.models.sales_access import SalesReporting
        from backend.models.use_case import CustomerUser

        h = _admin_headers(db_session)
        payload = {
            "primary_rep_user_id": team.rep2.id,
            "manager_user_id": team.mgr2.id,
            "inside_sales_user_ids": [team.inside2.id],
            "sales_ops_user_ids": [team.ops.id, team.ops2.id],
        }
        r = client.put(_url(team), headers=h, json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["primary_rep"]["user_id"] == team.rep2.id
        assert body["manager"]["user_id"] == team.mgr2.id
        assert [u["user_id"] for u in body["inside_sales"]] == [team.inside2.id]
        assert [u["user_id"] for u in body["sales_ops"]] == [team.ops.id, team.ops2.id]

        db_session.expire_all()
        roles = {
            cu.user_id: cu.role
            for cu in db_session.query(CustomerUser).filter_by(customer_id=team.acme.id)
        }
        assert roles[team.rep2.id] == "owner"
        assert roles[team.rep.id] == "member"  # demoted, access kept
        assert db_session.query(SalesReporting).filter_by(rep_user_id=team.rep2.id).one().manager_user_id == team.mgr2.id
        # other reps' reporting rows untouched
        assert db_session.query(SalesReporting).filter_by(rep_user_id=team.rep.id).one().manager_user_id == team.mgr.id

        actions = {
            a.action for a in db_session.query(AuditLog).filter_by(customer_id=team.acme.id)
        }
        assert {"set_primary_rep", "set_manager", "set_inside_sales", "set_sales_ops"} <= actions

        again = client.get(_url(team), headers=h).json()
        assert again == body

    def test_clear_manager(self, client, db_session, team):
        h = _admin_headers(db_session)
        r = client.put(_url(team), headers=h, json={
            "primary_rep_user_id": team.rep.id, "manager_user_id": None,
            "inside_sales_user_ids": [], "sales_ops_user_ids": [],
        })
        assert r.status_code == 200, r.text
        assert r.json()["manager"] is None
        assert r.json()["inside_sales"] == []
        assert r.json()["sales_ops"] == []

    def test_clear_primary_rep_400(self, client, db_session, team):
        r = client.put(_url(team), headers=_admin_headers(db_session), json={
            "primary_rep_user_id": None, "manager_user_id": None,
            "inside_sales_user_ids": [], "sales_ops_user_ids": [],
        })
        assert r.status_code == 400
        assert "cannot clear primary rep" in r.json()["detail"]

    def test_unknown_user_404(self, client, db_session, team):
        r = client.put(_url(team), headers=_admin_headers(db_session), json={
            "primary_rep_user_id": team.rep.id, "manager_user_id": None,
            "inside_sales_user_ids": [999999], "sales_ops_user_ids": [],
        })
        assert r.status_code == 404

    def test_unknown_customer_404(self, client, db_session, team):
        r = client.get("/api/customers/Nope/sales-team/", headers=_admin_headers(db_session))
        assert r.status_code == 404

    def test_non_admin_403(self, client, db_session, team):
        for who in (team.rep, team.mgr, team.ops):
            assert client.get(_url(team), headers=_headers(who.username)).status_code == 403
            r = client.put(_url(team), headers=_headers(who.username), json={
                "primary_rep_user_id": team.rep.id, "manager_user_id": None,
                "inside_sales_user_ids": [], "sales_ops_user_ids": [],
            })
            assert r.status_code == 403

    def test_unauthenticated_401(self, client, team):
        assert client.get(_url(team)).status_code == 401

    def test_detail_panel_includes_sales_ops_list_omits(self, client, db_session, team):
        h = _admin_headers(db_session)
        detail = client.get(f"/api/customers/{team.acme.name.replace(' ', '%20')}/", headers=h)
        assert detail.status_code == 200, detail.text
        assert detail.json()["sales_ops"] == [{"name": "Ops_One"}]


# ── write gates ────────────────────────────────────────────────────────────


class TestWriteGates:
    def test_sales_ops_can_post_note_auditor_cannot(self, client, db_session, team):
        body = {"category": "discovery", "title": "t", "content": "c"}
        url = f"/api/customers/{team.acme.id}/sales-notes/"
        r = client.post(url, headers=_headers(team.ops.username), json=body)
        assert r.status_code == 201, r.text
        assert client.post(url, headers=_headers(team.aud.username), json=body).status_code == 403
        # unassigned sales_ops is outside scope -> the same 404 as a missing
        # customer
        assert client.post(url, headers=_headers(team.ops2.username), json=body).status_code == 404
        # sales_ops may read the account's notes
        assert client.get(url, headers=_headers(team.ops.username)).status_code == 200

    def test_sales_ops_knowledge_upload_auditor_denied(self, client, db_session, team):
        csv_bytes = b"a,b\n1,2\n"

        def upload(who):
            return client.post(
                "/api/customer-knowledge/",
                files={"file": ("t.csv", csv_bytes, "text/csv")},
                data={"customer_id": str(team.acme.id)},
                headers=_headers(who.username),
            )

        assert upload(team.aud).status_code == 403
        r = upload(team.ops)
        assert r.status_code in (200, 201), r.text

    def test_sales_ops_cannot_edit_account(self, client, db_session, team):
        r = client.put(
            f"/api/customers/{team.acme.name.replace(' ', '%20')}/",
            headers=_headers(team.ops.username), json={"description": "x"},
        )
        assert r.status_code in (403, 404)


# ── migration ──────────────────────────────────────────────────────────────


def _alembic(db_path, *args):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["SAIL_DATABASE_URL"] = f"sqlite:///{db_path}"
    res = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_migration_upgrade_downgrade_roundtrip(tmp_path):
    db_path = tmp_path / "mig.db"
    url = f"sqlite:///{db_path}"

    def has_table():
        eng = create_engine(url)
        try:
            return inspect(eng).has_table("sales_ops_assignments")
        finally:
            eng.dispose()

    _alembic(db_path, "upgrade", "head")
    assert has_table()
    # step back to the revision before sales_ops_assignments (stable anchor,
    # independent of later migrations stacked on head)
    _alembic(db_path, "downgrade", "f1b2c3d4e5f6")
    assert not has_table()
    _alembic(db_path, "upgrade", "head")
    assert has_table()
