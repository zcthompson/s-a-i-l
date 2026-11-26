"""Add customer alias tags (Part 14, A1).

``customer_aliases`` — alternate names for a customer account. ``alias``
keeps the raw as-typed string; ``alias_norm`` carries the SAME normalization
the intelligence imports use (lower + whitespace-collapse) and is UNIQUE
portfolio-wide, so one alias always resolves to one customer and import
matching is deterministic by construction (A2's write rules guarantee an
alias can never equal a customer name, own or other).

Idempotent: the table create is guarded by an inspector check (the
0013/0014/0017 convention), so the ``stamp <rev>`` + ``upgrade head``
recovery path is a no-op when the table already exists.
``alembic check`` stays clean.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_add_customer_aliases"
down_revision: Union[str, None] = "0017_add_assessment_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customers") and not inspector.has_table("customer_aliases"):
        op.create_table(
            "customer_aliases",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("alias", sa.String(255), nullable=False),
            sa.Column("alias_norm", sa.String(255), nullable=False),
            sa.Column("created_by", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("alias_norm", name="uq_customer_aliases_alias_norm"),
        )
        op.create_index("ix_customer_aliases_customer_id", "customer_aliases", ["customer_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("customer_aliases"):
        op.drop_index("ix_customer_aliases_customer_id", table_name="customer_aliases")
        op.drop_table("customer_aliases")
