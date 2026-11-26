"""Centrally authorized health components with the account 404-first oracle."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.services.account_health import health_components_for
from backend.services.customer_access import require_account_read

router = APIRouter(tags=["account health"])


@router.get("/api/customers/{customer_id}/health/")
def health(request: Request, customer_id: int, db: Session = Depends(get_db)):
    try:
        user, _ = require_account_read(request, db, customer_id)
        return health_components_for(db, user, customer_id)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, "Customer not found") from exc
        raise
