"""Add personal saved portfolio views.

Downgrading drops saved user preferences, including populated views.
"""

import warnings

import sqlalchemy as sa
from alembic import op

revision = "0020_add_saved_views"
down_revision = "0019_add_import_amount_issues"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("saved_views"):
        op.create_table(
            "saved_views",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.Text, nullable=False),
            sa.Column("name_norm", sa.Text, nullable=False),
            sa.Column("surface", sa.Text, nullable=False),
            sa.Column("params", sa.JSON, nullable=False),
            sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.current_timestamp()),
            sa.UniqueConstraint("user_id", "surface", "name_norm", name="uq_saved_view_owner_surface_name"),
        )
        op.create_index("ix_saved_views_user_id", "saved_views", ["user_id"])


def downgrade():
    if sa.inspect(op.get_bind()).has_table("saved_views"):
        if op.get_bind().execute(sa.text("SELECT 1 FROM saved_views LIMIT 1")).first():
            warnings.warn("Dropping populated saved_views; saved user preferences will be lost", stacklevel=2)
        op.drop_index("ix_saved_views_user_id", table_name="saved_views")
        op.drop_table("saved_views")
