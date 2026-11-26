"""ER-12: record delete paths leave no orphaned child rows, and record IDs are
never reissued.

Runtime SQLite runs with PRAGMA foreign_keys OFF, so declared ON DELETE actions
never fire. These tests use their own FK-off engines and populate one row in
EVERY table that declares a foreign key to the deleted parent, so a newly added
child table is covered automatically.
"""

import datetime as dt
import importlib.util
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from backend.models.use_case import Base
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    LargeBinary,
    Numeric,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
PROTECTED = ("account_strategy", "assessments", "customer_activities", "customer_contacts", "customer_knowledge",
             "customer_tasks", "customer_technologies", "departments", "intelligence_imports", "partner_pipeline",
             "redhat_opportunity_imports", "rep_intelligence_imports", "rvtools_imports", "sales_notes",
             "technology_dependencies", "third_party_services", "use_cases")
ADMIN = {"username": "synthetic-admin", "user_id": 1, "is_admin": 1}


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_off(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=OFF")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.execute(Base.metadata.tables["users"].insert().values(
            id=1, username="synthetic-admin", role="admin", is_admin=1, approved=1, is_active=1, auth_provider="local"))
        session.execute(Base.metadata.tables["customers"].insert().values(id=1, name="Synthetic account"))
        session.commit()
        yield session
    engine.dispose()


_SEQ = iter(range(1, 10**9))


def ins(db, table, **given):
    """Insert a row, filling required columns with unique type-appropriate values."""
    t = Base.metadata.tables[table]
    vals = dict(given)
    for col in t.columns:
        if col.name in vals or (col.primary_key and not col.foreign_keys) or col.nullable \
                or col.server_default is not None or col.default is not None:
            continue
        ty = col.type
        if col.foreign_keys:
            vals[col.name] = 1
        elif isinstance(ty, Boolean):
            vals[col.name] = False
        elif isinstance(ty, Integer):
            vals[col.name] = 1
        elif isinstance(ty, (Float, Numeric)):
            vals[col.name] = 0
        elif isinstance(ty, DateTime):
            vals[col.name] = dt.datetime(2026, 1, 1)
        elif isinstance(ty, Date):
            vals[col.name] = dt.date(2026, 1, 1)
        elif isinstance(ty, JSON):
            vals[col.name] = {}
        elif isinstance(ty, LargeBinary):
            vals[col.name] = b"x"
        else:
            vals[col.name] = f"synthetic-{table}-{col.name}-{next(_SEQ)}"
    return db.execute(t.insert().values(**vals)).inserted_primary_key[0]


def children_of(db, parent, pid):
    made = []
    for t in Base.metadata.tables.values():
        for fk in t.foreign_keys:
            if fk.column.table.name == parent:
                ins(db, t.name, **{fk.parent.name: pid}, **({"source_row": next(_SEQ)}
                    if "source_row" in t.c else {}))
                made.append(f"{t.name}.{fk.parent.name}")
    return made


def orphans_of(db, parent):
    return sorted({row[0] for row in db.execute(text("PRAGMA foreign_key_check")).fetchall() if row[2] == parent})


def _delete_technology(db, pid):
    from backend.services.technology_inventory_service import delete_technology
    assert delete_technology(db, pid)


def _delete_contact(db, pid):
    from backend.models.customer_contact import CustomerContact
    from backend.services import customer_contact_service
    db.execute(text("DELETE FROM contact_notes"))  # contacts with linked notes are archived, not deleted (409)
    customer_contact_service.delete_contact(db, db.get(CustomerContact, pid))


def _delete_note(db, pid):
    from backend.services.sales_note_service import delete_sales_note
    assert delete_sales_note(db, pid)


def _delete_task(db, pid):
    from backend.models.customer_engagement import CustomerTask
    from backend.services import customer_engagement_service
    task = db.get(CustomerTask, pid)
    customer_engagement_service.delete_task(db, task, task.version)


def _delete_use_case(db, pid):
    from backend.services.use_case_service import UseCaseService
    assert UseCaseService.delete(db, pid, user=ADMIN)


def _delete_service(db, pid):
    from backend.services import third_party_service
    assert third_party_service.delete(db, ADMIN, pid)


@pytest.mark.parametrize("parent, call", [
    ("customer_technologies", _delete_technology),
    ("customer_contacts", _delete_contact),
    ("sales_notes", _delete_note),
    ("customer_tasks", _delete_task),
    ("use_cases", _delete_use_case),
    ("third_party_services", _delete_service),
], ids=lambda v: v if isinstance(v, str) else v.__name__)
def test_record_delete_leaves_no_orphans(db, parent, call):
    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 0
    pid = ins(db, parent, customer_id=1) if "customer_id" in Base.metadata.tables[parent].c else ins(db, parent)
    made = children_of(db, parent, pid)
    db.commit()
    assert orphans_of(db, parent) == [] and made
    call(db, pid)
    db.expire_all()
    assert orphans_of(db, parent) == []


