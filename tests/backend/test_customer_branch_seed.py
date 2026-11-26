"""Customer branch field + branches reference endpoint + real-customer CSV seed.

Covers the prod-seed schema work (migration f0a1b2c3d4e5):
  * ``customers.branch`` column + ``branch`` on CustomerCreate/Update/Response
  * ``GET /api/customers/branches/`` (the selectable reference list, mirrors
    /verticals/)
  * ``users.email`` nullable — a name-only pending owner (NULL email) inserts
  * ``seed_customers_from_csv`` — customers + branches + name-only pending
    owners + ``seed_customer_<slug>`` placeholder owners for rep-null rows,
    and idempotency (re-run creates no duplicates).

Deterministic TestClient tests against the shared temp DB (no LLM). Follows the
test_customer_vertical.py auth pattern: conftest ``client`` + ``db_session``
fixtures with a local autouse ``_auth_user_lookup`` that keeps the JWT +
junction lookups on the shared test engine.
"""

import csv
import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest
from backend.models.sales_access import (
    InsideSalesAssignment,
    SalesOpsAssignment,
    SalesReporting,
)
from backend.models.use_case import Branch, Customer, CustomerUser, User
from backend.seed import _slugify, is_excluded_seed_customer, seed_customers_from_csv

from tests.backend.common import _token

_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"
@pytest.fixture(autouse=True)
def _auth_user_lookup(db_session):
    from unittest.mock import patch

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
def admin(db_session):
    u = User(
        username="branch_admin", email="branch_admin@test.local",
        hashed_password=_FAKE_BCRYPT_HASH, display_name="Admin",
        department="IT", is_admin=1, approved=1, is_active=1,
    )
    db_session.add(u)
    db_session.commit()
    return u


# ── customers.branch column + API surface ────────────────────────────────────

def test_customer_response_includes_branch(client, db_session, admin):
    c = Customer(name="BranchCo", description=None, vertical=None, branch="BR20 - Sample Branch E")
    db_session.add(c)
    db_session.commit()
    db_session.add(CustomerUser(customer_id=c.id, user_id=admin.id, role="owner", granted_by=admin.id))
    db_session.commit()
    r = client.get("/api/customers/BranchCo/", headers=_token("branch_admin", True))
    assert r.status_code == 200
    assert r.json()["branch"] == "BR20 - Sample Branch E"


def test_create_customer_with_branch(client, db_session, admin):
    r = client.post("/api/customers/", json={
        "name": "NewBranchCo", "description": "d", "vertical": None,
        "branch": "BR50 - Sample Branch D",
    }, headers=_token("branch_admin", True))
    assert r.status_code == 201, r.text
    assert r.json()["branch"] == "BR50 - Sample Branch D"


def test_branches_endpoint_lists_reference(client, db_session, admin):
    # Seed the reference table with two branches.
    for b in ("BR10 - Sample Branch G", "BR37 – Example Customer J"):
        db_session.add(Branch(name=b))
    db_session.commit()

    r = client.get("/api/customers/branches/", headers=_token("branch_admin", True))
    assert r.status_code == 200
    body = r.json()
    assert body["branches"] == ["BR10 - Sample Branch G", "BR37 – Example Customer J"]
    assert [i["name"] for i in body["items"]] == body["branches"]


def test_branches_endpoint_requires_auth(client):
    r = client.get("/api/customers/branches/")
    assert r.status_code == 401


# ── users.email nullable (name-only pending owner) ───────────────────────────

def test_pending_owner_inserts_with_null_email(db_session):
    u = User(
        username="pending-owner", email=None, display_name="Pending Owner",
        department=None, role="user", is_admin=0, approved=0, is_active=0,
        auth_provider="local",
    )
    db_session.add(u)
    db_session.commit()  # must NOT raise a NOT NULL constraint error
    assert u.id is not None
    # Many NULL-email rows coexist legally (SQLite UNIQUE treats NULLs distinct).
    u2 = User(username="pending-owner-2", email=None, display_name="Pending Owner 2",
              is_admin=0, approved=0, is_active=0)
    db_session.add(u2)
    db_session.commit()
    assert u2.id is not None


# ── seed_customers_from_csv ──────────────────────────────────────────────────

def _write_csv(tmp_path, rows):
    p = tmp_path / "customers_seed.csv"
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["customer_name", "rep_name", "branch"])
        for r in rows:
            w.writerow(r)
    return str(p)


