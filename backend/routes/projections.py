"""Projection routes for customer projections.

Endpoints:
- POST /api/customers/{name}/projections/ — Generate projection for customer
- GET /api/customers/{name}/projections/ — Get latest projection for customer
- DELETE /api/customers/{name}/projections/ — Clear projection for customer
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import sales_access
from backend.services.customers_service import get_customer_by_name
from backend.services.projection_service import (
    DEFAULT_TIMELINE,
    ProjectionService,
)

router = APIRouter(prefix="/api/customers", tags=["projections"])


@router.post("/{customer_name}/projections/")
async def generate_projection(
    customer_name: str,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    horizon: str = DEFAULT_TIMELINE,
):
    """Generate a data-grounded projection for a customer.

    horizon: one of 30-60d, 3-6m, 6-12m (single timeline per projection).
    """
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    customer = get_customer_by_name(db, customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    # 404-first: out of read scope == missing; in-scope capability
    # denials keep their exact 403.
    if not sales_access.can(user, db, sales_access.CAP_READ, customer.id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Customer not found")
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer.id):  # type: ignore[arg-type]
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")

    try:
        projection = await ProjectionService.generate_projection(db, customer_name, horizon=horizon)
        ProjectionService.store_projection(db, projection)
        return projection
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Projection generation failed: {e!s}")


@router.get("/{customer_name}/projections/")
def get_projection(
    customer_name: str,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Get the latest projection for a customer.

    Out-of-scope customers answer 404 exactly like missing ones (no oracle).
    """
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    customer = get_customer_by_name(db, customer_name)
    if not customer or not sales_access.can(user, db, sales_access.CAP_READ, customer.id):
        raise HTTPException(status_code=404, detail="Customer not found")

    projection = ProjectionService.get_projection(db, customer_name)
    if projection is None:
        raise HTTPException(status_code=404, detail="No projection found for this customer")

    return projection


@router.delete("/{customer_name}/projections/")
def clear_projection(
    customer_name: str,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Clear a projection for a customer."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    customer = get_customer_by_name(db, customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        ProjectionService.assert_delete_access(db, user, customer.id)
    except ValueError:
        # 404-first: not an owner/admin of this customer == missing.
        raise HTTPException(status_code=404, detail="Customer not found")
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer.id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")

    ProjectionService.clear_projection(db, customer_name)
    return {"message": f"Projection for {customer_name} cleared"}
