"""Per-customer sales-team correction routes (system admin only).

The operator's pre-reseed correction surface for primary rep, manager,
inside sales and sales ops. Deliberately NOT opened to sales_manager.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.routes.customer_sharing import _record_audit
from backend.schemas.sales_team import SalesTeamResponse, SalesTeamUpdate
from backend.services import sales_team_service as svc
from backend.services.customers_service import get_customer_by_name

router = APIRouter(prefix="/api/customers", tags=["customer-sales-team"])


def _require_admin_customer(request: Request, db: Session, customer_name: str):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get("is_admin") != 1:
        raise HTTPException(status_code=403, detail="System admin required")
    customer = get_customer_by_name(db, customer_name)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return user, customer


@router.get("/{customer_name}/sales-team/", response_model=SalesTeamResponse)
def get_sales_team(customer_name: str, request: Request, db: Session = Depends(get_db)):
    """Editor state (user ids) for the customer's sales team."""
    _, customer = _require_admin_customer(request, db, customer_name)
    return svc.get_sales_team(db, customer)


@router.put("/{customer_name}/sales-team/", response_model=SalesTeamResponse)
def update_sales_team(
    customer_name: str,
    payload: SalesTeamUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Correct the customer's primary rep, manager, inside sales and sales ops."""
    user, customer = _require_admin_customer(request, db, customer_name)
    try:
        events = svc.update_sales_team(db, customer, payload, user.get("user_id"))
    except svc.SalesTeamError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    for ev in events:
        _record_audit(
            db, user, ev["action"], customer,
            target_id=ev["target_id"], details=ev["details"], request=request,
        )
    return svc.get_sales_team(db, customer)
