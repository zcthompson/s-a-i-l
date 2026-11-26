"""CRM prerequisites — reserved-section capabilities + creator membership parity.

CRM prerequisites:

* ``CAP_OPPORTUNITIES`` / ``CAP_FORECASTS`` / ``CAP_COMPETITORS`` activate the
  already-reserved section vocabulary (``models/account_membership.py``
  ACCOUNT_SECTIONS) with the matrix shape: owner-level writes; inside-sales
  gated on a ``contribute`` grant for the MATCHING section (a grant for
  another section never confers it); legacy junction-member parity; auditor /
  sales_admin / ps_admin denied.
* ``create_customer`` now writes BOTH the legacy ``CustomerUser`` owner row
  and the ``primary_owner`` membership row in one transaction (the 2026-10-15
  gap), audited as ``membership.add`` with reason ``customer.create``.
* The backfill is idempotent, dry-run by default, and refuses conflicts
  (an account that already has a different primary owner is reported, never
  touched).

Deterministic TestClient + service tests against the shared temp DB (no LLM).
Follows the test_customer_branch_seed.py auth pattern.
"""

import json
import os
import sqlite3

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import pytest
from backend.models.account_membership import AccountMembership
from backend.models.collaboration import AuditLog
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import membership_service, sales_access

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
        username="e0_admin", email="e0_admin@test.local",
        hashed_password=_FAKE_BCRYPT_HASH, display_name="E0 Admin",
        department="IT", is_admin=1, approved=1, is_active=1,
    )
    db_session.add(u)
    db_session.commit()
    return u


# ── capability matrix pins (the shape, applied to the reserved sections) ─


CRM_CAPS = (
    (sales_access.CAP_OPPORTUNITIES, "opportunities"),
    (sales_access.CAP_FORECASTS, "forecasts"),
    (sales_access.CAP_COMPETITORS, "competitors"),
)


def test_new_caps_are_part_of_the_resolver_vocabulary():
    for cap, section in CRM_CAPS:
        assert cap in sales_access.ALL_CAPS
        assert cap == section  # the reserved section names are the capability names


@pytest.mark.parametrize("cap, section", CRM_CAPS)
@pytest.mark.parametrize("context, customer_id, expected", [
    # owner-level identities: full write.
    ({"junction_roles": {1: "owner"}}, 1, True),
    ({"membership_roles": {1: ["primary_owner"]}}, 1, True),
    ({"membership_roles": {1: ["co_owner"]}}, 1, True),
    ({"membership_roles": {1: ["sales_ops"]}}, 1, True),
    # legacy junction member: content-write parity.
    ({"junction_roles": {1: "member"}}, 1, True),
    # inside-sales: gated on a contribute grant for the MATCHING section only
    # (the mixed-grants case is covered per-cap in
    # test_crm_capability_fail_closed_without_section_argument).
    ({"membership_roles": {1: ["inside_sales"]}}, 1, False),
    # junction auditor: read-only everywhere.
    ({"junction_roles": {1: "auditor"},
      "section_grants": {1: {"opportunities": "contribute"}}}, 1, False),
    # sales-role auditor: read/export only, no section grant can raise this.
    ({"sales_role": "auditor", "junction_roles": {1: "owner"}}, 1, False),
    # sales_admin: reads all accounts, manages via the admin surface only.
    ({"sales_role": "sales_admin", "junction_roles": {1: "owner"}}, 1, False),
    # ps_admin: confined to the third-party surface, no sales capabilities.
    ({"role": "ps_admin", "junction_roles": {1: "owner"}}, 1, False),
    # system admin: everything.
    ({"is_admin": 1}, 1, True),
    # fail-closed without a target customer / out of scope.
    ({"junction_roles": {1: "owner"}}, None, False),
    ({"junction_roles": {2: "owner"}}, 2, False),
])
def test_crm_capability_matrix(cap, section, context, customer_id, expected):
    user = {"username": "synthetic_e0_policy_user", "customer_ids": [1],
            "membership_roles": {}, **context}
    assert sales_access.can(user, None, cap, customer_id, section=section) is expected


