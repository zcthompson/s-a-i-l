"""REST API routes for advanced visualizations.

Customer scoping mirrors /api/analytics/* (v0.61.0): all endpoints require
authentication. An explicit ``customer_id`` requires central READ access
(else 404, 404-first); unscoped calls return global data for admins and the
caller's central READ scope (``sales_access.customer_scope``) for everyone else.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.schemas.advanced import (
    DeptComparisonResponse,
    DrillDownResponse,
    ImpactMatrixResponse,
)
from backend.services import sales_access
from backend.services.advanced_visualizations import AdvancedVisualizationsService
from backend.services.use_case_service import UseCaseService

router = APIRouter(prefix="/api/advanced", tags=["advanced-visualizations"])


def _scope_kwargs(db: Session, request: Request, customer_id: int | None) -> dict[str, Any]:
    """Auth + central-policy scoping for advanced visualization queries.

    - Explicit customer_id: requires central READ on the customer (else the
      same 404 as a missing customer — 404-first).
    - No customer_id: admins get global; everyone else gets their central
      READ scope (``sales_access.customer_scope``, resolved once).
    """
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    if customer_id is not None:
        if not sales_access.can(user, db, sales_access.CAP_READ, customer_id):
            # 404-first: out of scope == missing.
            raise HTTPException(status_code=404, detail="Customer not found")
        return {"customer_id": customer_id}
    if sales_access.is_unrestricted(user):
        return {}
    return {"customer_ids": sorted(sales_access.customer_scope(user, db))}


@router.get("/impact-matrix/", response_model=ImpactMatrixResponse)
def get_impact_matrix(
    request: Request,
    customer_id: int | None = Query(None, description="Filter by customer ID"),
    db: Session = Depends(get_db),
):
    """Get the business impact matrix: impact vs effort scatter plot."""
    return AdvancedVisualizationsService.get_impact_matrix(db, **_scope_kwargs(db, request, customer_id))


@router.get("/dept-comparison/", response_model=DeptComparisonResponse)
def get_dept_comparison(
    request: Request,
    customer_id: int | None = Query(None, description="Filter by customer ID"),
    db: Session = Depends(get_db),
):
    """Get department-level dimension comparison.

    For each department, shows averaged dimension scores across all
    scored use cases, with min/max ranges and count. Scoped to the
    caller's accessible customers (explicit customer_id requires access).
    """
    return AdvancedVisualizationsService.get_dept_comparison(db, **_scope_kwargs(db, request, customer_id))


@router.get("/drill-down/{use_case_id}/", response_model=DrillDownResponse)
def get_drill_down(
    use_case_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get detailed score breakdown for a single use case.

    Includes:
    - Dimension-level score details with weights and weighted scores
    - Historical score trends
    - AI reasoning and recommendations
    - Business impact summary
    """
    # Auth + central READ on the use case's customer (same basis as _scope_kwargs)
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    # Central read scope applies first: out-of-scope and unassigned (non-admin)
    # use cases are reported as missing, not 403 (no existence oracle).
    use_case = UseCaseService.get_by_id(db, use_case_id, user=user)
    if use_case is None:
        raise HTTPException(status_code=404, detail=f"Use case {use_case_id} not found")
    if use_case.customer_id is not None and not sales_access.can(
        user, db, sales_access.CAP_READ, use_case.customer_id  # type: ignore[arg-type]
    ):
        # 404-first: out of scope == the missing use case above.
        raise HTTPException(status_code=404, detail=f"Use case {use_case_id} not found")
    result = AdvancedVisualizationsService.get_drill_down(db, use_case_id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=f"Use case {use_case_id} not found or not scored",
        )
    return result
