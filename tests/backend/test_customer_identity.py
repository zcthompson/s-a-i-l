"""ER-10: non-reusing account IDs and retained audit isolation across generations."""

import importlib.util
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from backend.auth import create_access_token
from backend.models.collaboration import AuditLog
from backend.models.customer_contact import CustomerContact
from backend.models.customer_technology import CustomerTechnology
from backend.models.use_case import Base, Customer, CustomerUser, User
from backend.services.account_timeline import _memberships
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]


def _audit(db, cid, action, when, actor):
    row = AuditLog(user_id=1, username=actor, action=action, customer_id=cid,
                   details='{"role":"primary_owner"}', created_at=when)
    db.add(row)
    db.flush()
    return row.id


@pytest.mark.parametrize("deletion_marker", [False, True])
def test_legacy_reused_id_hides_former_history_from_replacement_reader(client, db_session, deletion_marker):
    cid = 100
    born = datetime(2026, 11, 4, 12)
    account = Customer(id=cid, name="Synthetic replacement", created_at=born)
    reader = User(username="replacement_reader", approved=1, is_active=1, is_admin=0, sales_role="rep")
    db_session.add_all([account, reader])
    db_session.flush()
    db_session.add(CustomerUser(customer_id=cid, user_id=reader.id, role="owner"))
    old = _audit(db_session, cid, "membership.add", datetime(2020, 1, 1), "Former account actor")
    if deletion_marker:
        # Even equal/future timestamps cannot bypass the recorded deletion boundary.
        _audit(db_session, cid, "ownership.transfer", datetime(2030, 1, 1), "Former future-dated actor")
        _audit(db_session, cid, "membership.remove", born, "Former same-instant actor")
        _audit(db_session, cid, "customer.delete", born, "Deleting actor")
    current = _audit(db_session, cid, "membership.add", born, "Current account actor")
    db_session.commit()
    token = create_access_token({"sub": reader.username})
    response = client.get(f"/api/customers/{cid}/timeline/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    events = [event for event in response.json()["items"] if event["kind"] == "membership"]
    assert [(event["id"], event["actor"]) for event in events] == [(current, "Current account actor")]
    assert db_session.get(AuditLog, old).username == "Former account actor"  # retained verbatim


def test_unknown_account_birth_fails_closed_for_membership_history(db_session):
    account = Customer(name="Synthetic unknown account birth")
    db_session.add(account)
    db_session.flush()
    cid = account.id
    db_session.query(Customer).filter_by(id=cid).update({"created_at": None})
    _audit(db_session, cid, "membership.add", datetime(2020, 1, 1), "Unattributed actor")
    db_session.commit()
    assert _memberships(db_session, cid) == []
    assert db_session.query(AuditLog).filter_by(customer_id=cid).count() == 1


def test_fresh_model_schema_does_not_reuse_deleted_maximum_id():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            old = Customer(name="Synthetic first generation")
            db.add(old)
            db.commit()
            old_id = old.id
            db.delete(old)
            db.commit()
            replacement = Customer(name="Synthetic second generation")
            db.add(replacement)
            db.commit()
            assert replacement.id > old_id
    finally:
        engine.dispose()


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


def test_migration_preserves_all_data_and_reserves_historical_ids(tmp_path):
    path = tmp_path / "identity.sqlite"
    _alembic(path, "upgrade", "0021_add_technology_eol_fields")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with Session(engine) as db:
            user = User(username="Synthetic identity owner", approved=1, is_active=1)
            customer = Customer(id=3, name="Synthetic preserved customer", branch="Synthetic branch")
            db.add_all([user, customer])
            db.flush()
            db.add_all([
                CustomerUser(user_id=user.id, customer_id=customer.id, role="owner"),
                CustomerContact(customer_id=customer.id, display_name="Synthetic preserved contact"),
                CustomerTechnology(customer_id=customer.id, name="Synthetic preserved technology", category="software"),
            ])
            _audit(db, 5000, "customer.delete", datetime(2020, 1, 1), "Synthetic historical actor")
            db.commit()
    finally:
        engine.dispose()
    before = _snapshot(path)
    with sqlite3.connect(path) as con:
        indexes = con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='customers' ORDER BY name").fetchall()
    _alembic(path, "upgrade", "head")
    after = _snapshot(path)
    assert {table: after[table] for table in before} == before
    assert after["redhat_opportunity_imports"] == []
    assert after["redhat_opportunity_rows"] == []
    _alembic(path, "check")
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert con.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='customers' ORDER BY name").fetchall() == indexes
        assert 'AUTOINCREMENT' in con.execute("SELECT sql FROM sqlite_master WHERE name='customers'").fetchone()[0]
        first = con.execute("INSERT INTO customers(name) VALUES ('Synthetic post-migration')").lastrowid
        assert first > 5000
        con.execute("DELETE FROM customers WHERE id=?", (first,))
        second = con.execute("INSERT INTO customers(name) VALUES ('Synthetic next generation')").lastrowid
        assert second > first
        con.execute("UPDATE sqlite_sequence SET seq=10000 WHERE name='customers'")
    # Recovery upgrade must not lower an allocator already above every retained ID.
    _alembic(path, "stamp", "0021_add_technology_eol_fields")
    _alembic(path, "upgrade", "head")
    _alembic(path, "check")
    _alembic(path, "downgrade", "0021_add_technology_eol_fields")
    with sqlite3.connect(path) as con:
        assert con.execute("INSERT INTO customers(name) VALUES ('Synthetic after downgrade')").lastrowid > 10000
    _alembic(path, "upgrade", "head")
    _alembic(path, "check")


def test_migration_refuses_parent_rebuild_with_foreign_keys_enabled(tmp_path):
    path = tmp_path / "fk-on.sqlite"
    _alembic(path, "upgrade", "0021_add_technology_eol_fields")
    spec = importlib.util.spec_from_file_location("identity_migration", ROOT / "alembic/versions/0022_prevent_customer_id_reuse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="foreign_keys=OFF"):
                    module.upgrade()
            assert 'AUTOINCREMENT' not in connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name='customers'").scalar()
    finally:
        engine.dispose()


def _migration_module():
    spec = importlib.util.spec_from_file_location("identity_migration", ROOT / "alembic/versions/0022_prevent_customer_id_reuse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_reserves_writer_before_reading_historical_ids(tmp_path):
    from sqlalchemy import event

    path = tmp_path / "writer-lock.sqlite"
    _alembic(path, "upgrade", "0021_add_technology_eol_fields")
    engine = create_engine(f"sqlite:///{path}")
    observed = []

    def inspect_lock(connection, cursor, statement, parameters, context, executemany):
        if "MAX(customer_id)" not in statement:
            return
        with sqlite3.connect(path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("UPDATE customers SET id=id WHERE 0")
        observed.append(True)

    event.listen(engine, "before_cursor_execute", inspect_lock)
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                _migration_module().upgrade()
        assert observed == [True]
    finally:
        engine.dispose()


def test_migration_failure_rolls_back_parent_and_dependents(tmp_path):
    from sqlalchemy import event

    path = tmp_path / "rollback.sqlite"
    _alembic(path, "upgrade", "0021_add_technology_eol_fields")
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO customers(id, name) VALUES (1, 'Synthetic retained customer')")
        con.execute("INSERT INTO departments(id, name, customer_id) VALUES (1, 'Synthetic department', 1)")
    before = _snapshot(path)
    engine = create_engine(f"sqlite:///{path}")

    def fail_rename(connection, cursor, statement, parameters, context, executemany):
        if "ALTER TABLE" in statement and "_alembic_tmp_customers" in statement and "RENAME TO" in statement:
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
        assert "AUTOINCREMENT" not in con.execute("SELECT sql FROM sqlite_master WHERE name='customers'").fetchone()[0]
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
