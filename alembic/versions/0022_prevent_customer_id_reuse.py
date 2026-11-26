"""Prevent SQLite customer ID reuse without discarding retained audit history.

Rebuild only the parent table with AUTOINCREMENT, preserving its rows, indexes
and constraints. The allocator starts above current IDs AND retained audit
customer references, including orphaned references above the current maximum.
The isolated Alembic connection must have foreign-key enforcement OFF before
this parent-table rebuild; fail before any DDL if it is enabled.

Downgrade intentionally retains the non-reuse security invariant and sequence.
Earlier migrations can still drop the table during a full disposable rollback.
"""

import sqlalchemy as sa
from alembic import op

from backend.migration_sequences import reserve_ids

revision = "0022_prevent_customer_id_reuse"
down_revision = "0021_add_technology_eol_fields"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        reserve_ids(bind, "customers", [("audit_logs", "customer_id", None)])
        return
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Customer ID non-reuse migration requires SQLite")
    ddl = bind.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='customers'"
    )).scalar_one()
    rebuild = "AUTOINCREMENT" not in ddl.upper()
    if rebuild and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Run the customer identity migration on an isolated connection with foreign_keys=OFF")
    # Reserve the writer before calculating the historical allocation floor.
    # This also makes the parent-table copy/drop/rename one SQLite transaction.
    bind.exec_driver_sql("UPDATE customers SET id=id WHERE 0")
    inspector = sa.inspect(bind)
    previous = 0
    if inspector.has_table("sqlite_sequence"):
        previous = bind.execute(sa.text(
            "SELECT COALESCE(MAX(seq), 0) FROM sqlite_sequence WHERE name='customers'"
        )).scalar_one()
    maximum = bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM customers")).scalar_one()
    historical = bind.execute(sa.text(
        "SELECT COALESCE(MAX(customer_id), 0) FROM audit_logs"
    )).scalar_one()
    high_water = max(0, previous, maximum, historical)
    if rebuild:
        with op.batch_alter_table("customers", recreate="always",
                                  table_kwargs={"sqlite_autoincrement": True}):
            pass
    bind.execute(sa.text("UPDATE sqlite_sequence SET seq=:seq WHERE name='customers'"), {"seq": high_water})
    bind.execute(sa.text(
        "INSERT INTO sqlite_sequence(name, seq) SELECT 'customers', :seq "
        "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='customers')"
    ), {"seq": high_water})


def downgrade():
    # Do not reintroduce ID reuse or lower the allocation high-water mark.
    pass