def test_seed_customers_from_csv_creates_customers_owners_branches(db_session, tmp_path):
    path = _write_csv(tmp_path, [
        ["Acme Real Co", "Jane Rep", "BR20 - Sample Branch E"],
        ["No Rep Co", "", "BR50 - Sample Branch D"],
        ["Same Rep Co", "Jane Rep", "BR50 - Sample Branch D"],  # reuses Jane's user
        ["Empty Rep Co", "   ", "BR10 - Sample Branch G"],      # whitespace rep -> placeholder
    ])
    summary = seed_customers_from_csv(db_session, path)

    # Customers: all 4 created, with branch set.
    acme = db_session.query(Customer).filter_by(name="Acme Real Co").first()
    assert acme.branch == "BR20 - Sample Branch E"
    assert summary["customers_created"] == 4
    assert summary["customers"] == 4

    # Branches: 3 distinct (BR20, BR50, BR10), not 4.
    branch_names = sorted(b.name for b in db_session.query(Branch).all())
    assert branch_names == ["BR10 - Sample Branch G", "BR20 - Sample Branch E", "BR50 - Sample Branch D"]
    assert summary["branches_created"] == 3

    # Owners: "Jane Rep" user created once, reused by Acme + Same Rep Co.
    jane = db_session.query(User).filter(User.username == _slugify("Jane Rep")).first()
    assert jane is not None
    assert jane.display_name == "Jane Rep"
    assert jane.email is None and jane.is_active == 0 and jane.approved == 0

    # Placeholder owners for the 2 rep-null customers.
    ph_no_rep = db_session.query(User).filter(User.username == f"seed_customer_{_slugify('No Rep Co')}").first()
    assert ph_no_rep is not None and ph_no_rep.display_name == "No Rep Co"
    ph_empty = db_session.query(User).filter(User.username == f"seed_customer_{_slugify('Empty Rep Co')}").first()
    assert ph_empty is not None
    # Department seeding rule (0.2.10): named rep owners are primary (outside)
    # reps -> "Sales"; placeholder owners (no rep name) stay department-less
    # for the operator to assign.
    assert jane.department == "Sales"
    assert ph_no_rep.department is None
    assert ph_empty.department is None
    # 1 real rep + 2 placeholders = 3 owner users created.
    assert summary["owners_created"] == 3

    # Owner junctions: every customer has exactly one owner.
    assert summary["junctions_created"] == 4
    assert db_session.query(CustomerUser).filter(CustomerUser.role == "owner").count() == 4
    # Acme's owner is Jane; No Rep Co's owner is its placeholder.
    acme_owner = db_session.query(CustomerUser).filter(
        CustomerUser.customer_id == acme.id, CustomerUser.user_id == jane.id).first()
    assert acme_owner is not None and acme_owner.role == "owner"
    no_rep = db_session.query(Customer).filter_by(name="No Rep Co").first()
    assert db_session.query(CustomerUser).filter(
        CustomerUser.customer_id == no_rep.id, CustomerUser.user_id == ph_no_rep.id).first() is not None


def test_seed_customers_from_csv_idempotent(db_session, tmp_path):
    path = _write_csv(tmp_path, [
        ["Idempotent Co", "Kai Rep", "BR20 - Sample Branch E"],
        ["Null Rep Co", "", "BR30 - Sample Branch P"],
    ])
    first = seed_customers_from_csv(db_session, path)
    # Capture totals AFTER the first run (shared temp DB may hold prior data).
    cust_after_1 = db_session.query(Customer).count()
    branch_after_1 = db_session.query(Branch).count()
    user_after_1 = db_session.query(User).count()
    junction_after_1 = db_session.query(CustomerUser).count()

    second = seed_customers_from_csv(db_session, path)

    assert first["customers_created"] == 2 and second["customers_created"] == 0
    assert first["owners_created"] == 2 and second["owners_created"] == 0
    assert first["junctions_created"] == 2 and second["junctions_created"] == 0
    assert first["branches_created"] == 2 and second["branches_created"] == 0
    # Totals unchanged after the re-run (idempotent — no duplicates).
    assert db_session.query(Customer).count() == cust_after_1
    assert db_session.query(Branch).count() == branch_after_1
    assert db_session.query(User).count() == user_after_1
    assert db_session.query(CustomerUser).count() == junction_after_1
    # The two seeded customers + both owner users are present exactly once.
    assert db_session.query(Customer).filter_by(name="Idempotent Co").count() == 1
    assert db_session.query(Customer).filter_by(name="Null Rep Co").count() == 1
    assert db_session.query(User).filter(User.username == _slugify("Kai Rep")).count() == 1
    assert db_session.query(User).filter(
        User.username == f"seed_customer_{_slugify('Null Rep Co')}").count() == 1