def test_technology_delete_keeps_import_history_without_link(db):
    pid = ins(db, "customer_technologies", customer_id=1)
    row = ins(db, "rep_intelligence_rows", technology_id=pid)
    db.commit()
    _delete_technology(db, pid)
    assert db.execute(text("SELECT technology_id FROM rep_intelligence_rows WHERE id=:r"), {"r": row}).one() == (None,)


def test_department_delete_cleans_use_case_children(db):
    from backend.models.use_case import Department
    from backend.services.departments_service import delete_department_with_use_cases
    dept = ins(db, "departments", customer_id=1)
    use_case = ins(db, "use_cases", customer_id=1, department_id=dept)
    children_of(db, "use_cases", use_case)
    db.commit()
    delete_department_with_use_cases(db, db.get(Department, dept))
    db.commit()
    assert db.execute(text("SELECT count(*) FROM use_cases")).scalar() == 0
    assert orphans_of(db, "use_cases") == [] and orphans_of(db, "departments") == []


@pytest.mark.parametrize("module, prefix", [
    ("rep_intelligence_service", "generic intelligence import #{id}"),
    ("intelligence_import_service", "{tech_source}"),
    ("rvtools_import_service", "{tech_source}"),
])
def test_import_delete_cleans_children_of_created_technologies(db, module, prefix):
    service = importlib.import_module(f"backend.services.{module}")
    table = {"rep_intelligence_service": "rep_intelligence_imports",
             "intelligence_import_service": "intelligence_imports",
             "rvtools_import_service": "rvtools_imports"}[module]
    extra = {"customer_id": 1} if "customer_id" in Base.metadata.tables[table].c else {}
    batch = ins(db, table, imported_by="synthetic-admin", **extra) if "imported_by" in Base.metadata.tables[table].c \
        else ins(db, table, **extra)
    source = prefix.format(id=batch, tech_source=getattr(service, "_tech_source", lambda i: "")(batch))
    tech = ins(db, "customer_technologies", customer_id=1, source=source)
    children_of(db, "customer_technologies", tech)
    db.commit()
    service.delete_import(db, batch, ADMIN)
    db.expire_all()
    assert db.execute(text("SELECT count(*) FROM customer_technologies WHERE id=:t"), {"t": tech}).scalar() == 0
    assert orphans_of(db, "customer_technologies") == []


def test_fresh_schema_never_reissues_protected_ids(db):
    for table in PROTECTED:
        kw = {"customer_id": 1} if "customer_id" in Base.metadata.tables[table].c else {}
        first = ins(db, table, **kw)
        db.execute(text(f'DELETE FROM "{table}" WHERE id=:i'), {"i": first})
        assert ins(db, table, **kw) > first, table


# ── Migration 0025 ───────────────────────────────────────────────────────────

def _alembic(path, *args):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{path}", "SAIL_DATABASE_URL": f"sqlite:///{path}"}
    env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                            text=True, capture_output=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr


def _snapshot(path):
    with sqlite3.connect(path) as con:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if r[0] not in ("sqlite_sequence", "alembic_version")]
        return {t: con.execute(f'SELECT * FROM "{t}" ORDER BY rowid').fetchall() for t in tables}


def _indexes(con):
    """Index structure (name, uniqueness, columns) per protected table; SQL text formatting may change."""
    out = []
    for table in PROTECTED:
        for _, name, unique, origin, _partial in con.execute(f'PRAGMA index_list("{table}")'):
            cols = [r[2] for r in con.execute(f'PRAGMA index_info("{name}")')]
            out.append((table, name if origin != "u" else "<unique>", unique, origin, tuple(cols)))
    return sorted(out)


