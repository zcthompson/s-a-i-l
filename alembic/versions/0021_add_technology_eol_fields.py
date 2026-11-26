"""Add nullable, independently sourced technology end-of-support facts.

Upgrade preserves existing technology rows; unknown dates and sources stay NULL.
Downgrade discards these two facts. Validate 0020->0021 and a guarded downgrade
on a disposable DB: full-chain data roundtrips are not supported because the
pre-existing c5d6e7f8a9b0 downgrade drops customer_technologies.
"""

import sqlalchemy as sa
from alembic import op

revision = "0021_add_technology_eol_fields"
down_revision = "0020_add_saved_views"
branch_labels = None
depends_on = None


def upgrade():
    columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("customer_technologies")}
    for name, kind in (("end_of_support_date", sa.Date()), ("eol_source", sa.String(255))):
        if name not in columns:
            op.add_column("customer_technologies", sa.Column(name, kind, nullable=True))


def downgrade():
    columns = {col["name"] for col in sa.inspect(op.get_bind()).get_columns("customer_technologies")}
    drop = [name for name in ("eol_source", "end_of_support_date") if name in columns]
    if drop:
        with op.batch_alter_table("customer_technologies") as batch:
            for name in drop:
                batch.drop_column(name)
