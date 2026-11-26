"""PDF export route with authentication and customer/assessment filtering."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services.export_service import (
    ExportScopeError,
    assert_scoped_or_admin,
    report_filename,
    resolve_export_scope,
)
from backend.services.pdf_export_service import export_use_cases_pdf

router = APIRouter(prefix="/api/export", tags=["export"])

logger = logging.getLogger(__name__)


@router.get("/pdf/")
def export_report(
    request: Request,
    use_case_ids: str | None = Query(None, description="Comma-separated use case IDs"),
    ids: str | None = Query(None, description="Comma-separated use case IDs (legacy alias)"),
    customer_name: str | None = Query(None, description="Filter by customer name"),
    assessment_id: int | None = Query(None, description="Export one assessment round (active or archived)"),
    db: Session = Depends(get_db),
):
    """Export a customer assessment as a formatted PDF report.

    Scopes to an assessment round (``assessment_id``, active or archived)
    and/or a customer (``customer_name``) and/or explicit use case IDs.
    Requires authentication; scoped customers/assessments require junction
    access (admin bypass) — same pattern as /api/customers/{name}/.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Parse explicit IDs (use_case_ids preferred; ids kept as legacy alias)
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

    logger.info(
        "User %s exporting PDF"
        f" for {len(scope_ids) if scope_ids else 'all'} use cases"
        + (f" (assessment {meta['assessment_id']})" if meta and meta.get("assessment_id") else "")
    )

    # Get PDF bytes from service
    pdf_bytes = export_use_cases_pdf(
        db, scope_ids, customer_id=customer_id, report_meta=meta
    )

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report_filename(meta, "pdf")}"'},
    )
