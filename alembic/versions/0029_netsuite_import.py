"""Allowlisted NetSuite import staging and stable per-subscription note keys."""

import sqlalchemy as sa
from alembic import op

revision = "0029_netsuite_import"
down_revision = "0028_user_appearance"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("netsuite_imports"):
        op.create_table("netsuite_imports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False, unique=True),
            sa.Column("layout", sa.String(10), nullable=False),
            sa.Column("invoice_date", sa.Date()),
            sa.Column("imported_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            *[sa.Column(name, sa.Integer(), nullable=False) for name in (
                "total_rows", "matched_rows", "matched_accounts", "technologies_created",
                "technologies_refreshed", "technologies_associated", "risks_created", "risks_refreshed",
                "observations_created", "skipped_rows")],
            sqlite_autoincrement=True)
    if not sa.inspect(op.get_bind()).has_table("netsuite_import_rows"):
        op.create_table("netsuite_import_rows",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("import_id", sa.Integer(), sa.ForeignKey("netsuite_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="SET NULL")),
            sa.Column("source_row", sa.Integer(), nullable=False),
            *[sa.Column(name, sa.String(255)) for name in ("customer_name", "subscription_id", "product", "vendor")],
            sa.Column("quantity", sa.String(64)),
            *[sa.Column(name, sa.String(100)) for name in ("uom", "term", "term_type")],
            sa.Column("term_end", sa.Date()), sa.Column("invoice_date", sa.Date()),
            sa.Column("status", sa.String(100)), sa.Column("detail_type", sa.String(100)),
            sa.Column("notes", sa.Text()), sa.Column("matched_by", sa.String(10)),
            sa.Column("technology_id", sa.Integer(), sa.ForeignKey("customer_technologies.id", ondelete="SET NULL")),
            sa.Column("risk_note_id", sa.Integer(), sa.ForeignKey("sales_notes.id", ondelete="SET NULL")),
            sa.Column("observation_note_id", sa.Integer(), sa.ForeignKey("sales_notes.id", ondelete="SET NULL")),
            sa.Column("disposition", sa.String(30), nullable=False), sa.Column("reason", sa.String(100)),
            *[sa.Column(name, sa.Integer(), nullable=False) for name in
              ("risks_created", "risks_refreshed", "observations_created")],
            sa.UniqueConstraint("import_id", "source_row"), sqlite_autoincrement=True)
        op.create_index("ix_netsuite_import_rows_import_id", "netsuite_import_rows", ["import_id"])
        op.create_index("ix_netsuite_import_rows_customer_id", "netsuite_import_rows", ["customer_id"])
    if not sa.inspect(op.get_bind()).has_table("netsuite_import_notes"):
        op.create_table("netsuite_import_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("subscription_id", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(80), nullable=False),
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("sales_notes.id", ondelete="SET NULL")),
            sa.Column("invoice_date", sa.Date()),
            sa.UniqueConstraint("customer_id", "subscription_id", "kind"), sqlite_autoincrement=True)
        op.create_index("ix_netsuite_import_notes_customer_id", "netsuite_import_notes", ["customer_id"])


def downgrade():
    op.drop_table("netsuite_import_notes")
    op.drop_table("netsuite_import_rows")
    op.drop_table("netsuite_imports")