def test_slugify_deterministic_and_safe():
    assert _slugify("Jane Rep") == "jane-rep"
    assert _slugify("Example Customer Q") == "example-customer-q"
    assert _slugify("1010 - Sample Branch R") == "1010-sample-branch-r"
    # unicode-safe
    assert _slugify("Über Café") == "uber-cafe"
    # non-empty fallback
    assert _slugify("!!!") == "unnamed"
    # length cap
    assert len(_slugify("a" * 500)) <= 100


# ── nullable email must not 500 the admin user-list / approve endpoints ────
# Regression: the prod-seed creates 158 pending owners with email=NULL
# (users.email nullable since migration f0a1b2c3d4e5). UserResponse.email
# and LoginResponse.email were `str` — serializing a NULL email raised and
# turned GET /api/auth/users/pending/ + /users/all/ + POST /approve/ into 500s
# the moment the first name-only owner existed.

def test_user_list_endpoints_handle_null_email(client, db_session, admin):
    pending = User(
        username="pending-no-email", email=None, display_name="Pending No Email",
        hashed_password=_FAKE_BCRYPT_HASH, role="user", is_admin=0,
        approved=0, is_active=1,
    )
    db_session.add(pending)
    db_session.commit()

    r = client.get("/api/auth/users/all/", headers=_token("branch_admin", True))
    assert r.status_code == 200, f"users/all 500'd on a NULL-email user: {r.status_code} {r.text[:200]}"
    row = next(u for u in r.json() if u["username"] == "pending-no-email")
    assert row["email"] is None

    r = client.get("/api/auth/users/pending/", headers=_token("branch_admin", True))
    assert r.status_code == 200, f"users/pending 500'd: {r.status_code} {r.text[:200]}"
    assert any(u["username"] == "pending-no-email" and u["email"] is None for u in r.json())

    # Approving a name-only owner also serializes UserResponse (email NULL).
    r = client.post("/api/auth/approve/pending-no-email/", headers=_token("branch_admin", True))
    assert r.status_code == 200, f"approve 500'd: {r.status_code} {r.text[:200]}"
    assert r.json()["email"] is None
    assert r.json()["approved"] == 1



# ── seed-scope exclusion (rebate / marketing-funds accounts) ────────────────

@pytest.mark.parametrize("name", [
    "Example Customer K - REBATES ONLY",
    "Nvidia (Vendor Rebates Only)",
    "Red Hat - MARKETING FUNDS ONLY",
    "Arrow ECS Marketing Funds",
    "SUSE LLC - Marketing funds",
])
def test_is_excluded_seed_customer_matches_out_of_scope_names(name):
    assert is_excluded_seed_customer(name)


@pytest.mark.parametrize("name", [
    "Example Customer K",           # real customer of the same vendor
    "Red Hat",
    "Arrow ECS",
    "Acme Marketing Group",    # "marketing" alone is NOT the out-of-scope marker
    "REBATES (general)",
])
def test_is_excluded_seed_customer_keeps_real_customers(name):
    assert not is_excluded_seed_customer(name)


def test_seed_customers_from_csv_skips_excluded_rows(db_session, tmp_path):
    """Backstop: even if out-of-scope rows resurface in a CSV, the seeder
    must not create customers/owners/branches/junctions for them."""
    path = _write_csv(tmp_path, [
        ["Acme Tracked Co", "Jane Rep", "BR50 - Sample Branch D"],
        ["Acme Tracked Co - REBATES ONLY", "Jane Rep", "BR50 - Sample Branch D"],
        ["Beta Marketing Funds", "", "BR10 - Sample Branch G"],
    ])
    summary = seed_customers_from_csv(db_session, path)

    assert summary["customers_created"] == 1
    assert summary["customers"] == 1
    tracked = db_session.query(Customer).filter_by(name="Acme Tracked Co").first()
    assert tracked is not None and tracked.branch == "BR50 - Sample Branch D"
    for absent in ("Acme Tracked Co - REBATES ONLY", "Beta Marketing Funds"):
        assert db_session.query(Customer).filter_by(name=absent).first() is None


# ── H2: batched sales context on the LIST payload ───────────────────────────


