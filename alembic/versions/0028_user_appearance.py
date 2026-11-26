"""Persist account appearance across browsers."""
import sqlalchemy as sa
from alembic import op

revision = "0028_user_appearance"
down_revision = "0027_deal_vendor_evidence"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("user_appearance"):
        op.create_table("user_appearance",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("theme", sa.String(5), nullable=False),
            sa.Column("font_size", sa.String(6), nullable=False))


def downgrade():
    op.drop_table("user_appearance")
