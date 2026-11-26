"""Retained generic intelligence batches and their per-row evidence."""

from datetime import UTC, datetime

import sqlalchemy as sa

from backend.models.intelligence_import import _wire
from backend.models.use_case import Base


class RepIntelligenceImport(Base):
    __tablename__ = "rep_intelligence_imports"
    # IDs are never reissued (ER-12): retained references must not attach to a new row.
    __table_args__ = {"sqlite_autoincrement": True}

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    file_name = sa.Column(sa.String(255), nullable=False)
    file_sha256 = sa.Column(sa.String(64), nullable=False)
    file_data = sa.Column(sa.LargeBinary, nullable=False)
    total_rows = sa.Column(sa.Integer, nullable=False)
    imported_rows = sa.Column(sa.Integer, nullable=False)
    imported_with_issues = sa.Column(sa.Integer, nullable=False)
    skipped_rows = sa.Column(sa.Integer, nullable=False)
    status = sa.Column(sa.String(30), nullable=False)
    technologies_created = sa.Column(sa.Integer, nullable=False)
    technologies_refreshed = sa.Column(sa.Integer, nullable=False)
    imported_by = sa.Column(sa.String(100), nullable=False)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return {
            "import_id": self.id,
            **{column.name: _wire(getattr(self, column.name)) for column in self.__table__.columns
               if column.name not in {"id", "file_data", "file_sha256"}},
        }


class RepIntelligenceRow(Base):
    __tablename__ = "rep_intelligence_rows"

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    import_id = sa.Column(
        sa.Integer, sa.ForeignKey("rep_intelligence_imports.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_row = sa.Column(sa.Integer, nullable=False)
    customer_name_supplied = sa.Column(sa.String(255))
    customer_id = sa.Column(sa.Integer, sa.ForeignKey("customers.id", ondelete="SET NULL"))
    technology_name_supplied = sa.Column(sa.String(255))
    hardware_software = sa.Column(sa.String(10))
    is_sale = sa.Column(sa.String(3))
    amount = sa.Column(sa.Float)
    currency = sa.Column(sa.String(3))
    vendor = sa.Column(sa.String(255))
    version = sa.Column(sa.String(255))
    quantity = sa.Column(sa.Integer)
    notes = sa.Column(sa.Text)
    technology_id = sa.Column(
        sa.Integer, sa.ForeignKey("customer_technologies.id", ondelete="SET NULL"),
    )
    status = sa.Column(sa.String(30), nullable=False)
    issues = sa.Column(sa.JSON, nullable=False, default=list)
    created_at = sa.Column(sa.DateTime, nullable=False, default=lambda: datetime.now(UTC))

    def to_dict(self):
        return {column.name: _wire(getattr(self, column.name)) for column in self.__table__.columns}
