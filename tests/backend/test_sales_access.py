"""Sales access resolver (phase 2) — role normalization, scope, and capability
rules from the shift to global customer management.

Pure where possible (role normalization / capability decisions over the user
dict); DB-backed tests only for the hierarchy/inside-sales scope derivation.
The resolver is NOT yet wired into routes (phase 3), so these tests pin the
policy layer's behavior without changing the running app.
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")


from backend.models.sales_access import InsideSalesAssignment, SalesReporting
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import sales_access as sa

# ── role normalization (pure, no DB) ────────────────────────────────────────

def test_role_system_admin_exclusive():
    assert sa.effective_role({"is_admin": 1}) == "system_admin"
    # a sales_manager who is ALSO is_admin=1 is still system_admin (flag wins)
    assert sa.effective_role({"is_admin": 1, "sales_role": "sales_manager"}) == "system_admin"


def test_role_ps_admin_confined():
    assert sa.effective_role({"is_admin": 0, "role": "ps_admin"}) == "ps_admin"


def test_role_sales_role_wins_over_legacy():
    assert sa.effective_role({"is_admin": 0, "role": "user", "sales_role": "sales_manager"}) == "sales_manager"
    assert sa.effective_role({"is_admin": 0, "sales_role": "inside_sales"}) == "inside_sales"
    assert sa.effective_role({"is_admin": 0, "sales_role": "rep"}) == "rep"


def test_role_legacy_auditor_maps():
    assert sa.effective_role({"is_admin": 0, "role": "auditor"}) == "auditor"
    # explicit sales_role=auditor too
    assert sa.effective_role({"is_admin": 0, "role": "user", "sales_role": "auditor"}) == "auditor"


def test_role_plain_user_default():
    assert sa.effective_role({"is_admin": 0, "role": "user"}) == "user"
    assert sa.effective_role({}) == "user"


def test_unrestricted_only_system_admin():
    assert sa.is_unrestricted({"is_admin": 1}) is True
    assert sa.is_unrestricted({"is_admin": 0, "sales_role": "sales_manager"}) is False
    assert sa.is_unrestricted({"is_admin": 0, "sales_role": "rep"}) is False


# ── capability decisions (pure, no DB; customer_id=None => capability-only) ─

def test_system_admin_has_all_capabilities():
    adm = {"is_admin": 1, "user_id": 1}
    for cap in sa.ALL_CAPS:
        assert sa.can(adm, None, cap) is True


def test_ps_admin_has_no_sales_capabilities():
    ps = {"is_admin": 0, "role": "ps_admin", "user_id": 2}
    for cap in (sa.CAP_READ, sa.CAP_EXPORT, sa.CAP_EDIT,
                sa.CAP_MANAGE_TEAM, sa.CAP_TRANSFER_OWNERSHIP, sa.CAP_SYSTEM_ADMIN):
        assert sa.can(ps, None, cap) is False, f"ps_admin must not be elevated to {cap}"


def test_manager_cannot_claim_system_admin():
    mgr = {"is_admin": 0, "sales_role": "sales_manager", "user_id": 3}
    assert sa.can(mgr, None, sa.CAP_SYSTEM_ADMIN) is False


def test_auditor_read_only():
    aud = {"is_admin": 0, "sales_role": "auditor", "user_id": 4,
           "customer_ids": [10], "junction_roles": {10: "auditor"}}
    assert sa.can(aud, None, sa.CAP_READ, customer_id=10) is True
    assert sa.can(aud, None, sa.CAP_EXPORT, customer_id=10) is True
    assert sa.can(aud, None, sa.CAP_EDIT, customer_id=10) is False
    assert sa.can(aud, None, sa.CAP_MANAGE_TEAM, customer_id=10) is False
    assert sa.can(aud, None, sa.CAP_TRANSFER_OWNERSHIP, customer_id=10) is False


def test_rep_in_scope_edit_manage_transfer():
    rep = {"is_admin": 0, "sales_role": "rep", "user_id": 5,
           "customer_ids": [10], "junction_roles": {10: "owner"}}
    assert sa.can(rep, None, sa.CAP_EDIT, customer_id=10) is True
    assert sa.can(rep, None, sa.CAP_MANAGE_TEAM, customer_id=10) is True
    assert sa.can(rep, None, sa.CAP_TRANSFER_OWNERSHIP, customer_id=10) is True


def test_inside_sales_edit_but_no_team():
    ins = {"is_admin": 0, "sales_role": "inside_sales", "user_id": 6,
           "customer_ids": [10], "junction_roles": {10: "member"}}
    assert sa.can(ins, None, sa.CAP_EDIT, customer_id=10) is True
    assert sa.can(ins, None, sa.CAP_MANAGE_TEAM, customer_id=10) is False
    assert sa.can(ins, None, sa.CAP_TRANSFER_OWNERSHIP, customer_id=10) is False


def test_out_of_scope_denied():
    # rep whose junction is only on customer 10 must not edit customer 99
    rep = {"is_admin": 0, "sales_role": "rep", "user_id": 5,
           "customer_ids": [10], "junction_roles": {10: "owner"}}
    assert sa.can(rep, None, sa.CAP_EDIT, customer_id=99) is False


# ── DB-backed scope derivation (hierarchy + inside-sales) ───────────────────

def test_manager_scope_includes_report_owned_customers(db_session):
    mgr = User(username="mgr", email="m@t.local", is_admin=0, approved=1, is_active=1, sales_role="sales_manager")
    rep = User(username="rep", email="r@t.local", is_admin=0, approved=1, is_active=1, sales_role="rep")
    other = User(username="other_mgr_rep", email="o@t.local", is_admin=0, approved=1, is_active=1, sales_role="rep")
    db_session.add_all([mgr, rep, other])
    db_session.flush()

    owned_by_rep = Customer(name="Rep Owned Co")
    owned_by_other = Customer(name="Other Rep Co")
    db_session.add_all([owned_by_rep, owned_by_other])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=owned_by_rep.id, user_id=rep.id, role="owner", granted_by=rep.id))
    db_session.add(CustomerUser(customer_id=owned_by_other.id, user_id=other.id, role="owner", granted_by=other.id))
    db_session.add(SalesReporting(rep_user_id=rep.id, manager_user_id=mgr.id))
    db_session.commit()

    mgr_dict = {"is_admin": 0, "sales_role": "sales_manager", "user_id": mgr.id,
                "customer_ids": [], "junction_roles": {}}
    scope = sa.customer_scope(mgr_dict, db_session)
    assert owned_by_rep.id in scope
    assert owned_by_other.id not in scope


def test_transitive_manager_scope_and_cycle_safety(db_session):
    m1 = User(username="m1", email="m1@t.local", is_admin=0, approved=1, is_active=1, sales_role="sales_manager")
    m2 = User(username="m2", email="m2@t.local", is_admin=0, approved=1, is_active=1, sales_role="sales_manager")
    rep = User(username="rep2", email="rep2@t.local", is_admin=0, approved=1, is_active=1, sales_role="rep")
    db_session.add_all([m1, m2, rep])
    db_session.flush()
    co = Customer(name="Transitive Owned Co")
    db_session.add(co)
    db_session.flush()
    db_session.add(CustomerUser(customer_id=co.id, user_id=rep.id, role="owner", granted_by=rep.id))
    # rep -> m2 -> m1 (two levels)
    db_session.add(SalesReporting(rep_user_id=rep.id, manager_user_id=m2.id))
    db_session.add(SalesReporting(rep_user_id=m2.id, manager_user_id=m1.id))
    db_session.commit()

    m1_dict = {"is_admin": 0, "sales_role": "sales_manager", "user_id": m1.id, "customer_ids": [], "junction_roles": {}}
    scope = sa.customer_scope(m1_dict, db_session)
    assert co.id in scope, "transitive manager scope must reach the report's owned customer"

    # cycle-safety: add m1 -> m2 (self-closing cycle) and ensure no infinite loop
    db_session.add(SalesReporting(rep_user_id=m1.id, manager_user_id=m2.id))
    db_session.commit()
    reports = sa._transitive_report_ids(db_session, m1.id)
    assert rep.id in reports
    assert m1.id not in reports  # own id excluded


def test_inside_sales_scope_is_customer_specific(db_session):
    ins = User(username="ins", email="i@t.local", is_admin=0, approved=1, is_active=1, sales_role="inside_sales")
    db_session.add(ins)
    db_session.flush()
    a = Customer(name="ISA Co")
    b = Customer(name="ISB Co")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.add(InsideSalesAssignment(inside_sales_user_id=ins.id, customer_id=a.id))
    db_session.commit()

    ins_dict = {"is_admin": 0, "sales_role": "inside_sales", "user_id": ins.id, "customer_ids": [], "junction_roles": {}}
    scope = sa.customer_scope(ins_dict, db_session)
    assert a.id in scope
    assert b.id not in scope


def test_empty_scope_means_no_data(db_session):
    # a rep with no junctions / no assignments / no reports -> empty scope
    lonely = {"is_admin": 0, "sales_role": "rep", "user_id": 999999, "customer_ids": [], "junction_roles": {}}
    assert sa.customer_scope(lonely, db_session) == set()
