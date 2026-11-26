"""Retain source-labelled Red Hat account opportunity observations."""

import sqlalchemy as sa
from alembic import op

revision = "0023_redhat_opportunity_import"
down_revision = "0022_prevent_customer_id_reuse"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("redhat_opportunity_imports"):
        op.create_table("redhat_opportunity_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("file_data", sa.LargeBinary(), nullable=False),
        sa.Column("imported_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("matched_rows", sa.Integer(), nullable=False),
        sa.Column("matched_accounts", sa.Integer(), nullable=False),
        sa.Column("unmatched_json", sa.Text(), nullable=False))
    if not inspector.has_table("redhat_opportunity_rows"):
        op.create_table("redhat_opportunity_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("import_id", sa.Integer(), sa.ForeignKey("redhat_opportunity_imports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.Column("source_account", sa.String(255), nullable=False),
        sa.Column("redhat_owner", sa.String(255)),
        sa.Column("matched_by", sa.String(10), nullable=False),
        sa.Column("fields_json", sa.Text(), nullable=False))
    inspector = sa.inspect(op.get_bind())
    required = {
        "redhat_opportunity_imports": {"id", "file_name", "file_sha256", "file_data", "imported_by",
                                       "created_at", "total_rows", "matched_rows", "matched_accounts", "unmatched_json"},
        "redhat_opportunity_rows": {"id", "import_id", "customer_id", "source_row", "source_account",
                                    "redhat_owner", "matched_by", "fields_json"},
    }
    for table, expected in required.items():
        if not expected <= {column["name"] for column in inspector.get_columns(table)}:
            raise RuntimeError(f"Existing {table} table is missing required columns")
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("redhat_opportunity_rows")}
    if "ix_redhat_opportunity_rows_import_id" not in indexes:
        op.create_index("ix_redhat_opportunity_rows_import_id", "redhat_opportunity_rows", ["import_id"])
    if "ix_redhat_opportunity_rows_customer_id" not in indexes:
        op.create_index("ix_redhat_opportunity_rows_customer_id", "redhat_opportunity_rows", ["customer_id"])


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("redhat_opportunity_rows"):
        indexes = {index["name"] for index in inspector.get_indexes("redhat_opportunity_rows")}
        for name in ("ix_redhat_opportunity_rows_customer_id", "ix_redhat_opportunity_rows_import_id"):
            if name in indexes:
                op.drop_index(name, table_name="redhat_opportunity_rows")
        op.drop_table("redhat_opportunity_rows")
    if inspector.has_table("redhat_opportunity_imports"):
        op.drop_table("redhat_opportunity_imports")
