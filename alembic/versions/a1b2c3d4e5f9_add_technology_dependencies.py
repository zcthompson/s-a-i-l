"""add technology_dependencies table (S-A-I-L technology dependencies)

Revision ID: a1b2c3d4e5f9
Revises: b7c8d9e0f1a2
Create Date: 2026-09-09

Creates the technology_dependencies table backing persistent
technology-to-technology relationships per customer
(PLAN_FEATURE_ENHANCMENTS.md — "technology dependency relationships").
Each row is one canonical relationship: source technology -> target
technology under a controlled relationship_type (validated in the service
layer; see backend/models/technology_dependency.py). UNIQUE(source_id,
target_id, relationship_type) keeps the stored relationship
non-mirrored — the canonical-orientation/deduplication invariant of the
customer intelligence graph.

Idempotent: skips creation when the table already exists.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f9"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "technology_dependencies" in inspector.get_table_names():
        return

    op.create_table(
        "technology_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
        sa.Column(
            "customer_id",
            sa.Integer(),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("customer_technologies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "target_id",
            sa.Integer(),
            sa.ForeignKey("customer_technologies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("relationship_type", sa.String(length=50), nullable=False),
        sa.Column(
            "verification_state",
            sa.String(length=20),
            nullable=False,
            server_default="verified",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("source_provenance", sa.String(length=255), nullable=True),
        sa.Column("date_observed", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "source_id", "target_id", "relationship_type",
            name="uq_technology_dependencies_src_tgt_type",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "technology_dependencies" in inspector.get_table_names():
        op.drop_table("technology_dependencies")
