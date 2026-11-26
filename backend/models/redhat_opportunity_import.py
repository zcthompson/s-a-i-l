"""Retained Red Hat account opportunity reports, separate from partner deals."""

from datetime import UTC, datetime

import sqlalchemy as sa

from backend.models.use_case import Base


class RedHatOpportunityImport(Base):
    __tablename__ = "redhat_opportunity_imports"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True)
    file_name = sa.Column(sa.String(255), nullable=False)
    file_sha256 = sa.Column(sa.String(64), nullable=False)
    file_data = sa.Column(sa.LargeBinary, nullable=False)
    imported_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))
    total_rows = sa.Column(sa.Integer, nullable=False)
    matched_rows = sa.Column(sa.Integer, nullable=False)
    matched_accounts = sa.Column(sa.Integer, nullable=False)
    unmatched_json = sa.Column(sa.Text, nullable=False)


class RedHatOpportunityRow(Base):
    __tablename__ = "redhat_opportunity_rows"

    id = sa.Column(sa.Integer, primary_key=True)
    import_id = sa.Column(sa.Integer, sa.ForeignKey("redhat_opportunity_imports.id", ondelete="CASCADE"),
                          nullable=False, index=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    source_row = sa.Column(sa.Integer, nullable=False)
    source_account = sa.Column(sa.String(255), nullable=False)
    redhat_owner = sa.Column(sa.String(255))
    matched_by = sa.Column(sa.String(10), nullable=False)
    fields_json = sa.Column(sa.Text, nullable=False)
