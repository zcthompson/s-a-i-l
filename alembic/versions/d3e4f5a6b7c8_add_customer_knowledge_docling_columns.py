"""Customer Knowledge Docling normalization columns + legacy data backfill.

Revision ID: d3e4f5a6b7c8
Revises: a1b2c3d4e5f9

Adds the Docling document-normalization layer to the existing
``customer_knowledge`` table:

- original_*      : original document provenance (retained source artifact)
- normalized_*    : canonical Markdown representation (Docling output or
                     the in-process Markdown short-circuit)
- processing_*    : UPLOADED -> PROCESSING -> READY | FAILED lifecycle +
                     failure diagnostics
- processor*      : which processor produced the normalized content

Legacy data backfill (safe, idempotent — no data destruction):
  - rows with ``processed = 1`` (the legacy "text was extracted" flag) get
    ``processing_status = 'READY'`` — their ``extracted_text`` is the
      canonical content until a reprocess produces normalized Markdown;
      consumers fall back to ``extracted_text`` when
      ``normalized_content`` is NULL.
  - rows with ``processed = 0`` get ``processing_status = 'UPLOADED'`` —
      no processing has succeeded yet; they are reprocessable.
  - every row gets ``original_content_type`` (extension-derived),
    ``original_storage_path`` (the in-DB location descriptor), and
    ``normalized_format = 'markdown'`` (the canonical target format).

Idempotent: missing columns are added, backfills are guarded by
``processing_status IS NULL`` so a re-run is a no-op.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "a1b2c3d4e5f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("customer_knowledge"):
        return
    cols = {c["name"] for c in inspector.get_columns("customer_knowledge")}

    if "original_content_type" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("original_content_type", sa.String(100), nullable=True),
        )
    if "original_storage_path" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("original_storage_path", sa.String(255), nullable=True),
        )
    if "normalized_format" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("normalized_format", sa.String(20), nullable=True),
        )
    if "normalized_content" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("normalized_content", sa.Text(), nullable=True),
        )
    if "processing_status" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column(
                "processing_status",
                sa.String(20),
                nullable=False,
                server_default="UPLOADED",
            ),
        )
    if "processing_error" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("processing_error", sa.Text(), nullable=True),
        )
    if "processing_error_kind" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("processing_error_kind", sa.String(50), nullable=True),
        )
    if "processor" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("processor", sa.String(50), nullable=True),
        )
    if "processor_version" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("processor_version", sa.String(50), nullable=True),
        )
    if "processing_time_seconds" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("processing_time_seconds", sa.Float(), nullable=True),
        )
    if "processed_at" not in cols:
        op.add_column(
            "customer_knowledge",
            sa.Column("processed_at", sa.DateTime(), nullable=True),
        )

    # ------------------------------------------------------------------
    # Legacy data backfill (idempotent: only rows without a status yet).
    # processed=1 rows already have usable extracted_text; they are READY
    # (consumers fall back to extracted_text when normalized_content is
    # NULL). processed=0 rows are UPLOADED and reprocessable.
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            "UPDATE customer_knowledge SET processing_status = 'READY' "
            "WHERE processing_status IS NULL AND processed = 1"
        )
    )
    op.execute(
        sa.text(
            "UPDATE customer_knowledge SET processing_status = 'UPLOADED' "
            "WHERE processing_status IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE customer_knowledge SET normalized_format = 'markdown' "
            "WHERE normalized_format IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE customer_knowledge SET original_storage_path = "
            "'database:customer_knowledge.file_data:' || CAST(id AS TEXT) "
            "WHERE original_storage_path IS NULL"
        )
    )
    # Extension-derived original_content_type for legacy rows (deterministic
    # mapping for the types S-A-I-L accepts).
    _EXT_TYPE_MAP = [
        ("pdf", "application/pdf"),
        ("csv", "text/csv"),
        ("tsv", "text/tab-separated-values"),
        ("txt", "text/plain"),
        ("md", "text/markdown"),
        ("markdown", "text/markdown"),
        ("doc", "application/msword"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("xls", "application/vnd.ms-excel"),
        ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("ppt", "application/vnd.ms-powerpoint"),
        ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("html", "text/html"),
        ("htm", "text/html"),
        ("png", "image/png"),
        ("jpg", "image/jpeg"),
        ("jpeg", "image/jpeg"),
    ]
    for ext, mime in _EXT_TYPE_MAP:
        op.execute(
            sa.text(
                "UPDATE customer_knowledge SET original_content_type = :mime "
                "WHERE original_content_type IS NULL "
                "AND file_name LIKE :pattern"
            ).bindparams(mime=mime, pattern=f"%.{ext}")
        )


def downgrade() -> None:
    # Destructive on SQLite (loses the normalization layer for existing
    # rows); the columns are additive and nullable (processing_status has a
    # server_default), so pre-migration code keeps working.
    pass
