"""add ondelete cascade to use_cases.department_id

Revision ID: 87bff5e2a7ed
Revises: bf4d3068b073
Create Date: 2026-08-17 01:58:46.779942

NOTE: SQLite requires full table recreation for FK constraint changes.
Alembic batch mode reflects the live table so columns added by other
migrations are preserved during both upgrades and downgrades.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '87bff5e2a7ed'
down_revision: Union[str, Sequence[str], None] = 'bf4d3068b073'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FK_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _set_department_fk(*, ondelete: str | None) -> None:
    """Rebuild the current table with the requested department FK action."""
    if op.get_bind().dialect.name == "postgresql":
        for fk in sa.inspect(op.get_bind()).get_foreign_keys("use_cases"):
            if fk["constrained_columns"] == ["department_id"]:
                op.drop_constraint(fk["name"], "use_cases", type_="foreignkey")
        op.create_foreign_key("fk_use_cases_department_id_departments", "use_cases", "departments",
                              ["department_id"], ["id"], ondelete=ondelete)
        return
    with op.batch_alter_table(
        "use_cases",
        recreate="auto",
        naming_convention=_FK_NAMING_CONVENTION,
    ) as batch_op:
        batch_op.drop_constraint(
            "fk_use_cases_department_id_departments",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_use_cases_department_id_departments",
            "departments",
            ["department_id"],
            ["id"],
            ondelete=ondelete,
        )


def upgrade() -> None:
    """Add cascading deletes to the department relationship."""
    _set_department_fk(ondelete="CASCADE")


def downgrade() -> None:
    """Downgrade schema — remove ondelete cascade from department_id."""
    _set_department_fk(ondelete=None)
