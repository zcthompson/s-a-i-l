"""User deletion cleanup and user ID non-reuse (orphaned sales_reporting finding).

Runtime SQLite runs with PRAGMA foreign_keys OFF, so declared ON DELETE actions
never fire. These tests use their own engines with enforcement OFF to match
production, unlike the shared fixture connection.
"""

import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from backend.models.account_membership import AccountMembership
from backend.models.sales_access import (
    InsideSalesAssignment,
    SalesOpsAssignment,
    SalesReporting,
)
from backend.models.saved_view import SavedView
from backend.models.use_case import Base, Customer, CustomerUser, User
from backend.services.user_service import UserService
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def fk_off_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_off(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=OFF")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def _user(db, name, **kw):
    user = User(username=name, approved=1, is_active=1, **kw)
    db.add(user)
    db.flush()
    return user


def _seed_relationships(db):
    admin = _user(db, "synthetic-admin", is_admin=1)
    manager = _user(db, "synthetic-manager", sales_role="sales_manager")
    rep = _user(db, "synthetic-rep", sales_role="rep")
    report = _user(db, "synthetic-report", sales_role="rep")
    other = _user(db, "synthetic-other")
    account = Customer(name="Synthetic account")
    db.add(account)
    db.flush()
    db.add_all([
        SalesReporting(rep_user_id=rep.id, manager_user_id=manager.id),
        SalesReporting(rep_user_id=report.id, manager_user_id=rep.id),
        InsideSalesAssignment(inside_sales_user_id=rep.id, customer_id=account.id),
        InsideSalesAssignment(inside_sales_user_id=other.id, customer_id=account.id, rep_user_id=rep.id),
        SalesOpsAssignment(user_id=rep.id, customer_id=account.id),
        AccountMembership(user_id=rep.id, customer_id=account.id, role="co_owner"),
        AccountMembership(user_id=other.id, customer_id=account.id, role="co_owner"),
        SavedView(user_id=rep.id, name="Mine", name_norm="mine", surface="customers", params={}),
        CustomerUser(customer_id=account.id, user_id=rep.id, role="owner"),
        CustomerUser(customer_id=account.id, user_id=other.id, role="member", granted_by=rep.id),
    ])
    db.commit()
    return admin, manager, rep, report, other, account


def test_delete_user_removes_every_access_reference_without_fk_enforcement(fk_off_db):
    db = fk_off_db
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 0
    admin, manager, rep, report, other, account = _seed_relationships(db)
    rep_id = rep.id

    UserService.delete_user(db, rep_id, admin.id)
    db.expire_all()

    assert db.get(User, rep_id) is None
    assert db.query(SalesReporting).filter(
        (SalesReporting.rep_user_id == rep_id) | (SalesReporting.manager_user_id == rep_id)).count() == 0
    assert db.query(InsideSalesAssignment).filter_by(inside_sales_user_id=rep_id).count() == 0
    supported = db.query(InsideSalesAssignment).filter_by(inside_sales_user_id=other.id).one()
    assert supported.rep_user_id is None
    assert db.query(SalesOpsAssignment).filter_by(user_id=rep_id).count() == 0
    assert db.query(AccountMembership).filter_by(user_id=rep_id).count() == 0
    assert db.query(SavedView).filter_by(user_id=rep_id).count() == 0
    assert db.query(CustomerUser).filter_by(user_id=rep_id).count() == 0
    # Access granted BY the deleted user to someone else is retained.
    grant = db.query(CustomerUser).filter_by(user_id=other.id).one()
    assert grant.granted_by is None
    assert db.query(AccountMembership).filter_by(user_id=other.id).count() == 1
    assert db.execute(text("PRAGMA foreign_key_check")).fetchall() == []


def test_new_user_never_inherits_deleted_users_reporting_line(fk_off_db):
    db = fk_off_db
    admin, manager, rep, report, other, account = _seed_relationships(db)
    deleted = [report.id, other.id]
    UserService.delete_user(db, other.id, admin.id)
    UserService.delete_user(db, report.id, admin.id)
    first = _user(db, "synthetic-new-1")
    second = _user(db, "synthetic-new-2", sales_role="sales_manager")
    db.commit()
    assert min(first.id, second.id) > max(deleted)
    assert db.query(SalesReporting).filter(SalesReporting.rep_user_id.in_([first.id, second.id])).count() == 0
    assert db.query(SalesReporting).filter_by(manager_user_id=second.id).count() == 0


def test_delete_user_failure_rolls_back_every_cleanup(fk_off_db, monkeypatch):
    db = fk_off_db
    admin, manager, rep, report, other, account = _seed_relationships(db)
    rep_id = rep.id

    def fail(_obj):
        raise RuntimeError("synthetic delete failure")

    monkeypatch.setattr(db, "delete", fail)
    with pytest.raises(RuntimeError, match="synthetic delete failure"):
        UserService.delete_user(db, rep_id, admin.id)
    db.expire_all()
    assert db.get(User, rep_id) is not None
    assert db.query(SalesReporting).filter_by(rep_user_id=rep_id).count() == 1
    assert db.query(SalesReporting).filter_by(manager_user_id=rep_id).count() == 1
    assert db.query(CustomerUser).filter_by(user_id=other.id).one().granted_by == rep_id


def test_fresh_model_schema_does_not_reuse_deleted_maximum_user_id(fk_off_db):
    db = fk_off_db
    old = _user(db, "synthetic-first")
    db.commit()
    old_id = old.id
    db.delete(old)
    db.commit()
    assert _user(db, "synthetic-second").id > old_id


# ── Migration 0024 ───────────────────────────────────────────────────────────

def _alembic(path, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}", "SAIL_DATABASE_URL": f"sqlite:///{path}"}
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout + result.stderr


def _snapshot(path):
    with sqlite3.connect(path) as con:
        tables = [row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if row[0] not in ("sqlite_sequence", "alembic_version")]
        return {table: con.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall() for table in tables}


def _migration_module():
    spec = importlib.util.spec_from_file_location(
        "user_identity_migration", ROOT / "alembic/versions/0024_prevent_user_id_reuse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_preserves_data_and_reserves_every_historical_user_id(tmp_path):
    path = tmp_path / "users.sqlite"
    _alembic(path, "upgrade", "0023_redhat_opportunity_import")
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO users(id, username, approved, is_active, auth_provider, role) "
                    "VALUES (3, 'synthetic-kept', 1, 1, 'local', 'user')")
        con.execute("INSERT INTO customers(id, name) VALUES (1, 'Synthetic account')")
        con.execute("INSERT INTO customer_users(customer_id, user_id, role) VALUES (1, 3, 'owner')")
        # Orphaned reporting line left by an unenforced deletion (preserved, not repaired).
        con.execute("INSERT INTO sales_reporting(rep_user_id, manager_user_id) VALUES (40, 41)")
        con.execute("INSERT INTO audit_logs(user_id, username, action, target_id, created_at) VALUES (3, 'a', 'add_user', 500, '2026-01-01')")
        # A non-user target must not raise the user floor.
        con.execute("INSERT INTO audit_logs(user_id, username, action, target_id, created_at) VALUES (3, 'a', 'membership.add', 9000, '2026-01-01')")
        indexes = con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='users' "
                              "ORDER BY name").fetchall()
        fk_before = con.execute("PRAGMA foreign_key_check").fetchall()
    before = _snapshot(path)
    _alembic(path, "upgrade", "head")
    after = _snapshot(path)  # later migrations may add tables; existing data must be unchanged
    assert {table: after[table] for table in before} == before
    _alembic(path, "check")
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == fk_before
        assert con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='users' "
                           "ORDER BY name").fetchall() == indexes
        assert "AUTOINCREMENT" in con.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
        insert = ("INSERT INTO users(username, approved, is_active, auth_provider, role) "
                  "VALUES (?, 1, 1, 'local', 'user')")
        first = con.execute(insert, ("synthetic-post-1",)).lastrowid
        assert 500 < first < 9000
        con.execute("DELETE FROM users WHERE id=?", (first,))
        assert con.execute(insert, ("synthetic-post-2",)).lastrowid > first
        con.execute("UPDATE sqlite_sequence SET seq=20000 WHERE name='users'")
    # Recovery re-upgrade never lowers a higher allocator; downgrade keeps the invariant.
    _alembic(path, "stamp", "0023_redhat_opportunity_import")
    _alembic(path, "upgrade", "head")
    _alembic(path, "downgrade", "0023_redhat_opportunity_import")
    with sqlite3.connect(path) as con:
        assert con.execute("INSERT INTO users(username, approved, is_active, auth_provider, role) "
                           "VALUES ('synthetic-after-downgrade', 1, 1, 'local', 'user')").lastrowid > 20000
    _alembic(path, "upgrade", "head")
    _alembic(path, "check")


