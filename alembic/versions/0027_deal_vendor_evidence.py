"""Retained vendor-opportunity evidence for rep-maintained deals."""
import sqlalchemy as sa
from alembic import op

revision = '0027_deal_vendor_evidence'
down_revision = '0026_add_deals'
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table('deal_vendor_evidence'):
        op.create_table('deal_vendor_evidence',
            sa.Column('deal_id', sa.Integer(), sa.ForeignKey('deals.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('import_id', sa.Integer(), primary_key=True),
            sa.Column('opportunity_number', sa.String(255), primary_key=True))


def downgrade():
    op.drop_table('deal_vendor_evidence')