@pytest.mark.parametrize("cap, section", CRM_CAPS)
def test_crm_capability_fail_closed_without_section_argument(cap, section):
    # The section-gate defect class: a write gate that forgets the section must NOT
    # let a bare inside_sales membership write. Without ``section`` the
    # resolver defaults fail-closed.
    user = {"username": "synthetic_e0_policy_user", "customer_ids": [1],
            "membership_roles": {1: ["inside_sales"]},
            "section_grants": {1: {section: "contribute"}}}
    assert sales_access.can(user, None, cap, 1, section=section) is True
    assert sales_access.can(user, None, cap, 1, section=None) is False
    # A grant for another section never confers this one.
    other = {"opportunities", "forecasts", "competitors"} - {section}
    user2 = {"username": "synthetic_e0_policy_user", "customer_ids": [1],
             "membership_roles": {1: ["inside_sales"]},
             "section_grants": {1: {sorted(other)[0]: "contribute"}}}
    assert sales_access.can(user2, None, cap, 1, section=section) is False


# ── create_customer membership parity (the 2026-10-15 gap) ─────────────────


def test_create_customer_writes_both_owner_rows(client, db_session, admin):
    r = client.post("/api/customers/", json={
        "name": "E0ParityCo", "description": "parity fixture",
    }, headers=_token("e0_admin", True))
    assert r.status_code == 201, r.text
    c = db_session.query(Customer).filter(Customer.name == "E0ParityCo").first()
    assert c is not None
    legacy = db_session.query(CustomerUser).filter_by(
        customer_id=c.id, user_id=admin.id, role="owner").all()
    assert len(legacy) == 1
    memberships = db_session.query(AccountMembership).filter_by(
        customer_id=c.id, user_id=admin.id).all()
    assert len(memberships) == 1
    assert memberships[0].role == "primary_owner"
    assert memberships[0].source == "manual"
    audit = db_session.query(AuditLog).filter_by(
        action="membership.add", customer_id=c.id).all()
    assert len(audit) == 1
    details = json.loads(audit[0].details)
    assert details["details"]["reason"] == "customer.create"
    assert details["role"] == "primary_owner"


def test_create_customer_duplicate_name_keeps_single_membership(client, db_session, admin):
    r1 = client.post("/api/customers/", json={"name": "E0DupCo"},
                     headers=_token("e0_admin", True))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/api/customers/", json={"name": "E0DupCo"},
                     headers=_token("e0_admin", True))
    assert r2.status_code == 400
    c = db_session.query(Customer).filter(Customer.name == "E0DupCo").first()
    assert db_session.query(AccountMembership).filter_by(
        customer_id=c.id).count() == 1


# ── stage_creator_membership: idempotency + conflict guard ──────────────────


def test_stage_creator_membership_is_idempotent(db_session, admin):
    c = Customer(name="E0StageCo")
    db_session.add(c)
    db_session.commit()
    row1 = membership_service.stage_creator_membership(db_session, c, admin.id, admin.id)
    row2 = membership_service.stage_creator_membership(db_session, c, admin.id, admin.id)
    assert row1 is not None and row2 is not None and row1.id == row2.id
    assert db_session.query(AccountMembership).filter_by(
        customer_id=c.id).count() == 1
    db_session.flush()  # the audit row rides the transaction; flush to assert it
    assert db_session.query(AuditLog).filter_by(
        action="membership.add", customer_id=c.id).count() == 1


def test_stage_creator_membership_refuses_to_displace(db_session, admin):
    other = User(
        username="e0_other", email="e0_other@test.local",
        hashed_password=_FAKE_BCRYPT_HASH, display_name="Other",
        department="IT", is_admin=0, approved=1, is_active=1,
    )
    c = Customer(name="E0DisplaceCo")
    db_session.add_all([other, c])
    db_session.commit()
    # The account already has a primary owner (another user); the legacy
    # owner row for the admin is stale. Staging must refuse, never displace.
    db_session.add(AccountMembership(user_id=other.id, customer_id=c.id,
                                     role="primary_owner", source="manual"))
    db_session.add(CustomerUser(customer_id=c.id, user_id=admin.id,
                                role="owner", granted_by=admin.id))
    db_session.commit()
    assert membership_service.stage_creator_membership(db_session, c, admin.id, admin.id) is None
    rows = db_session.query(AccountMembership).filter_by(
        customer_id=c.id, role="primary_owner").all()
    assert len(rows) == 1 and rows[0].user_id == other.id


