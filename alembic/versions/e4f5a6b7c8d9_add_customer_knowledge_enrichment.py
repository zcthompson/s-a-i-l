"""Customer knowledge enrichment: knowledge_category, enrichment status columns, customer_knowledge_items table.


- ``customer_knowledge.knowledge_category`` (controlled vocabulary;
  user-authoritative at upload, LLM-suggested when absent).
- LLM enrichment status columns on ``customer_knowledge`` (enrichment is
  tracked SEPARATELY from Docling processing — plan item 16).
- New ``customer_knowledge_items`` table: durable, traceable record of
  LLM-extracted intelligence items (provenance explicit/derived/suggested,
  evidence, application pointers to the domain objects they were applied to).

Idempotent in the established repository pattern: each addition checks
for pre-existing state (legacy DBs created before this migration).
"""

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── customer_knowledge: knowledge_category ────────────────────────
    bind = op.get_bind()
    insp = sa.inspect(bind)
    ck_cols = {c["name"] for c in insp.get_columns("customer_knowledge")}

    if "knowledge_category" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("knowledge_category", sa.String(60), nullable=True),
        )
        op.create_index(
            "ix_customer_knowledge_knowledge_category",
            "customer_knowledge",
            ["knowledge_category"],
        )

    # ── customer_knowledge: enrichment status columns ─────────────────
    if "enrichment_status" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("enrichment_status", sa.String(20), nullable=False, server_default="NOT_RUN"),
        )
    if "enrichment_error" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("enrichment_error", sa.Text(), nullable=True),
        )
    if "enrichment_error_kind" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("enrichment_error_kind", sa.String(50), nullable=True),
        )
    if "enrichment_model" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("enrichment_model", sa.String(100), nullable=True),
        )
    if "enrichment_time_seconds" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("enrichment_time_seconds", sa.Float(), nullable=True),
        )
    if "enriched_at" not in ck_cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("enriched_at", sa.DateTime(), nullable=True),
        )

    # ── customer_knowledge_items table ────────────────────────────────
    if "customer_knowledge_items" not in insp.get_table_names():
        op.create_table(
            "customer_knowledge_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=False),
            sa.Column("source_knowledge_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(50), nullable=False),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("provenance", sa.String(20), nullable=False, server_default="derived"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("source_reference", sa.String(500), nullable=True),
            sa.Column("applied_status", sa.String(20), nullable=True),
            sa.Column("applied_object_type", sa.String(50), nullable=True),
            sa.Column("applied_object_id", sa.Integer(), nullable=True),
            sa.Column("enrichment_model", sa.String(100), nullable=True),
            sa.Column("extracted_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["source_knowledge_id"], ["customer_knowledge.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_customer_knowledge_items_customer_id", "customer_knowledge_items", ["customer_id"])
        op.create_index(
            "ix_customer_knowledge_items_source_knowledge_id",
            "customer_knowledge_items",
            ["source_knowledge_id"],
        )


def downgrade() -> None:
    op.drop_table("customer_knowledge_items")
    op.drop_column("customer_knowledge", "enriched_at")
    op.drop_column("customer_knowledge", "enrichment_time_seconds")
    op.drop_column("customer_knowledge", "enrichment_model")
    op.drop_column("customer_knowledge", "enrichment_error_kind")
    op.drop_column("customer_knowledge", "enrichment_error")
    op.drop_column("customer_knowledge", "enrichment_status")
    op.drop_index("ix_customer_knowledge_knowledge_category", table_name="customer_knowledge")
    op.drop_column("customer_knowledge", "knowledge_category")
