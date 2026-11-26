"""Prevent SQLite ID reuse for records that other rows reference (ER-12).

Rebuild each listed parent table with AUTOINCREMENT, preserving its rows,
indexes and constraints. Each allocator starts above the table's current IDs
and every retained reference to it: declared child foreign keys (including
orphans left while SQLite did not enforce ON DELETE), task promotion sources,
applied knowledge items and audit targets. The isolated Alembic connection
must have foreign-key enforcement OFF before rebuilding parent tables; fail
before any DDL if it is enabled.

Orphaned rows are not modified here. Downgrade intentionally retains the
non-reuse invariant (the 0022/0024 pattern).
"""

import sqlalchemy as sa
from alembic import op

from backend.migration_sequences import reserve_ids

revision = "0025_prevent_record_id_reuse"
down_revision = "0024_prevent_user_id_reuse"
branch_labels = None
depends_on = None

# parent table -> [(child table, column, optional SQL filter)]
REFERENCES = {
    "account_strategy": [("strategy_contact_links", "strategy_id", None), ("strategy_note_links", "strategy_id", None),
                         ("strategy_task_links", "strategy_id", None)],
    "assessments": [("use_cases", "assessment_id", None)],
    "customer_activities": [("activity_contacts", "activity_id", None), ("task_evidence_activities", "activity_id", None)],
    "customer_contacts": [("activity_contacts", "contact_id", None), ("contact_buying_roles", "contact_id", None),
                          ("contact_notes", "contact_id", None), ("contact_technologies", "contact_id", None),
                          ("contact_use_cases", "contact_id", None), ("strategy_contact_links", "contact_id", None)],
    "customer_knowledge": [("customer_knowledge_items", "source_knowledge_id", None)],
    "customer_tasks": [("strategy_task_links", "task_id", None), ("task_evidence_activities", "task_id", None),
                       ("task_evidence_notes", "task_id", None), ("task_notification_windows", "task_id", None)],
    "customer_technologies": [("contact_technologies", "technology_id", None), ("rep_intelligence_rows", "technology_id", None),
                              ("sales_note_technologies", "technology_id", None), ("technology_dependencies", "source_id", None),
                              ("technology_dependencies", "target_id", None),
                              ("customer_tasks", "source_id", "source_type = 'eol_attention'"),
                              ("customer_knowledge_items", "applied_object_id", "applied_object_type = 'technology'")],
    "departments": [("use_cases", "department_id", None)],
    "intelligence_imports": [("partner_pipeline", "import_id", None),
                             ("audit_logs", "target_id", "action LIKE 'intelligence_import.%'")],
    "partner_pipeline": [("customer_tasks", "source_id", "source_type = 'renewal_attention'")],
    "redhat_opportunity_imports": [("redhat_opportunity_rows", "import_id", None),
                                   ("audit_logs", "target_id", "action LIKE 'redhat_opportunity.%'")],
    "rep_intelligence_imports": [("rep_intelligence_rows", "import_id", None),
                                 ("audit_logs", "target_id", "action LIKE 'rep_intelligence_import.%'")],
    "rvtools_imports": [("rvtools_hosts", "import_id", None), ("rvtools_licenses", "import_id", None),
                        ("rvtools_vms", "import_id", None), ("audit_logs", "target_id", "action LIKE 'rvtools_import.%'")],
    "sales_notes": [("contact_notes", "note_id", None), ("sales_note_technologies", "note_id", None),
                    ("sales_note_use_cases", "note_id", None), ("strategy_note_links", "note_id", None),
                    ("task_evidence_notes", "note_id", None), ("customer_tasks", "source_id", "source_type = 'note'")],
    "technology_dependencies": [("customer_knowledge_items", "applied_object_id",
                                 "applied_object_type = 'technology_dependency'")],
    "third_party_services": [("third_party_service_documents", "service_id", None),
                             ("third_party_service_use_cases", "service_id", None)],
    "use_cases": [("ai_predictions", "use_case_id", None), ("comments", "use_case_id", None),
                  ("contact_use_cases", "use_case_id", None), ("sales_note_use_cases", "use_case_id", None),
                  ("score_history", "use_case_id", None), ("third_party_service_use_cases", "use_case_id", None),
                  ("customer_knowledge_items", "applied_object_id", "applied_object_type = 'use_case'"),
                  ("audit_logs", "target_id", "action = 'score'")],
}


def _ddl(bind, table):
    return bind.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table}).scalar()


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table, refs in REFERENCES.items():
            reserve_ids(bind, table, refs)
        return
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Record ID non-reuse migration requires SQLite")
    present = [t for t in REFERENCES if _ddl(bind, t) is not None]
    rebuild = [t for t in present if "AUTOINCREMENT" not in _ddl(bind, t).upper()]
    if rebuild and bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Run the record identity migration on an isolated connection with foreign_keys=OFF")
    # Reserve the writer before calculating any allocation floor. This also
    # makes every parent-table copy/drop/rename part of one SQLite transaction.
    bind.exec_driver_sql(f'UPDATE "{present[0]}" SET id=id WHERE 0')
    inspector = sa.inspect(bind)
    has_sequence = inspector.has_table("sqlite_sequence")
    floors = {}
    for table in present:
        candidates = [bind.execute(sa.text(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')).scalar_one()]
        if has_sequence:
            candidates.append(bind.execute(sa.text(
                "SELECT COALESCE(MAX(seq), 0) FROM sqlite_sequence WHERE name=:t"), {"t": table}).scalar_one())
        for child, column, condition in REFERENCES[table]:
            if not inspector.has_table(child) or column not in {c["name"] for c in inspector.get_columns(child)}:
                continue
            where = f"typeof(\"{column}\")='integer'" + (f" AND {condition}" if condition else "")
            candidates.append(bind.execute(sa.text(
                f'SELECT COALESCE(MAX("{column}"), 0) FROM "{child}" WHERE {where}')).scalar_one())
        floors[table] = max(0, *candidates)
    for table in rebuild:
        with op.batch_alter_table(table, recreate="always", table_kwargs={"sqlite_autoincrement": True}):
            pass
    for table, floor in floors.items():
        bind.execute(sa.text("UPDATE sqlite_sequence SET seq=:seq WHERE name=:t"), {"seq": floor, "t": table})
        bind.execute(sa.text(
            "INSERT INTO sqlite_sequence(name, seq) SELECT :t, :seq "
            "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name=:t)"), {"seq": floor, "t": table})


def downgrade():
    # Do not reintroduce ID reuse or lower any allocation high-water mark.
    pass
