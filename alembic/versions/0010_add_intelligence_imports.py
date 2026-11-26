"""Add retained intelligence imports and matched partner pipeline rows."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_intelligence_imports"
down_revision: Union[str, None] = "0009_add_auto_linked_flag_to_inside_sales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("intelligence_imports"):
        op.create_table(
            "intelligence_imports",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("file_name", sa.String(255), nullable=False),
            sa.Column("file_sha256", sa.String(64), nullable=False),
            sa.Column("file_data", sa.LargeBinary, nullable=False),
            sa.Column("total_rows", sa.Integer, nullable=False),
            sa.Column("matched_accounts", sa.Integer, nullable=False),
            sa.Column("matched_rows", sa.Integer, nullable=False),
            sa.Column("unmatched_accounts", sa.Integer, nullable=False),
            sa.Column("unmatched_report", sa.Text, nullable=False),
            sa.Column("imported_by", sa.String(100), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )
    if not inspector.has_table("partner_pipeline"):
        op.create_table(
            "partner_pipeline",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("import_id", sa.Integer,
                      sa.ForeignKey("intelligence_imports.id", ondelete="CASCADE"), nullable=False),
            sa.Column("customer_id", sa.Integer,
                      sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("customer_account_name", sa.String(255), nullable=False),
            sa.Column("opportunity_name", sa.String(255)),
            sa.Column("opportunity_number", sa.String(100)),
            sa.Column("opp_stage", sa.String(50)),
            sa.Column("forecast_category", sa.String(50)),
            sa.Column("net_new_vs_renewal", sa.String(30)),
            sa.Column("route_to_market", sa.String(50)),
            sa.Column("opportunity_channel", sa.String(50)),
            sa.Column("partner_account", sa.String(255)),
            sa.Column("partner_tier", sa.String(50)),
            sa.Column("product_offering_group", sa.String(50)),
            sa.Column("product_sku", sa.String(100)),
            sa.Column("product_description", sa.Text),
            sa.Column("est_acv_usd", sa.Float),
            sa.Column("est_tcv_usd", sa.Float),
            sa.Column("currency_code", sa.String(10)),
            sa.Column("close_date", sa.Date),
            sa.Column("contract_start_date", sa.Date),
            sa.Column("contract_end_date", sa.Date),
            sa.Column("current_contract_start_date", sa.Date),
            sa.Column("current_contract_end_date", sa.Date),
            sa.Column("fiscal_quarter", sa.String(20)),
            sa.Column("growth_risk_flag", sa.String(10)),
            sa.Column("deal_reg_approval_status", sa.String(50)),
            sa.Column("opp_create_date", sa.Date),
            sa.Column("source_row", sa.Integer),
            sa.Column("created_at", sa.DateTime, nullable=False),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("partner_pipeline", "intelligence_imports"):
        if inspector.has_table(table):
            op.drop_table(table)
