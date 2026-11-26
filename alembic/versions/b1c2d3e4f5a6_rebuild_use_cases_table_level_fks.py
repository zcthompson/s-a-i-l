"""rebuild use_cases with table-level foreign keys

Recreates ``use_cases`` so that the ``assessment_id`` foreign key is
declared as a table-level ``FOREIGN KEY`` clause instead of an inline
``REFERENCES`` clause on the column.

Background
----------
Migration a1b2c3d4e5f7 added the column with raw
``ALTER TABLE ... ADD COLUMN assessment_id INTEGER REFERENCES
assessments(id) ON DELETE SET NULL``.  SQLite treats the two forms
identically at runtime, but SQLAlchemy's SQLite introspector only
reads ``ON DELETE``/``ON UPDATE`` options from table-level ``FOREIGN
KEY`` clauses in the stored DDL — inline ``REFERENCES`` options come
back with empty ``options``.  As a result ``alembic check`` reported a
phantom remove_fk/add_fk diff on every run.

This migration rebuilds the table with all three foreign keys rendered
as table-level clauses.  No column definitions, data, or FK semantics
change.

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f7
Create Date: 2026-08-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The rebuilt table includes all 28 columns known at this point in the full
# chain.  On a fresh forward upgrade, an earlier legacy rebuild has removed
# the four technology columns; on downgrade from head they are still present.
_COLUMNS = """
    id INTEGER NOT NULL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    customer_id INTEGER,
    department VARCHAR(100),
    department_id INTEGER,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    created_at DATETIME,
    updated_at DATETIME,
    goals JSON,
    challenges JSON,
    pain_points JSON,
    impact_category VARCHAR(50),
    impact_description TEXT,
    estimated_savings FLOAT,
    estimated_revenue FLOAT,
    timeline_estimate VARCHAR(50),
    scores JSON,
    overall_score FLOAT,
    scored_at DATETIME,
    score_history JSON,
    created_by VARCHAR(100),
    updated_by VARCHAR(100),
    assessment_id INTEGER,
    tech_stack JSON,
    devices JSON,
    software JSON,
    vendor VARCHAR(255)
"""

_COPY_COLUMNS = (
    "id",
    "title",
    "description",
    "customer_id",
    "department",
    "department_id",
    "status",
    "created_at",
    "updated_at",
    "goals",
    "challenges",
    "pain_points",
    "impact_category",
    "impact_description",
    "estimated_savings",
    "estimated_revenue",
    "timeline_estimate",
    "scores",
    "overall_score",
    "scored_at",
    "score_history",
    "created_by",
    "updated_by",
    "assessment_id",
    "tech_stack",
    "devices",
    "software",
    "vendor",
)

_INDEXES = [
    "CREATE INDEX ix_use_cases_id ON use_cases(id)",
    "CREATE INDEX ix_use_cases_customer_id ON use_cases(customer_id)",
    "CREATE INDEX ix_use_cases_department_id ON use_cases(department_id)",
    "CREATE INDEX ix_use_cases_assessment_id ON use_cases(assessment_id)",
]

# Target state: all three FKs as table-level clauses.
_TABLE_LEVEL_FKS = (
    "    , FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE\n"
    "    , FOREIGN KEY(department_id) REFERENCES departments(id) ON DELETE CASCADE\n"
    "    , FOREIGN KEY(assessment_id) REFERENCES assessments(id) ON DELETE SET NULL"
)

# Previous state (for downgrade): inline REFERENCES on assessment_id.
_PREVIOUS_FKS = (
    "    , FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE\n"
    "    , FOREIGN KEY(department_id) REFERENCES departments(id) ON DELETE CASCADE"
)
_PREVIOUS_COLUMNS = _COLUMNS.replace(
    "    assessment_id INTEGER\n",
    "    assessment_id INTEGER REFERENCES assessments(id) ON DELETE SET NULL\n",
)


def _rebuild(columns_ddl: str, fk_clauses: str) -> None:
    """Rebuild use_cases: create sibling table, copy rows, swap names.

    The rebuild renames use_cases_new -> use_cases.  No child table
    references the name "use_cases_new", and dropping the old table
    does not delete rows row-wise, so default foreign-key enforcement
    is safe throughout (no PRAGMA toggling needed).
    """
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return  # PostgreSQL already stores these FKs as table constraints.
    current_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("use_cases")
    }
    columns_sql = ", ".join(column for column in _COPY_COLUMNS if column in current_columns)

    op.execute(f"CREATE TABLE use_cases_new ({columns_ddl}{fk_clauses})")
    op.execute(
        f"INSERT INTO use_cases_new ({columns_sql}) "
        f"SELECT {columns_sql} FROM use_cases"
    )
    op.execute("DROP TABLE use_cases")
    op.execute("ALTER TABLE use_cases_new RENAME TO use_cases")
    for idx in _INDEXES:
        op.execute(idx)
    # Sanity: no dangling foreign key references after the rebuild.
    violations = bind.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise RuntimeError(f"Foreign key violations after rebuild: {violations}")


def upgrade() -> None:
    _rebuild(_COLUMNS, _TABLE_LEVEL_FKS)


def downgrade() -> None:
    _rebuild(_PREVIOUS_COLUMNS, _PREVIOUS_FKS)
