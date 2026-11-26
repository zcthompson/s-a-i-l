"""Shared test resources: engine, Base, etc.

Importable from any test module via tests.backend._shared.
"""
from datetime import datetime

from tests.backend.database_support import engine as engine


def add_pipeline_batch(db, account_lines, *, file_name="synthetic-pipeline.csv"):
    """Retained synthetic batch, with explicit per-account source line fields."""
    from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline

    count = sum(len(lines) for _, lines in account_lines)
    batch = IntelligenceImport(
        file_name=file_name, file_sha256="0" * 64, file_data=b"synthetic test evidence",
        total_rows=count, matched_accounts=len(account_lines), matched_rows=count,
        unmatched_accounts=0, unmatched_report="[]", imported_by="admin",
        created_at=datetime(2026, 10, 25, 22, 20, 1, 123456),
    )
    db.add(batch)
    db.flush()
    source_row = 0
    for customer, lines in account_lines:
        for fields in lines:
            source_row += 1
            values = {
                "customer_account_name": customer.name, "opportunity_number": "OPP-1",
                "opp_stage": "Discover", "currency_code": "USD", "source_row": source_row,
                **fields,
            }
            db.add(PartnerPipeline(import_id=batch.id, customer_id=customer.id, **values))
    db.flush()
    return batch
