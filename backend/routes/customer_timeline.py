"""Thin, centrally authorized Account 360 timeline route (E1 + E10)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services import account_timeline as service
from backend.services.customer_access import require_account_read

router = APIRouter(tags=["timeline"])
LIMIT_ERROR = "limit must be an integer between 1 and 100"


def _read(request, db, customer_id):
    try:
        return require_account_read(request, db, customer_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, "Customer not found") from exc
        raise


def _limit(raw):
    if raw is None:
        return service.DEFAULT_LIMIT
    text = raw.strip()
    if not text.isdigit() or not 1 <= int(text) <= service.MAX_LIMIT:
        raise HTTPException(422, LIMIT_ERROR)
    return int(text)


@router.get("/api/customers/{customer_id}/timeline/")
def account_timeline(request: Request, customer_id: int, limit: str | None = None,
                     cursor: str | None = None, db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    page_size = _limit(limit)
    try:
        return service.build_timeline(db, customer_id, limit=page_size, cursor=cursor)
    except service.InvalidCursor as exc:
        raise HTTPException(400, "Invalid cursor") from exc