# ── backfill: dry-run default, apply, idempotency, conflict refusal ────────


def test_backfill_dry_run_then_apply_then_idempotent(db_session, admin):
    c = Customer(name="E0BackfillCo")
    db_session.add(c)
    db_session.commit()
    db_session.add(CustomerUser(customer_id=c.id, user_id=admin.id,
                                role="owner", granted_by=admin.id))
    db_session.commit()

    dry = membership_service.backfill_creator_ownerships(db_session, dry_run=True)
    assert dry["dry_run"] is True
    assert dry["gaps"] == 1 and dry["to_add"] == 1 and dry["added"] == 0
    assert db_session.query(AccountMembership).filter_by(
        customer_id=c.id).count() == 0  # dry-run wrote nothing

    applied = membership_service.backfill_creator_ownerships(db_session, dry_run=False)
    assert applied["added"] == 1 and applied["conflicts"] == []
    row = db_session.query(AccountMembership).filter_by(
        customer_id=c.id, user_id=admin.id, role="primary_owner").one()
    assert row.source == "migration"
    assert db_session.query(AuditLog).filter_by(
        action="ownership.backfill").count() == 1

    again = membership_service.backfill_creator_ownerships(db_session, dry_run=True)
    assert again["gaps"] == 0 and again["to_add"] == 0  # idempotent


def test_backfill_reports_conflicts_without_touching(db_session, admin):
    other = User(
        username="e0_conflict_other", email="e0_conflict_other@test.local",
        hashed_password=_FAKE_BCRYPT_HASH, display_name="Conflict Other",
        department="IT", is_admin=0, approved=1, is_active=1,
    )
    c = Customer(name="E0ConflictCo")
    db_session.add_all([other, c])
    db_session.commit()
    db_session.add(AccountMembership(user_id=other.id, customer_id=c.id,
                                     role="primary_owner", source="manual"))
    db_session.add(CustomerUser(customer_id=c.id, user_id=admin.id,
                                role="owner", granted_by=admin.id))
    db_session.commit()

    report = membership_service.backfill_creator_ownerships(db_session, dry_run=False)
    assert report["conflicts"] == [c.id]
    assert report["added"] == 0
    rows = db_session.query(AccountMembership).filter_by(
        customer_id=c.id, role="primary_owner").all()
    assert len(rows) == 1 and rows[0].user_id == other.id  # untouched


# ── the backfill script (raw-CLI wrapper) end to end on a scratch file ─────


