"""Allowlisted NetSuite staging and stable note identities; uploaded bytes excluded."""

from datetime import UTC, datetime

import sqlalchemy as sa

from backend.models.use_case import Base


class NetSuiteImport(Base):
    __tablename__ = "netsuite_imports"
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True)
    file_name = sa.Column(sa.String(255), nullable=False)
    file_sha256 = sa.Column(sa.String(64), nullable=False, unique=True)
    layout = sa.Column(sa.String(10), nullable=False)
    invoice_date = sa.Column(sa.Date)
    imported_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))
    status = sa.Column(sa.String(30), nullable=False, default="complete")
    total_rows = sa.Column(sa.Integer, nullable=False, default=0)
    matched_rows = sa.Column(sa.Integer, nullable=False, default=0)
    matched_accounts = sa.Column(sa.Integer, nullable=False, default=0)
    technologies_created = sa.Column(sa.Integer, nullable=False, default=0)
    technologies_refreshed = sa.Column(sa.Integer, nullable=False, default=0)
    technologies_associated = sa.Column(sa.Integer, nullable=False, default=0)
    risks_created = sa.Column(sa.Integer, nullable=False, default=0)
    risks_refreshed = sa.Column(sa.Integer, nullable=False, default=0)
    observations_created = sa.Column(sa.Integer, nullable=False, default=0)
    skipped_rows = sa.Column(sa.Integer, nullable=False, default=0)


class NetSuiteImportRow(Base):
    __tablename__ = "netsuite_import_rows"
    __table_args__ = (sa.UniqueConstraint("import_id", "source_row"), {"sqlite_autoincrement": True})

    id = sa.Column(sa.Integer, primary_key=True)
    import_id = sa.Column(sa.Integer, sa.ForeignKey("netsuite_imports.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="SET NULL"), index=True)
    source_row = sa.Column(sa.Integer, nullable=False)
    customer_name = sa.Column(sa.String(255))
    subscription_id = sa.Column(sa.String(255))
    product = sa.Column(sa.String(255))
    vendor = sa.Column(sa.String(255))
    quantity = sa.Column(sa.String(64))
    uom = sa.Column(sa.String(100))
    term = sa.Column(sa.String(100))
    term_type = sa.Column(sa.String(100))
    term_end = sa.Column(sa.Date)
    invoice_date = sa.Column(sa.Date)
    status = sa.Column(sa.String(100))
    detail_type = sa.Column(sa.String(100))
    notes = sa.Column(sa.Text)
    matched_by = sa.Column(sa.String(10))
    technology_id = sa.Column(sa.Integer, sa.ForeignKey("customer_technologies.id", ondelete="SET NULL"))
    risk_note_id = sa.Column(sa.Integer, sa.ForeignKey("sales_notes.id", ondelete="SET NULL"))
    observation_note_id = sa.Column(sa.Integer, sa.ForeignKey("sales_notes.id", ondelete="SET NULL"))
    disposition = sa.Column(sa.String(30), nullable=False, default="pending")
    reason = sa.Column(sa.String(100))
    risks_created = sa.Column(sa.Integer, nullable=False, default=0)
    risks_refreshed = sa.Column(sa.Integer, nullable=False, default=0)
    observations_created = sa.Column(sa.Integer, nullable=False, default=0)


class NetSuiteImportNote(Base):
    """A subscription may have several distinct risks and original observations."""

    __tablename__ = "netsuite_import_notes"
    __table_args__ = (sa.UniqueConstraint("customer_id", "subscription_id", "kind"), {"sqlite_autoincrement": True})

    id = sa.Column(sa.Integer, primary_key=True)
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id = sa.Column(sa.String(255), nullable=False)
    kind = sa.Column(sa.String(80), nullable=False)
    note_id = sa.Column(sa.Integer, sa.ForeignKey("sales_notes.id", ondelete="SET NULL"))
    invoice_date = sa.Column(sa.Date)
