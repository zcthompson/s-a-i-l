"""Retained intelligence-import batches and matched partner pipeline rows."""

from datetime import UTC, date, datetime

import sqlalchemy as sa

from backend.models.use_case import Base


def _wire(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=UTC).isoformat() if value.tzinfo is None else value.isoformat()
    return value.isoformat() if isinstance(value, date) else value


class IntelligenceImport(Base):
    __tablename__ = "intelligence_imports"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    file_name = sa.Column(sa.String(255), nullable=False)
    file_sha256 = sa.Column(sa.String(64), nullable=False)
    file_data = sa.Column(sa.LargeBinary, nullable=False)
    total_rows = sa.Column(sa.Integer, nullable=False)
    matched_accounts = sa.Column(sa.Integer, nullable=False)
    matched_rows = sa.Column(sa.Integer, nullable=False)
    unmatched_accounts = sa.Column(sa.Integer, nullable=False)
    unmatched_report = sa.Column(sa.Text, nullable=False)
    # JSON list of unreadable amount cells on imported rows
    # [{source_row, customer_id, column, value}] — migration 0019; NULL on
    # batches imported before it (read as no issues).
    amount_issues = sa.Column(sa.Text, nullable=True)
    imported_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return {
            "import_id": self.id,
            **{name: _wire(getattr(self, name)) for name in (
                "file_name", "created_at", "imported_by", "total_rows",
                "matched_accounts", "matched_rows", "unmatched_accounts",
            )},
            # Rows not imported (no matching customer name or alias) — the
            # import warning count.
            "skipped_rows": self.total_rows - self.matched_rows,
        }


class PartnerPipeline(Base):
    __tablename__ = "partner_pipeline"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    import_id = sa.Column(
        sa.Integer, sa.ForeignKey("intelligence_imports.id", ondelete="CASCADE"), nullable=False,
    )
    customer_id = sa.Column(
        sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False,
    )
    customer_account_name = sa.Column(sa.String(255), nullable=False)
    opportunity_name = sa.Column(sa.String(255))
    opportunity_number = sa.Column(sa.String(100))
    opp_stage = sa.Column(sa.String(50))
    forecast_category = sa.Column(sa.String(50))
    net_new_vs_renewal = sa.Column(sa.String(30))
    route_to_market = sa.Column(sa.String(50))
    opportunity_channel = sa.Column(sa.String(50))
    partner_account = sa.Column(sa.String(255))
    partner_tier = sa.Column(sa.String(50))
    product_offering_group = sa.Column(sa.String(50))
    product_sku = sa.Column(sa.String(100))
    product_description = sa.Column(sa.Text)
    est_acv_usd = sa.Column(sa.Float)
    est_tcv_usd = sa.Column(sa.Float)
    currency_code = sa.Column(sa.String(10))
    close_date = sa.Column(sa.Date)
    contract_start_date = sa.Column(sa.Date)
    contract_end_date = sa.Column(sa.Date)
    current_contract_start_date = sa.Column(sa.Date)
    current_contract_end_date = sa.Column(sa.Date)
    fiscal_quarter = sa.Column(sa.String(20))
    growth_risk_flag = sa.Column(sa.String(10))
    deal_reg_approval_status = sa.Column(sa.String(50))
    opp_create_date = sa.Column(sa.Date)
    source_row = sa.Column(sa.Integer)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return {column.name: _wire(getattr(self, column.name)) for column in self.__table__.columns}