def _scratch_db(path):
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL);
        CREATE TABLE customer_users (
            id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, role TEXT NOT NULL, granted_by INTEGER);
        CREATE TABLE account_memberships (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            customer_id INTEGER NOT NULL, role TEXT NOT NULL,
            section_grants TEXT, source TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT);
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
            username TEXT NOT NULL, action TEXT NOT NULL,
            customer_id INTEGER, target_id INTEGER, details TEXT,
            ip_address TEXT, created_at TEXT);
    """)
    return con


def test_backfill_script_dry_run_apply_idempotent_conflict(tmp_path, admin):
    import sys as _sys

    db_file = tmp_path / "e0_backfill.sqlite"
    con = _scratch_db(db_file)
    cur = con.cursor()
    cur.execute("INSERT INTO users (id, username) VALUES (7, 'legacy-owner')")
    cur.execute("INSERT INTO users (id, username) VALUES (8, 'other-owner')")
    cur.execute("INSERT INTO customers (id, name) VALUES (1, 'GapCo'), (2, 'ConflictCo')")
    # Gap: legacy owner, no membership. Conflict: another user already PO.
    cur.execute("INSERT INTO customer_users (customer_id, user_id, role) "
                "VALUES (1, 7, 'owner'), (2, 7, 'owner')")
    cur.execute("INSERT INTO account_memberships (user_id, customer_id, role, source) "
                "VALUES (8, 2, 'primary_owner', 'manual')")
    con.commit()
    con.close()

    env_db = f"DB_PATH={db_file}"
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "scripts", "backfill_creator_ownerships.py")

    def run(*args):
        import os as _os
        import subprocess as sp
        e = dict(_os.environ)
        e["DB_PATH"] = str(db_file)
        return sp.run([_sys.executable, script, *args], capture_output=True,
                      text=True, env=e)

    def _report(out: str) -> dict:
        # The script prints the JSON report followed by a status line.
        return json.loads(out[out.index("{"):out.rindex("}") + 1])

    # dry-run: reports, writes nothing
    r = run()
    assert r.returncode == 0, r.stderr
    report = _report(r.stdout)
    assert report["dry_run"] is True and report["gaps"] == 2
    assert report["to_add"] == 1 and report["conflicts"] == [2]
    con = sqlite3.connect(db_file)
    assert con.execute("SELECT COUNT(*) FROM account_memberships").fetchone()[0] == 1
    con.close()

    # apply: fills the gap only, records one audit row
    r = run("--apply")
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db_file)
    row = con.execute(
        "SELECT user_id, source FROM account_memberships "
        "WHERE customer_id=1 AND role='primary_owner'").fetchall()
    assert row == [(7, "migration")]
    assert con.execute(
        "SELECT COUNT(*) FROM account_memberships WHERE customer_id=2"
    ).fetchone()[0] == 1  # conflict untouched
    assert con.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE action='ownership.backfill'"
    ).fetchone()[0] == 1
    con.close()

    # idempotent: nothing left to ADD — the conflict row stays reported
    # (report_only, never backfilled) by design.
    r = run()
    report = _report(r.stdout)
    assert report["to_add"] == 0 and report["added"] == 0
    assert report["gaps"] == 1 and report["conflicts"] == [2]


@pytest.mark.parametrize("ambiguous", [False, True])
def test_backfill_deduplicates_owners_and_refuses_ambiguity(db_session, admin, ambiguous):
    other = User(username="e0_ambiguous", email="e0_ambiguous@test.local",
                 hashed_password=_FAKE_BCRYPT_HASH, approved=1, is_active=1)
    customer = Customer(name="E0Ambiguous")
    db_session.add_all([other, customer])
    db_session.commit()
    db_session.add_all([
        CustomerUser(customer_id=customer.id, user_id=admin.id, role="owner"),
        CustomerUser(customer_id=customer.id, user_id=admin.id, role="owner"),
    ])
    if ambiguous:
        db_session.add(CustomerUser(customer_id=customer.id, user_id=other.id, role="owner"))
    db_session.commit()
    for dry_run in (True, False):
        result = membership_service.backfill_creator_ownerships(db_session, dry_run=dry_run)
        assert result["gaps"] == (2 if ambiguous else 1)
        assert result["to_add"] == (0 if ambiguous else 1)
        assert result["conflicts"] == ([customer.id] if ambiguous else [])
        assert all(row["reason"] == ("multiple_legacy_owners" if ambiguous else None)
                   for row in result["detail"])
    owners = db_session.query(AccountMembership).filter_by(customer_id=customer.id).all()
    assert len(owners) == (0 if ambiguous else 1)
    again = membership_service.backfill_creator_ownerships(db_session, dry_run=False)
    assert again["added"] == 0
    assert db_session.query(AuditLog).filter_by(action="ownership.backfill").count() == (
        0 if ambiguous else 1)


def test_backfill_rechecks_after_dry_run_and_locks_before_read(db_session, admin, monkeypatch):
    customer = Customer(name="E0Concurrent")
    db_session.add(customer)
    db_session.commit()
    db_session.add(CustomerUser(customer_id=customer.id, user_id=admin.id, role="owner"))
    db_session.commit()
    assert membership_service.backfill_creator_ownerships(db_session)["to_add"] == 1
    other = User(username="e0_new_owner", email="e0_new_owner@test.local",
                 hashed_password=_FAKE_BCRYPT_HASH, approved=1, is_active=1)
    db_session.add(other)
    db_session.flush()
    db_session.add(AccountMembership(customer_id=customer.id, user_id=other.id,
                                     role="primary_owner", source="manual"))
    db_session.commit()
    original = membership_service.find_creator_ownership_gaps

    def checked_find(db):
        # A competing writer must be blocked while apply reads its candidates.
        if db.get_bind().dialect.name == "postgresql":
            from sqlalchemy import text
            from sqlalchemy.exc import OperationalError
            with db.get_bind().connect() as other_connection:
                other_connection.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(OperationalError):
                    other_connection.execute(text("UPDATE customers SET id=id WHERE id=:id"), {"id": customer.id})
            return original(db)
        con = sqlite3.connect(db.get_bind().url.database, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                con.execute("UPDATE customers SET id=id WHERE 0")
        finally:
            con.close()
        return original(db)

    monkeypatch.setattr(membership_service, "find_creator_ownership_gaps", checked_find)
    report = membership_service.backfill_creator_ownerships(db_session, dry_run=False)
    assert report["added"] == 0
    assert report["conflicts"] == [customer.id]
    assert db_session.query(AccountMembership).filter_by(customer_id=customer.id).one().user_id == other.id


def test_backfill_failure_rolls_back_all_accounts(db_session, admin, monkeypatch):
    customers = [Customer(name=f"E0Rollback{i}") for i in range(2)]
    db_session.add_all(customers)
    db_session.commit()
    for customer in customers:
        db_session.add(CustomerUser(customer_id=customer.id, user_id=admin.id, role="owner"))
    db_session.commit()

    def fail_audit(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(membership_service, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        membership_service.backfill_creator_ownerships(db_session, dry_run=False)
    assert db_session.query(AccountMembership).count() == 0
    assert membership_service.backfill_creator_ownerships(db_session)["to_add"] == 2


@pytest.mark.parametrize("ambiguous", [False, True])
def test_backfill_cli_deduplicates_and_reports_ambiguous_owners(tmp_path, ambiguous):
    import subprocess
    import sys
    from pathlib import Path

    db_file = tmp_path / "ambiguous.sqlite"
    con = _scratch_db(db_file)
    con.executescript("""
        INSERT INTO users (id, username) VALUES (7, 'first'), (8, 'second');
        INSERT INTO customers (id, name) VALUES (1, 'Legacy');
        INSERT INTO customer_users (customer_id, user_id, role)
        VALUES (1, 7, 'owner'), (1, 7, 'owner');
    """)
    if ambiguous:
        con.execute("INSERT INTO customer_users (customer_id, user_id, role) VALUES (1, 8, 'owner')")
    con.commit()
    script = Path(__file__).resolve().parents[2] / "scripts/backfill_creator_ownerships.py"
    for args in ([], ["--apply"], ["--apply"]):
        result = subprocess.run([sys.executable, str(script), *args],
                                env={**os.environ, "DB_PATH": str(db_file)},
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout[result.stdout.index("{"):result.stdout.rindex("}") + 1])
        assert report["conflicts"] == ([1] if ambiguous else [])
        if ambiguous:
            assert report["to_add"] == 0
            assert len(report["detail"]) == 2
            assert all(row["reason"] == "multiple_legacy_owners" for row in report["detail"])
    assert con.execute("SELECT COUNT(*) FROM account_memberships").fetchone()[0] == (0 if ambiguous else 1)
    assert con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == (0 if ambiguous else 1)
    con.close()


def test_backfill_cli_failure_rolls_back_entire_pass(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    db_file = tmp_path / "rollback.sqlite"
    con = _scratch_db(db_file)
    con.executescript("""
        INSERT INTO users (id, username) VALUES (7, 'owner');
        INSERT INTO customers (id, name) VALUES (1, 'First'), (2, 'Second');
        INSERT INTO customer_users (customer_id, user_id, role)
        VALUES (1, 7, 'owner'), (2, 7, 'owner');
        CREATE TRIGGER reject_backfill_audit BEFORE INSERT ON audit_logs
        BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END;
    """)
    con.commit()
    script = Path(__file__).resolve().parents[2] / "scripts/backfill_creator_ownerships.py"
    result = subprocess.run([sys.executable, str(script), "--apply"],
                            env={**os.environ, "DB_PATH": str(db_file)},
                            text=True, capture_output=True)
    assert result.returncode == 1
    assert "rolled back" in result.stderr
    assert con.execute("SELECT COUNT(*) FROM account_memberships").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 0
    con.close()
