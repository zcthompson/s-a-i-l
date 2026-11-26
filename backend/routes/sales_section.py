"""Sales Section API Endpoints for S-A-I-L (Sales Analytics and Intelligence Launchpad).

Provides endpoints for:
1. Listing use cases linked to a customer with sales-ready data
2. Getting customer knowledge summary for sales evaluations
3. Sales readiness insights linking scoring and customer knowledge

All customer-scoped endpoints are auth-gated through the central
``sales_access`` READ capability (Part 13 DV wave, ruling R1); admins pass
via the central policy.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.use_case import Customer
from backend.schemas.customer_knowledge import CustomerKnowledge as CKSchema
from backend.schemas.use_case import UseCaseResponse
from backend.services import customer_access
from backend.services.customer_knowledge_service import get_customer_knowledge_list
from backend.services.third_party_service import readiness_summary
from backend.services.use_case_service import UseCaseService

router = APIRouter(prefix="/api/sales", tags=["sales"])


def _require_existing_customer(db: Session, customer_id: int) -> Customer:
    """Resolve an existing customer after the access gate (BE-04).

    Access is checked first (403 for a caller without READ), then
    existence (404 for a missing customer) — so an unauthorized caller gets
    403, not a 404 existence disclosure. A missing customer must 404 rather
    than yield a zero-shaped readiness/listing that resembles a real, empty
    account.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@router.get("/customers/{customer_id}/usecases", response_model=list[UseCaseResponse])
def list_customer_use_cases_sales(
    customer_id: int,
    request: Request,
    skip: int = Query(0, ge=0, description="Number of records to skip (>= 0)"),
    limit: int = Query(100, ge=1, le=1000, description="Page size (1..1000)"),
    db: Session = Depends(get_db),
):
    """List all use cases for a customer with sales-ready data (auth-gated).

    Includes the technology tracking fields (tech_stack, devices, software,
    vendor) via to_dict() so the data feeds sales briefs. A missing customer
    is a 404 (BE-04). Explicitly paginated with the same bounded contract as
    ``/api/use-cases/`` (BE-03/FE-03) — no arbitrary 1000-row cap.
    """
    user = customer_access.read_or_403(request, db, customer_id)
    _require_existing_customer(db, customer_id)

    use_cases = UseCaseService.get_all(
        db, skip=skip, limit=limit,
        customer_id=customer_id, user=user,
    )
    return [uc.to_dict() for uc in use_cases]


@router.get("/customers/{customer_id}/knowledge", response_model=list[CKSchema])
def list_customer_knowledge_sales(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """List customer knowledge entries for sales evaluation (auth-gated).

    A missing customer is a 404 (BE-04).
    """
    customer_access.read_or_403(request, db, customer_id)
    _require_existing_customer(db, customer_id)

    entries = get_customer_knowledge_list(db, customer_id)
    return entries


@router.get("/customers/{customer_id}/readiness", response_model=dict)
def get_customer_readiness_sales(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get combined readiness assessment for sales team (auth-gated).

    A missing customer is a 404 (BE-04) — previously it returned a
    zero-count readiness-shaped body that resembled a real empty account.

    The organizational_readiness aggregates are computed in SQL over the
    COMPLETE customer dataset (BE-07) — not from a capped row fetch — so
    total/scored counts and the average stay correct past any arbitrary
    limit and never include another customer's records.
    """
    customer_access.read_or_403(request, db, customer_id)
    customer = _require_existing_customer(db, customer_id)

    from backend.services.stats_service import StatsService

    org = StatsService.customer_readiness_aggregates(db, customer_id)

    knowledge_entries = get_customer_knowledge_list(db, customer_id)

    tech_profile = customer.tech_profile

    knowledge_counts = {}
    for entry in knowledge_entries:
        ktype = entry.knowledge_type
        knowledge_counts[ktype] = knowledge_counts.get(ktype, 0) + 1

    # Environment knowledge coverage by type (drives the readiness summary).
    has_software = knowledge_counts.get("software_inventory", 0) > 0
    has_hardware = knowledge_counts.get("hardware_inventory", 0) > 0
    has_process = (
        knowledge_counts.get("process_document", 0)
        + knowledge_counts.get("policy_document", 0)
    ) > 0

    return {
        "customer_id": customer_id,
        "organizational_readiness": {
            "average_score": org["average_score"],
            "scored_use_cases": org["scored_use_cases"],
            "total_use_cases": org["total_use_cases"],
        },
        "customer_environment": {
            "tech_profile": tech_profile,
            "knowledge_entries": len(knowledge_entries),
            "knowledge_by_type": knowledge_counts,
            # Third-party professional services (0.1.6, additive — existing
            # keys unchanged; docs/archive/PLAN_THIRD_PARTY_SERVICES.md §4.4).
            "third_party_services": readiness_summary(db, customer_id),
        },
        "gap_analysis": {
            # The full cross-domain gap/risk/growth analysis is produced by the
            # sales-evaluations engine (POST /api/sales-evaluations/). This
            # endpoint reports readiness + environment coverage only.
            "readiness_vs_environment": (
                "Full gap/risk/growth analysis available via "
                "POST /api/sales-evaluations/ (cross-domain evaluation engine)."
            ),
            "software_gaps": (
                "Assessable" if has_software else "No software inventory recorded yet"
            ),
            "hardware_risks": (
                "Assessable" if has_hardware else "No hardware inventory recorded yet"
            ),
            "process_coverage": (
                "Documented" if has_process else "No process/policy documentation recorded yet"
            ),
        },
        "sales_approach": {
            "recommended_focus": (
                "Combine organizational readiness scoring with customer "
                "environment knowledge for a cross-domain evaluation."
            ),
            "next_actions": [
                "Review use case scoring details",
                "Upload software/hardware inventory (CSV/PDF) to the customer knowledge base",
                "Generate a cross-domain sales evaluation (sales-evaluations endpoint)",
            ],
        },
    }


@router.get("/health-check", response_model=dict)
def sales_health_check():
    """Simple health check for sales section."""
    return {"status": "ok", "message": "Sales section API is operational"}
