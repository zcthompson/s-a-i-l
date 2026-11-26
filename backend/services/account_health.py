"""Explained account health components from current, authorized evidence."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import String, case, cast, exists, func, select

from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.rep_intelligence import RepIntelligenceImport, RepIntelligenceRow
from backend.models.rvtools_import import RvToolsImport
from backend.models.sales_note import SalesNote
from backend.services import (
    customer_contact_service,
    customer_engagement_service,
    pipeline_read_model,
)
from backend.services.customer_access import require_account_read_service

EOL_LIMIT = 5
RENEWAL_BASIS = "vendor-reported pipeline; import time is not a business date"
TASK_BASIS = "open and in-progress account tasks"


def dated_eol_for(db, customer_id):
    """Return the total dated inventory and its first five evidence records."""
    model = CustomerTechnology
    names = ("id", "name", "vendor", "end_of_support_date", "eol_source",
             "lifecycle_state", "business_criticality")
    rows = db.query(*(getattr(model, key) for key in names), func.count().over().label("total")).filter(
        model.customer_id == customer_id, model.end_of_support_date.is_not(None),
    ).order_by(model.end_of_support_date, case(
        {"critical": 0, "high": 1, "medium": 2, "low": 3},
        value=model.business_criticality, else_=4), model.id).limit(EOL_LIMIT).all()
    return {"dated_count": rows[0].total if rows else 0,
            "items": [{key: row._mapping[key].isoformat() if key == "end_of_support_date"
                       else row._mapping[key] for key in names} for row in rows]}


def _exposure(summary):
    cards = [card for bucket in pipeline_read_model.DATED_BUCKETS for card in summary["buckets"][bucket]]
    amounts = {key: [card[f"est_{key}"]["total"] for card in cards] for key in ("acv", "tcv")}
    totals = {key: float(sum((Decimal(str(value)) for value in values if value is not None),
                            Decimal(0)).quantize(Decimal("0.01")))
              if any(value is not None for value in values) else None
              for key, values in amounts.items()}
    coverage = ("no_data" if not cards else "complete" if all(
        card[f"est_{key}"]["total"] is not None and card[f"est_{key}"].get("lines_excluded", 0) == 0
        for card in cards for key in ("acv", "tcv")) else "partial")
    return {**totals, "coverage": coverage}


def _freshness(db, customer_id):
    def maximum(column, *filters):
        return select(func.max(column)).where(*filters).scalar_subquery()

    pipeline = exists().where(PartnerPipeline.import_id == IntelligenceImport.id,
                              PartnerPipeline.customer_id == customer_id)
    rep = exists().where(RepIntelligenceRow.import_id == RepIntelligenceImport.id,
                         RepIntelligenceRow.customer_id == customer_id)
    # Scalar MAX subqueries share one round trip; only import metadata is read.
    columns = (
        maximum(IntelligenceImport.created_at, pipeline),
        maximum(RepIntelligenceImport.created_at, rep),
        maximum(RvToolsImport.created_at, RvToolsImport.customer_id == customer_id),
        maximum(SalesNote.note_date, SalesNote.customer_id == customer_id),
        maximum(func.coalesce(cast(CustomerActivity.occurred_at, String),
                cast(CustomerActivity.occurred_date, String)), CustomerActivity.customer_id == customer_id),
    )
    values = db.query(*columns).one()
    keys = ("pipeline_import", "rep_import", "rvtools_import", "latest_note", "latest_activity")
    return {key: value.isoformat() if isinstance(value, (date, datetime))
            else value.replace(" ", "T") if value else None for key, value in zip(keys, values)}


def health_components_for(db, user, customer_id, now=None):
    require_account_read_service(db, user, customer_id)
    now = customer_engagement_service.utc(now or datetime.now(UTC))
    coverage = customer_contact_service.contact_coverage_for(db, customer_id)
    renewal = pipeline_read_model.renewal_attention_summaries_for(
        db, [customer_id], reference_date=now.date(), as_of=now.isoformat())[customer_id]
    tasks = db.query(CustomerTask.status, CustomerTask.due_date, CustomerTask.due_at).filter(
        CustomerTask.customer_id == customer_id, CustomerTask.status.in_(("open", "in_progress"))).all()
    last = coverage["last_contacted"]
    return {"customer_id": customer_id, "calc_version": "account-health/1", "as_of": now.isoformat(),
            "components": {
                "engagement": {"last_contacted": last, "days_since": (now.date() - date.fromisoformat(last)).days
                               if last else None, "basis": coverage["last_contacted_basis"]},
                "renewals": {"snapshot": renewal["snapshot"], "counts": renewal["counts"],
                             "exposure": _exposure(renewal), "basis": RENEWAL_BASIS},
                "buying_coverage": {key: coverage[key] for key in ("contacts_recorded", "economic_buyer_recorded",
                                    "champion_recorded", "roles", "gaps")},
                "tasks": {"open": sum(task.status == "open" for task in tasks),
                          "in_progress": sum(task.status == "in_progress" for task in tasks),
                          "overdue": sum(customer_engagement_service.due_flags(task, now)["overdue"] for task in tasks),
                          "basis": TASK_BASIS},
                "eol": dated_eol_for(db, customer_id), "data_freshness": _freshness(db, customer_id),
            }}
