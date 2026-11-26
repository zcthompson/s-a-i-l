"""Add auto_linked + link_reason columns to inside_sales_assignments.

Customer-ownership linking surface: track which inside_sales assignments were
created by the opt-in golden-seed auto-link (Pass 5 of seed_accounts_v3) vs
manually via the CustomerSalesTeam editor.

STRICTLY ADDITIVE — nothing existing changes behavior.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_add_auto_linked_flag_to_inside_sales"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("inside_sales_assignments"):
        return

    cols = {c["name"] for c in inspector.get_columns("inside_sales_assignments")}

    # auto_linked: True only for assignments created by the opt-in seed auto-link.
    if "auto_linked" not in cols:
        with op.batch_alter_table(
            "inside_sales_assignments", recreate="auto"
        ) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "auto_linked",
                    sa.Boolean(),
                    nullable=False,
                    server_default=sa.text("false"),
                )
            )

    # link_reason: human-readable rationale for auto-linked assignments
    # (e.g. "Auto-linked: BR15 - SAMPLE BRANCH O supports SMITH — last-name match
    # MUISE==SMITH"). NULL for manually assigned rows.
    if "link_reason" not in cols:
        with op.batch_alter_table(
            "inside_sales_assignments", recreate="auto"
        ) as batch_op:
            batch_op.add_column(
                sa.Column("link_reason", sa.String(255), nullable=True)
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("inside_sales_assignments"):
        return

    with op.batch_alter_table(
        "inside_sales_assignments", recreate="auto"
    ) as batch_op:
        batch_op.drop_column("auto_linked")
        batch_op.drop_column("link_reason")
