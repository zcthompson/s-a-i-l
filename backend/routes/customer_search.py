"""Account-scoped search with authorization before parameter validation."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services.account_search import search_account
from backend.services.customer_access import require_account_read

router = APIRouter(tags=["search"])


@router.get("/api/customers/{customer_id}/search/")
def search(request: Request, customer_id: int, db: Session = Depends(get_db)):
    try:
        user, _ = require_account_read(request, db, customer_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, "Customer not found") from exc
        raise
    q = request.query_params.get("q", "").strip()
    if not 2 <= len(q) <= 100:
        raise HTTPException(422, "Search query must be 2-100 characters")
    archived = request.query_params.get("include_archived", "false")
    if archived not in ("true", "false"):
        raise HTTPException(422, "include_archived must be true or false")
    return search_account(db, user, customer_id, q, archived == "true")