def _mk_user(db, username, *, sales_role=None, display_name=None):
    u = User(
        username=username, email=f"{username}@test.local",
        hashed_password=_FAKE_BCRYPT_HASH,
        display_name=display_name or username,
        department="Sales", is_admin=0, approved=1, is_active=1,
        sales_role=sales_role,
    )
    db.add(u)
    return u


def test_list_payload_carries_batched_sales_context(client, db_session, admin):
    """H2: the LIST route carries the SAME sales context as the detail route
    (owner filter/sort run off the authorized payload — no per-account
    lookups in the UI)."""
    rep = _mk_user(db_session, "ctx_rep", sales_role="rep", display_name="Rep One")
    mgr = _mk_user(db_session, "ctx_mgr", sales_role="sales_manager", display_name="Mgr One")
    mgr2 = _mk_user(db_session, "ctx_mgr2", sales_role="sales_manager")
    inside = _mk_user(db_session, "ctx_inside")
    ops = _mk_user(db_session, "ctx_ops")
    db_session.flush()
    c1 = Customer(name="CtxCo One")
    c2 = Customer(name="CtxCo Two")   # non-rep owner registered first, rep after
    c3 = Customer(name="CtxCo Three")  # no owner; inside + ops assignments
    db_session.add_all([c1, c2, c3])
    db_session.flush()
    db_session.add_all([
        CustomerUser(customer_id=c1.id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=c2.id, user_id=mgr2.id, role="owner"),
        CustomerUser(customer_id=c2.id, user_id=rep.id, role="owner"),
        SalesReporting(rep_user_id=rep.id, manager_user_id=mgr.id),
        InsideSalesAssignment(customer_id=c3.id, inside_sales_user_id=inside.id),
        SalesOpsAssignment(customer_id=c3.id, user_id=ops.id),
    ])
    db_session.commit()
    headers = _token("branch_admin", True)
    listing = client.get("/api/customers/", headers=headers)
    assert listing.status_code == 200
    by_name = {row["name"]: row for row in listing.json()}
    # c1: rep owner + reporting row
    assert by_name["CtxCo One"]["primary_rep"] == "Rep One"
    assert by_name["CtxCo One"]["manager_name"] == "Mgr One"
    # c2: exactly-one-rep rule beats the earlier-registered non-rep owner
    assert by_name["CtxCo Two"]["primary_rep"] == "Rep One"
    # c3: no owner → null rep; inside/ops carried through
    assert by_name["CtxCo Three"]["primary_rep"] is None
    assert by_name["CtxCo Three"]["inside_sales"] == [{"name": "ctx_inside"}]
    assert by_name["CtxCo Three"]["sales_ops"] == [{"name": "ctx_ops"}]
    # Cross-surface: the detail route (per-customer path) agrees for every row.
    for name in ("CtxCo One", "CtxCo Two", "CtxCo Three"):
        detail = client.get(f"/api/customers/{name}/", headers=headers)
        assert detail.status_code == 200
        for field in ("primary_rep", "rep_sales_role", "manager_name",
                      "inside_sales", "sales_ops"):
            assert by_name[name][field] == detail.json()[field], field


def test_list_sales_context_is_fixed_batch_queries(client, db_session, admin):
    """H2 scale pin: the list route resolves the sales context in exactly
    FOUR batch statements (owners / managers / inside / ops) regardless of
    list size — never one lookup per account."""
    from sqlalchemy import event

    rep = _mk_user(db_session, "batch_rep", sales_role="rep")
    db_session.flush()
    customers = [Customer(name=f"BatchCo {i}") for i in range(3)]
    db_session.add_all(customers)
    db_session.flush()
    for c in customers:
        db_session.add(CustomerUser(customer_id=c.id, user_id=rep.id, role="owner"))
    db_session.commit()
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db_session.get_bind().engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        r = client.get("/api/customers/", headers=_token("branch_admin", True))
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert r.status_code == 200
    families = {
        "customer_users": 0,
        "sales_reporting": 0,
        "inside_sales_assignments": 0,
        "sales_ops_assignments": 0,
    }
    for s in statements:
        for family in families:
            if family not in s:
                continue
            if " IN " in s:
                families[family] += 1
            elif family == "customer_users" and "customer_users.user_id = " in s:
                continue  # the auth path's per-USER junction lookup (not per-customer)
            else:
                raise AssertionError(
                    f"per-customer sales-structure lookup leaked into the list route: {s}"
                )
    assert families == {
        "customer_users": 1, "sales_reporting": 1,
        "inside_sales_assignments": 1, "sales_ops_assignments": 1,
    }, statements
