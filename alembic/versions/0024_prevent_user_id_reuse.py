"""Prevent SQLite user ID reuse without discarding retained references.

Rebuild only the parent ``users`` table with AUTOINCREMENT, preserving its
rows, indexes and constraints. The allocator starts above current user IDs and
every retained user reference: access/reporting tables (including orphaned
rows left by earlier deletions while SQLite did not enforce ON DELETE), audit
actors and audit events whose target is a user. The isolated Alembic
connection must have foreign-key enforcement OFF before this parent-table
rebuild; fail before any DDL if it is enabled.

Orphaned rows are not modified here; they are reported for an explicit,
reviewed repair. Downgrade intentionally retains the non-reuse invariant.
"""

import sqlalchemy as sa
from alembic import op

from backend.migration_sequences import reserve_ids

revision = "0024_prevent_user_id_reuse"
down_revision = "0023_redhat_opportunity_import"
branch_labels = None
depends_on = None

# (table, column) pairs holding user IDs.
USER_REFERENCES = (
    ("customer_users", "user_id"),
    ("customer_users", "granted_by"),
    ("account_memberships", "user_id"),
    ("sales_reporting", "rep_user_id"),
    ("sales_reporting", "manager_user_id"),
    ("inside_sales_assignments", "inside_sales_user_id"),
    ("inside_sales_assignments", "rep_user_id"),
    ("sales_ops_assignments", "user_id"),
    ("saved_views", "user_id"),
    ("audit_logs", "user_id"),
)
# Audit actions whose target_id is a user ID.
USER_TARGET_ACTIONS = ("add_user", "remove_user", "set_manager", "set_primary_rep")


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        refs = [(t, c, None) for t, c in USER_REFERENCES]
        actions = ", ".join("'" + action + "'" for action in USER_TARGET_ACTIONS)
        refs.append(("audit_logs", "target_id", f"action IN ({actions})"))
        reserve_ids(bind, "users", refs)
        return
    if bind.dialect.name != "sqlite":
        raise RuntimeError("User ID non-reuse migration requires SQLite")
    ddl = bind.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    )).scalar_one()
    rebuild = "AUTOINCREMENT" not in ddl.upper()
    if rebuild and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Run the user identity migration on an isolated connection with foreign_keys=OFF")
    # Reserve the writer before calculating the historical allocation floor.
    # This also makes the parent-table copy/drop/rename one SQLite transaction.
    bind.exec_driver_sql("UPDATE users SET id=id WHERE 0")
    inspector = sa.inspect(bind)
    candidates = [bind.execute(sa.text("SELECT COALESCE(MAX(id), 0) FROM users")).scalar_one()]
    if inspector.has_table("sqlite_sequence"):
        candidates.append(bind.execute(sa.text(
            "SELECT COALESCE(MAX(seq), 0) FROM sqlite_sequence WHERE name='users'"
        )).scalar_one())
    for table, column in USER_REFERENCES:
        if inspector.has_table(table) and column in {c["name"] for c in inspector.get_columns(table)}:
            candidates.append(bind.execute(sa.text(
                f'SELECT COALESCE(MAX("{column}"), 0) FROM "{table}" WHERE typeof("{column}")=\'integer\''
            )).scalar_one())
    if inspector.has_table("audit_logs"):
        candidates.append(bind.execute(
            sa.text("SELECT COALESCE(MAX(target_id), 0) FROM audit_logs WHERE action IN :actions")
            .bindparams(sa.bindparam("actions", expanding=True)),
            {"actions": list(USER_TARGET_ACTIONS)},
        ).scalar_one())
    high_water = max(0, *candidates)
    if rebuild:
        with op.batch_alter_table("users", recreate="always",
                                  table_kwargs={"sqlite_autoincrement": True}):
            pass
    bind.execute(sa.text("UPDATE sqlite_sequence SET seq=:seq WHERE name='users'"), {"seq": high_water})
    bind.execute(sa.text(
        "INSERT INTO sqlite_sequence(name, seq) SELECT 'users', :seq "
        "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='users')"
    ), {"seq": high_water})


def downgrade():
    # Do not reintroduce ID reuse or lower the allocation high-water mark.
    pass
