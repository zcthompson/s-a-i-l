"""Per-customer aggregate statistics endpoint.

Enforces junction-table access control:
- Admin: see all customer stats
- Junction users: see only their assigned customers (an out-of-scope
  customer is the same 404 as a missing one — 404-first)
"""

from fastapi import APIRouter, HTTPException, Request

from backend.auth import get_user_from_request
from backend.models.use_case import get_session
from backend.schemas.customer_stats import CustomerStatsResponse
from backend.services.customer_stats_service import CustomerStatsService
from backend.services.customers_service import get_customer_by_name

router = APIRouter(prefix="/api/customers", tags=["customer-stats"])


@router.get("/stats/")
def get_all_customers_stats(request: Request, my_view: bool = False):
    """Get aggregate statistics across all customers.

    Admin users see all customers by default. When ``my_view=True``,
    admins are scoped to their assigned customers via the junction table.
    Junction users see only their assigned customers.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    db = get_session()
    try:
        return CustomerStatsService.build_stats_response(db, user, my_view)
    finally:
        db.close()


@router.get("/{customer_name}/stats/", response_model=CustomerStatsResponse)
def get_customer_stats(customer_name: str, request: Request):
    """Get aggregate statistics for a specific customer (access-controlled).

    Missing customer or caller without junction access → the same 404
    (404-first).
    The ``response_model`` validates the success shape so an error-dict body
    can no longer masquerade as statistics.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    db = get_session()
    try:
        # Resolve customer name to object (simple read query, acceptable)
        customer = get_customer_by_name(db, customer_name)
        if not customer:
            # A missing customer is a 404, not a 200 error-dict: an
            # error dict masquerading as stats made the FE render zeros.
            raise HTTPException(status_code=404, detail="Customer not found")

        return CustomerStatsService.build_customer_stats_response(db, customer, user)
    finally:
        db.close()