def test_migration_refuses_parent_rebuild_with_foreign_keys_enabled(tmp_path):
    path = tmp_path / "fk-on.sqlite"
    _alembic(path, "upgrade", "0023_redhat_opportunity_import")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="foreign_keys=OFF"):
                    _migration_module().upgrade()
            assert "AUTOINCREMENT" not in connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name='users'").scalar()
    finally:
        engine.dispose()


def test_migration_reserves_writer_before_reading_historical_ids(tmp_path):
    path = tmp_path / "writer-lock.sqlite"
    _alembic(path, "upgrade", "0023_redhat_opportunity_import")
    engine = create_engine(f"sqlite:///{path}")
    observed = []

    def inspect_lock(connection, cursor, statement, parameters, context, executemany):
        if "MAX(id), 0) FROM users" not in statement:
            return
        with sqlite3.connect(path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("UPDATE users SET id=id WHERE 0")
        observed.append(True)

    event.listen(engine, "before_cursor_execute", inspect_lock)
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                _migration_module().upgrade()
        assert observed == [True]
    finally:
        engine.dispose()


def test_migration_failure_rolls_back_users_and_dependents(tmp_path):
    path = tmp_path / "rollback.sqlite"
    _alembic(path, "upgrade", "0023_redhat_opportunity_import")
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO users(id, username, approved, is_active, auth_provider, role) "
                    "VALUES (1, 'synthetic-retained', 1, 1, 'local', 'user')")
        con.execute("INSERT INTO customers(id, name) VALUES (1, 'Synthetic account')")
        con.execute("INSERT INTO customer_users(customer_id, user_id, role) VALUES (1, 1, 'owner')")
    before = _snapshot(path)
    engine = create_engine(f"sqlite:///{path}")

    def fail_rename(connection, cursor, statement, parameters, context, executemany):
        if "ALTER TABLE" in statement and "_alembic_tmp_users" in statement and "RENAME TO" in statement:
            raise RuntimeError("synthetic migration failure")

    event.listen(engine, "before_cursor_execute", fail_rename)
    try:
        with pytest.raises(RuntimeError, match="synthetic migration failure"):
            with engine.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    _migration_module().upgrade()
    finally:
        engine.dispose()
    assert _snapshot(path) == before
    with sqlite3.connect(path) as con:
        assert "AUTOINCREMENT" not in con.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
