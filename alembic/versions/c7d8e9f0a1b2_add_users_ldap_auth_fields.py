"""add LDAP/directory auth fields to users (S-A-I-L federated identity, 0.2.0 P0)

Revision ID: c7d8e9f0a1b2
Revises: f3a4b5c6d7e8
Create Date: 2026-09-14

docs/archive/PLAN_LDAP_AD_AUTH.md §3.3 — federated identity with a local identity anchor.
Adds the three columns that drive directory authentication (auth provider
resolution, idempotent JIT linking, audit trail) and relaxes
``hashed_password`` to NULL so JIT-provisioned directory rows can store no
local password (the value is self-describing via ``auth_provider='ldap'`` —
no sentinel string).

SQLite cannot ``ALTER COLUMN ... DROP NOT NULL`` — the ``users`` table is
rebuilt via Alembic batch operations (charter §3). The rebuild:
  - preserves every existing row and its ``id`` (the ``customer_users``
    junction references users.id, so ids must be stable);
  - keeps all populated ``hashed_password`` values (existing local users are
    untouched — local-first precedence);
  - backfills ``auth_provider='local'`` for pre-existing rows.

Idempotent: the batch step runs only when ``auth_provider`` is absent, so a
re-run (and a fresh DB that already has the columns via create_all) is a no-op.
``alembic check`` stays clean afterwards (no create_all / startup mutation —
charter prohibitions).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _needs_upgrade(bind) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return False
    cols = {c["name"] for c in inspector.get_columns("users")}
    return "auth_provider" not in cols


def upgrade() -> None:
    bind = op.get_bind()
    if not _needs_upgrade(bind):
        return

    # Batch rebuild: relax hashed_password nullability + add the three
    # directory-auth columns. render_as_batch is already set in env.py.
    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.alter_column(
            "hashed_password",
            existing_type=sa.String(255),
            existing_nullable=False,
            nullable=True,
        )
        batch_op.add_column(
            sa.Column(
                "auth_provider",
                sa.String(20),
                nullable=False,
                server_default="local",
            )
        )
        batch_op.add_column(
            sa.Column(
                "external_id",
                sa.String(64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "last_directory_login_at",
                sa.DateTime(),
                nullable=True,
            )
        )
        # Unique on the stable directory entry id (AD objectGUID hex or entry
        # UUID) — enables idempotent JIT link + admin re-link. NULLs are
        # allowed to repeat (SQLite unique treats NULLs as distinct).
        batch_op.create_unique_constraint("uq_users_external_id", ["external_id"])

    # Defensive backfill (server_default handles it on the rebuild, but guard
    # against any row that came in NULL — idempotent no-op when already set).
    op.execute(
        sa.text(
            "UPDATE users SET auth_provider = 'local' "
            "WHERE auth_provider IS NULL"
        )
    )


def downgrade() -> None:
    # Re-assert NOT NULL on hashed_password ONLY if no directory-managed rows
    # exist — never silent data destruction (plan §3.6 rule 8).
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("users"):
        return
    cols = {c["name"] for c in inspector.get_columns("users")}
    if "auth_provider" not in cols:
        return

    ldap_rows = bind.execute(
        sa.text("SELECT COUNT(*) FROM users WHERE auth_provider = 'ldap'")
    ).scalar()
    if ldap_rows:
        raise RuntimeError(
            f"Refusing to downgrade users (auth_provider) while {ldap_rows} "
            "directory-managed row(s) exist — their hashed_password is NULL. "
            "Migrate or remove them first (preservation-first)."
        )

    with op.batch_alter_table("users", recreate="auto") as batch_op:
        batch_op.alter_column(
            "hashed_password",
            existing_type=sa.String(255),
            existing_nullable=True,
            nullable=False,
        )
        batch_op.drop_constraint("uq_users_external_id", type_="unique")
        batch_op.drop_column("auth_provider")
        batch_op.drop_column("external_id")
        batch_op.drop_column("last_directory_login_at")
