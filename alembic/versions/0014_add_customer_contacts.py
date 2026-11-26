"""Add customer-owned contacts, observed buying roles, and relationship links."""

import sqlalchemy as sa
from alembic import op

revision = "0014_add_customer_contacts"
down_revision = "0013_add_customer_sales_structure"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("customer_contacts"):
        op.create_table(
            "customer_contacts",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("customer_id", sa.Integer, sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("title", sa.String(255)),
            sa.Column("email", sa.String(255)),
            sa.Column("phone", sa.String(50)),
            sa.Column("department", sa.String(100)),
            sa.Column("persona", sa.String(50)),
            sa.Column("source", sa.String(255)),
            sa.Column("observation_date", sa.Date),
            sa.Column("verification_state", sa.String(20), nullable=False),
            sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("archived_at", sa.DateTime),
            sa.Column("created_by", sa.String(255)),
            sa.Column("updated_by", sa.String(255)),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
        )
    if not inspector.has_table("contact_buying_roles"):
        op.create_table(
            "contact_buying_roles",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("contact_id", sa.Integer, sa.ForeignKey("customer_contacts.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(50), nullable=False),
            sa.Column("source", sa.String(255)),
            sa.Column("observation_date", sa.Date),
            sa.Column("verification_state", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("contact_id", "role", name="uq_contact_buying_role"),
        )
    for table, key, target in (
        ("contact_notes", "note_id", "sales_notes.id"),
        ("contact_use_cases", "use_case_id", "use_cases.id"),
        ("contact_technologies", "technology_id", "customer_technologies.id"),
    ):
        if not inspector.has_table(table):
            op.create_table(
                table,
                sa.Column("contact_id", sa.Integer, sa.ForeignKey("customer_contacts.id", ondelete="CASCADE"), primary_key=True, nullable=False),
                sa.Column(key, sa.Integer, sa.ForeignKey(target, ondelete="CASCADE"), primary_key=True, nullable=False),
            )
    for table, column in (("customer_contacts", "customer_id"),
                          ("contact_buying_roles", "contact_id"),
                          ("contact_notes", "contact_id"),
                          ("contact_use_cases", "contact_id"),
                          ("contact_technologies", "contact_id")):
        name = f"ix_{table}_{column}"
        if name not in {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}:
            op.create_index(name, table, [column])


def downgrade():
    for table, column in (("contact_technologies", "contact_id"),
                          ("contact_use_cases", "contact_id"),
                          ("contact_notes", "contact_id"),
                          ("contact_buying_roles", "contact_id"),
                          ("customer_contacts", "customer_id")):
        inspector = sa.inspect(op.get_bind())
        if inspector.has_table(table):
            name = f"ix_{table}_{column}"
            if name in {index["name"] for index in inspector.get_indexes(table)}:
                op.drop_index(name, table_name=table)
            op.drop_table(table)
