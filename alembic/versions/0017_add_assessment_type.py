"""Add assessment round type + purpose (Part 13 WS5, R1/R2/R11).

``assessments.assessment_type`` — String(20) NOT NULL, server_default 'ai';
vocabulary ``ai | generic``. Every existing round is an AI round: the
server_default fills it on ADD COLUMN, and an explicit backfill UPDATE
(loud, idempotent) covers any legacy row that ended up NULL/empty — rows
are never relabeled 'generic'.

``assessments.purpose`` — Text nullable (a round's "why").

Idempotent: each step is guarded by an inspector check (the 0013/0014
convention), so the ``stamp <rev>`` + ``upgrade head`` recovery path is a
no-op when the columns already exist. ``alembic check`` stays clean.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_add_assessment_type"
down_revision: Union[str, None] = "0016_account_strategy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("assessments"):
        return
    cols = {c["name"] for c in inspector.get_columns("assessments")}
    if "assessment_type" not in cols:
        with op.batch_alter_table("assessments", recreate="auto") as batch_op:
            batch_op.add_column(sa.Column(
                "assessment_type", sa.String(20), nullable=False, server_default="ai"))
    if "purpose" not in cols:
        with op.batch_alter_table("assessments", recreate="auto") as batch_op:
            batch_op.add_column(sa.Column("purpose", sa.Text, nullable=True))
    op.execute(
        "UPDATE assessments SET assessment_type = 'ai' "
        "WHERE assessment_type IS NULL OR assessment_type = ''"
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("assessments"):
        return
    cols = {c["name"] for c in inspector.get_columns("assessments")}
    if "assessment_type" in cols or "purpose" in cols:
        with op.batch_alter_table("assessments", recreate="auto") as batch_op:
            if "purpose" in cols:
                batch_op.drop_column("purpose")
            if "assessment_type" in cols:
                batch_op.drop_column("assessment_type")
