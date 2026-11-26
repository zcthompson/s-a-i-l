"""add third_party_services + documents + use-case junction (S-A-I-L Sales)

Revision ID: f3a4b5c6d7e8
Revises: e4f5a6b7c8d9
Create Date: 2026-09-14

Creates the third_party_services table, the
third_party_service_documents table (store-first document tracking for
POs/SOWs), and the third_party_service_use_cases junction table backing the
S-A-I-L Third-Party Professional Services feature. Pure additions — no batch ops required,
existing databases upgrade without data loss. Idempotent: each
table is created only if absent.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "third_party_services" not in tables:
        op.create_table(
            "third_party_services",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
            sa.Column(
                "customer_id",
                sa.Integer(),
                sa.ForeignKey("customers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("vendor_name", sa.String(length=255), nullable=False),
            sa.Column("service_category", sa.String(length=50), nullable=False),
            sa.Column(
                "engagement_status",
                sa.String(length=20),
                nullable=False,
                server_default="active",
            ),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("sow_reference", sa.String(length=255), nullable=True),
            sa.Column("contract_reference", sa.String(length=255), nullable=True),
            sa.Column("started_on", sa.Date(), nullable=True),
            sa.Column("ended_on", sa.Date(), nullable=True),
            sa.Column("billing_model", sa.String(length=20), nullable=True),
            sa.Column("fee_amount", sa.Float(), nullable=True),
            sa.Column(
                "verification_state",
                sa.String(length=20),
                nullable=False,
                server_default="verified",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(length=255), nullable=True),
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
        )

    if "third_party_service_documents" not in tables:
        op.create_table(
            "third_party_service_documents",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False, index=True),
            sa.Column(
                "service_id",
                sa.Integer(),
                sa.ForeignKey("third_party_services.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "customer_id",
                sa.Integer(),
                sa.ForeignKey("customers.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("document_type", sa.String(length=30), nullable=False),
            sa.Column("file_name", sa.String(length=255), nullable=False),
            sa.Column("file_data", sa.LargeBinary(), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("uploaded_by", sa.String(length=255), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )

    if "third_party_service_use_cases" not in tables:
        op.create_table(
            "third_party_service_use_cases",
            sa.Column(
                "service_id",
                sa.Integer(),
                sa.ForeignKey("third_party_services.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
            sa.Column(
                "use_case_id",
                sa.Integer(),
                sa.ForeignKey("use_cases.id", ondelete="CASCADE"),
                primary_key=True,
                nullable=False,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "third_party_service_use_cases" in tables:
        op.drop_table("third_party_service_use_cases")
    if "third_party_service_documents" in tables:
        op.drop_table("third_party_service_documents")
    if "third_party_services" in tables:
        op.drop_table("third_party_services")
