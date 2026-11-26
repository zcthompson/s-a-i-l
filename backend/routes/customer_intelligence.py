"""Customer Intelligence API routes (S-A-I-L P4).

Per-customer deterministic intelligence Overview aggregation
(CHANGELOG 0.0.80 items 4-5, 14-15). Reads use the central account policy
before any content is assembled; an out-of-scope customer returns the same
404 as a missing one (404-first, R4/Q7). Business logic (the aggregation itself) lives in
backend/services/customer_intelligence.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import Customer
from backend.services import customer_intelligence as cis
from backend.services import sales_access

router = APIRouter(tags=["customer-intelligence"])


def _require_account_read(request: Request, db: Session, customer_id: int) -> None:
    """401 unauthenticated; 404 when the customer is missing OR out of scope.

    The existing in-scope basis for these routes (the central account-read
    policy of ``customer_access.require_account_read``, unchanged). Out-of-
    scope is remapped to 404 (oracle-closing, R4/Q7); the shared helper keeps
    its 403 for its other callers.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None or not sales_access.can(user, db, sales_access.CAP_READ, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")


@router.get("/api/customers/{customer_id}/intelligence/overview/")
def customer_intelligence_overview(
    request: Request, customer_id: int, db: Session = Depends(get_db)
):
    """Deterministic per-customer intelligence Overview (S-A-I-L P4).

    Aggregates Customer Knowledge, Technology Inventory, Sales Notes, and
    Use Cases into counts + derived indicators. No LLM — pure rule-based
    SQL aggregation; unknowns stay unknown (zeros/None, never fabricated).
    """
    _require_account_read(request, db, customer_id)
    return cis.get_customer_overview(db, customer_id)


@router.get("/api/customers/{customer_id}/intelligence/workspace/")
def customer_intelligence_workspace(
    request: Request, customer_id: int, db: Session = Depends(get_db)
):
    """Account workspace context (CHANGELOG 0.1.0 U1).

    Four actionable summaries (Technology Landscape, Knowledge, Sales
    Activity, Assessment & Use Case) + consolidated Business Impact +
    latest Sales Evaluation reference + typed, evidence-backed
    Opportunities & Attention synthesis. Deterministic; same auth/isolation
    convention as the overview endpoint (central account-read policy).
    """
    _require_account_read(request, db, customer_id)
    return cis.get_account_workspace(db, customer_id)


@router.get("/api/customers/{customer_id}/intelligence/graph/")
def customer_intelligence_graph(
    request: Request, customer_id: int, db: Session = Depends(get_db)
):
    """Customer Intelligence graph projection (F3).

    Deterministic node/link view model for the Customer Intelligence
    Constellation (Customer -> Domain -> Entity + technology-dependency +
    cross-domain links from authoritative references). Canonical
    orientation, deduplicated, provenance + epistemic class on every link,
    bounded top-N per domain with the active limits reported. Same
    auth/isolation convention as the overview/workspace endpoints
    (central account-read policy) — authorization runs BEFORE assembly.
    """
    _require_account_read(request, db, customer_id)
    return cis.build_customer_intelligence_graph(db, customer_id)
