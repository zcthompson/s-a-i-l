"""REST API routes for statistics and reporting with authentication."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services.customers_service import get_accessible_customers
from backend.services.export_service import (
    ExportScopeError,
    assert_scoped_or_admin,
    report_filename,
    resolve_export_scope,
)
from backend.services.stats_service import StatsService

router = APIRouter(prefix="/api/stats", tags=["stats"])

logger = logging.getLogger(__name__)


def _require_user(request: Request) -> dict:
    """Return authenticated user or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _resolve_stats_scope(
    db: Session, user: dict, customer_id: int | None
) -> tuple[int | None, list | None]:
    """Resolve the caller's authorized stats scope.

    Returns ``(explicit_customer_id, customer_ids)`` to pass to
    ``StatsService``. Authorization occurs **before** any aggregation:

    - Admin: global scope (``None, None``); an explicit ``customer_id`` is
      passed through when positive (foreign/invalid IDs return an empty,
      well-formed result rather than 404, preserving the "filter" contract).
    - Non-admin: ``customer_ids`` = the union of accessible customers
      (``[]`` when the user has no assignment → every field is empty, no
      data). An explicit ``customer_id`` outside the union is rejected (403)
      so a foreign scope can never widen or read another account's data.
    """
    if user.get("is_admin") == 1:
        if customer_id is not None and customer_id < 1:
            raise HTTPException(
                status_code=422, detail="customer_id must be a positive ID"
            )
        return customer_id, None

    accessible = [c.id for c in get_accessible_customers(db, user)]
    if customer_id is not None:
        if customer_id < 1:
            raise HTTPException(
                status_code=422, detail="customer_id must be a positive ID"
            )
        if customer_id not in accessible:
            # 404-first: an out-of-scope customer filter is the same
            # as a missing customer — no existence oracle.
            raise HTTPException(
                status_code=404, detail="Customer not found"
            )
        return customer_id, accessible
    return None, accessible


def _resolve_scope(
    db: Session,
    request: Request,
    use_case_ids: str | None,
    ids: str | None,
    customer_name: str | None,
    assessment_id: int | None,
    kind: str,
):
    """Parse explicit IDs, resolve the export scope, and audit-log it.

    Shared by the CSV/Excel export routes — scoping and access checks live
    in export_service (single source of truth across all export formats).
    """
    user = _require_user(request)

    id_list = None
    raw_ids = use_case_ids or ids
    if raw_ids:
        try:
            id_list = [int(i.strip()) for i in raw_ids.split(",") if i.strip()]
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid IDs format")

    try:
        assert_scoped_or_admin(user, customer_name, assessment_id, id_list)
        scope_ids, customer_id, meta = resolve_export_scope(
            db,
            user,
            customer_name=customer_name,
            assessment_id=assessment_id,
            use_case_ids=id_list,
        )
    except ExportScopeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    user_id = user.get("username") or "anonymous"
    logger.info(
        f"User {user_id} exporting {kind} for "
        f"{len(scope_ids) if scope_ids else 'all'} use cases"
        + (f" (assessment {meta['assessment_id']})" if meta and meta.get("assessment_id") else "")
    )
    return scope_ids, customer_id, meta


@router.get("/aggregate/")
def get_aggregate_stats(
    request: Request,
    customer_id: int | None = Query(None, description="Optional customer filter"),
    db: Session = Depends(get_db),
):
    """Get comprehensive aggregate statistics, scoped to the caller.

    Admins receive global aggregates (or one customer when ``customer_id`` is
    supplied). Non-admins always receive the union of their accessible
    customers; an explicit ``customer_id`` outside that union is rejected.
    """
    user = _require_user(request)
    scope_id, scope_ids = _resolve_stats_scope(db, user, customer_id)
    return StatsService.get_aggregate_stats(db, customer_id=scope_id, customer_ids=scope_ids)


@router.get("/trends/")
def get_score_trends(
    request: Request,
    days: int = Query(30, ge=1, le=365),
    customer_id: int | None = Query(None, description="Optional customer filter"),
    db: Session = Depends(get_db),
):
    """Get score trends over time, scoped to the caller."""
    user = _require_user(request)
    scope_id, scope_ids = _resolve_stats_scope(db, user, customer_id)
    return StatsService.get_score_trends(db, days, customer_id=scope_id, customer_ids=scope_ids)


@router.get("/export/csv/")
def export_to_csv(
    request: Request,
    use_case_ids: str | None = Query(None, description="Comma-separated use case IDs"),
    ids: str | None = Query(None, description="Comma-separated use case IDs (legacy alias)"),
    customer_name: str | None = Query(None, description="Filter by customer name"),
    assessment_id: int | None = Query(None, description="Export one assessment round (active or archived)"),
    db: Session = Depends(get_db),
):
    """Export a customer assessment to CSV.

    Scoped to an assessment round (``assessment_id``, active or archived)
    and/or a customer (``customer_name``) and/or explicit use case IDs.
    Requires authentication; scoped customers/assessments require junction
    access (admin bypass).
    """
    scope_ids, customer_id, meta = _resolve_scope(
        db, request, use_case_ids, ids, customer_name, assessment_id, "CSV"
    )

    csv_content = StatsService.export_to_csv(db, scope_ids, customer_id=customer_id)

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(meta, "csv")}"'},
    )


@router.get("/export/excel/")
def export_to_excel(
    request: Request,
    use_case_ids: str | None = Query(None, description="Comma-separated use case IDs"),
    ids: str | None = Query(None, description="Comma-separated use case IDs (legacy alias)"),
    customer_name: str | None = Query(None, description="Filter by customer name"),
    assessment_id: int | None = Query(None, description="Export one assessment round (active or archived)"),
    db: Session = Depends(get_db),
):
    """Export a customer assessment to an Excel workbook.

    All workbook sheets are computed from the same scoped query set.
    Requires authentication; scoped customers/assessments require junction
    access (admin bypass).
    """
    scope_ids, customer_id, meta = _resolve_scope(
        db, request, use_case_ids, ids, customer_name, assessment_id, "Excel"
    )

    excel_bytes = StatsService.export_excel(
        db, scope_ids, customer_id=customer_id, report_meta=meta
    )

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(meta, "xlsx")}"'},
    )