def _module():
    spec = importlib.util.spec_from_file_location("record_identity_migration",
                                                  ROOT / "alembic/versions/0025_prevent_record_id_reuse.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_pre_0025(path):
    with sqlite3.connect(path) as con:
        con.execute("INSERT INTO customers(id, name) VALUES (1, 'Synthetic account')")
        con.execute("INSERT INTO customer_technologies(id, customer_id, name, category, verification_state, source, "
                    "created_at, updated_at) VALUES (5, 1, 'Synthetic tech', 'software', 'unverified', 'manual', "
                    "'2026-01-01', '2026-01-01')")
        # Retained references above every current ID (preserved, not repaired).
        con.execute("INSERT INTO contact_technologies(contact_id, technology_id) VALUES (70, 40)")
        con.execute("INSERT INTO customer_tasks(customer_id, title, status, source_type, source_id, version, created_by, "
                    "created_at, updated_at) VALUES (1, 't', 'open', 'eol_attention', 90, 1, 'a', '2026-01-01', '2026-01-01')")
        con.execute("INSERT INTO customer_tasks(customer_id, title, status, source_type, source_id, version, created_by, "
                    "created_at, updated_at) VALUES (1, 'n', 'open', 'note', 300, 1, 'a', '2026-01-01', '2026-01-01')")
        con.execute("INSERT INTO audit_logs(user_id, username, action, target_id, created_at) "
                    "VALUES (1, 'a', 'rvtools_import.delete', 12, '2026-01-01')")
        # A target of an unrelated action must not raise the floor.
        con.execute("INSERT INTO audit_logs(user_id, username, action, target_id, created_at) "
                    "VALUES (1, 'a', 'membership.add', 9000, '2026-01-01')")


def test_migration_preserves_data_and_reserves_every_reference(tmp_path):
    path = tmp_path / "records.sqlite"
    _alembic(path, "upgrade", "0024_prevent_user_id_reuse")
    _seed_pre_0025(path)
    with sqlite3.connect(path) as con:
        indexes = _indexes(con)
        fk_before = con.execute("PRAGMA foreign_key_check").fetchall()
    before = _snapshot(path)
    _alembic(path, "upgrade", "head")
    after = _snapshot(path)  # later migrations may add tables; existing data must be unchanged
    assert {table: after[table] for table in before} == before
    _alembic(path, "check")
    with sqlite3.connect(path) as con:
        assert con.execute("PRAGMA foreign_key_check").fetchall() == fk_before
        assert _indexes(con) == indexes
        for table in PROTECTED:
            assert "AUTOINCREMENT" in con.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0], table
        seq = dict(con.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
        assert seq["customer_technologies"] == 90   # task promotion source above the contact link (40) and row (5)
        assert seq["customer_contacts"] == 70
        assert seq["sales_notes"] == 300
        assert seq["rvtools_imports"] == 12
        assert seq["customer_tasks"] == 2 and seq["use_cases"] == 0
        new = con.execute("INSERT INTO customer_technologies(customer_id, name, category, verification_state, source, "
                          "created_at, updated_at) VALUES (1, 'n', 'software', 'unverified', 'manual', '2026-01-01', "
                          "'2026-01-01')").lastrowid
        assert new == 91
        con.execute("UPDATE sqlite_sequence SET seq=5000 WHERE name='customer_technologies'")
    # Recovery re-upgrade never lowers an allocator; downgrade keeps the invariant.
    _alembic(path, "stamp", "0024_prevent_user_id_reuse")
    _alembic(path, "upgrade", "head")
    _alembic(path, "downgrade", "0024_prevent_user_id_reuse")
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT seq FROM sqlite_sequence WHERE name='customer_technologies'").fetchone()[0] == 5000
        assert "AUTOINCREMENT" in con.execute("SELECT sql FROM sqlite_master WHERE name='use_cases'").fetchone()[0]
    _alembic(path, "upgrade", "head")
    _alembic(path, "check")


def test_migration_refuses_rebuild_with_foreign_keys_enabled(tmp_path):
    path = tmp_path / "fk-on.sqlite"
    _alembic(path, "upgrade", "0024_prevent_user_id_reuse")
    engine = create_engine(f"sqlite:///{path}")
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="foreign_keys=OFF"):
                    _module().upgrade()
            assert "AUTOINCREMENT" not in connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE name='use_cases'").scalar()
    finally:
        engine.dispose()


def test_migration_reserves_writer_before_reading_floors(tmp_path):
    path = tmp_path / "writer.sqlite"
    _alembic(path, "upgrade", "0024_prevent_user_id_reuse")
    engine = create_engine(f"sqlite:///{path}")
    observed = []

    def inspect_lock(connection, cursor, statement, parameters, context, executemany):
        if "COALESCE(MAX(id), 0)" not in statement or observed:
            return
        with sqlite3.connect(path, timeout=0) as competing:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing.execute("UPDATE use_cases SET id=id WHERE 0")
        observed.append(True)

    event.listen(engine, "before_cursor_execute", inspect_lock)
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                _module().upgrade()
        assert observed == [True]
    finally:
        engine.dispose()


def test_migration_failure_rolls_back_every_table(tmp_path):
    path = tmp_path / "rollback.sqlite"
    _alembic(path, "upgrade", "0024_prevent_user_id_reuse")
    _seed_pre_0025(path)
    before = _snapshot(path)
    engine = create_engine(f"sqlite:///{path}")

    def fail_late(connection, cursor, statement, parameters, context, executemany):
        if "ALTER TABLE" in statement and "_alembic_tmp_use_cases" in statement and "RENAME TO" in statement:
            raise RuntimeError("synthetic migration failure")

    event.listen(engine, "before_cursor_execute", fail_late)
    try:
        with pytest.raises(RuntimeError, match="synthetic migration failure"):
            with engine.begin() as connection:
                with Operations.context(MigrationContext.configure(connection)):
                    _module().upgrade()
    finally:
        engine.dispose()
    assert _snapshot(path) == before
    with sqlite3.connect(path) as con:
        for table in PROTECTED:
            assert "AUTOINCREMENT" not in con.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0], table
