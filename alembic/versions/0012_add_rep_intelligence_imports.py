"""Add retained generic intelligence imports and per-row issues."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_add_rep_intelligence_imports"
down_revision: Union[str, None] = "0011_add_rvtools_imports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("rep_intelligence_imports"):
        op.create_table(
            "rep_intelligence_imports",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("file_data", sa.LargeBinary, nullable=False),
            sa.Column("total_rows", sa.Integer, nullable=False),
            sa.Column("imported_rows", sa.Integer, nullable=False),
            sa.Column("imported_with_issues", sa.Integer, nullable=False),
            sa.Column("skipped_rows", sa.Integer, nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("technologies_created", sa.Integer, nullable=False),
            sa.Column("technologies_refreshed", sa.Integer, nullable=False),
            sa.Column("imported_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
    if not inspector.has_table("rep_intelligence_rows"):
        op.create_table(
            "rep_intelligence_rows",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer,
                      sa.ForeignKey("rep_intelligence_imports.id", ondelete="CASCADE"),
                      nullable=False),
            sa.Column("source_row", sa.Integer, nullable=False),
            sa.Column("customer_name_supplied", sa.String(255)),
            sa.Column("customer_id", sa.Integer,
                      sa.ForeignKey("customers.id", ondelete="SET NULL")),
            sa.Column("technology_name_supplied", sa.String(255)),
            sa.Column("hardware_software", sa.String(10)),
            sa.Column("is_sale", sa.String(3)),
            sa.Column("amount", sa.Float),
            sa.Column("currency", sa.String(3)),
            sa.Column("vendor", sa.String(255)),
            sa.Column("version", sa.String(255)),
            sa.Column("quantity", sa.Integer),
            sa.Column("notes", sa.Text),
            sa.Column("technology_id", sa.Integer,
                      sa.ForeignKey("customer_technologies.id", ondelete="SET NULL")),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("issues", sa.JSON, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
    inspector = sa.inspect(op.get_bind())
    index_name = "ix_rep_intelligence_rows_import_id"
    if index_name not in {index["name"] for index in inspector.get_indexes("rep_intelligence_rows")}:
        op.create_index(index_name, "rep_intelligence_rows", ["import_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("rep_intelligence_rows", "rep_intelligence_imports"):
        if inspector.has_table(table):
            op.drop_table(table)
