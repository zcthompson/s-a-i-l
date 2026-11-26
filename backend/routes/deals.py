"""Thin E6 deal and pipeline-stage routes.

Reads require account read access (404-first); writes require
CAP_OPPORTUNITIES on the "opportunities" section. Stage configuration is
limited to system admins and sales admins. Ownership grants no access.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.deal import Deal
from backend.routes.customer_activity import accessible_item, require_write
from backend.routes.customer_contact import _read, _require_user
from backend.schemas.deal import (
    DealCreate,
    DealDelete,
    DealPromotion,
    DealUpdate,
    StageCreate,
    StageUpdate,
)
from backend.services import deal_service as service
from backend.services import sales_access
from backend.services.customer_access import read_or_404

router = APIRouter(tags=["deals"])


def _require_stage_admin(user):
    if user.get("is_admin") != 1 and sales_access.effective_role(user) != "sales_admin":
        raise HTTPException(403, "Admin or sales admin privileges required")


@router.get("/api/pipeline-stages/")
def list_stages(request: Request, include_inactive: bool = False, db: Session = Depends(get_db)):
    _require_user(request)
    return service.list_stages(db, include_inactive)


@router.post("/api/admin/pipeline-stages/", status_code=201)
def create_stage(request: Request, payload: StageCreate, db: Session = Depends(get_db)):
    _require_stage_admin(_require_user(request))
    return service.create_stage(db, payload.model_dump())


@router.put("/api/admin/pipeline-stages/{stage_id}/")
def update_stage(request: Request, stage_id: int, payload: StageUpdate, db: Session = Depends(get_db)):
    user = _require_user(request)
    _require_stage_admin(user)
    return service.update_stage(db, stage_id, payload.model_dump(exclude_unset=True), user["username"])


@router.get("/api/customers/{customer_id}/deals/")
def list_deals(request: Request, customer_id: int, include_closed: bool = True,
               db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    return service.list_deals(db, customer_id, include_closed=include_closed)


@router.post("/api/customers/{customer_id}/deals/", status_code=201)
def create_deal(request: Request, customer_id: int, payload: DealCreate, db: Session = Depends(get_db)):
    user = _require_user(request)
    read_or_404(db, user, customer_id)
    require_write(user, db, customer_id, sales_access.CAP_OPPORTUNITIES, "opportunities")
    return service.create_deal(db, customer_id, payload.model_dump(exclude_unset=True), user["username"])


@router.post("/api/customers/{customer_id}/deals/promote/")
def promote_deal(request: Request, customer_id: int, payload: DealPromotion, db: Session = Depends(get_db)):
    user = _require_user(request)
    read_or_404(db, user, customer_id)
    require_write(user, db, customer_id, sales_access.CAP_OPPORTUNITIES, "opportunities")
    return service.promote(db, customer_id, payload.model_dump(exclude_none=True), user["username"])


@router.get("/api/deals/{deal_id}/")
def get_deal(request: Request, deal_id: int, db: Session = Depends(get_db)):
    row = accessible_item(_require_user(request), db, Deal, deal_id, "Deal")
    return service.list_deals(db, row.customer_id, deal_id=row.id)[0]


@router.get("/api/deals/{deal_id}/history/")
def deal_history(request: Request, deal_id: int, db: Session = Depends(get_db)):
    row = accessible_item(_require_user(request), db, Deal, deal_id, "Deal")
    return service.history(db, row.id)


@router.put("/api/deals/{deal_id}/")
def update_deal(request: Request, deal_id: int, payload: DealUpdate, db: Session = Depends(get_db)):
    user = _require_user(request)
    row = accessible_item(user, db, Deal, deal_id, "Deal")
    require_write(user, db, row.customer_id, sales_access.CAP_OPPORTUNITIES, "opportunities")
    return service.update_deal(db, row, payload.model_dump(exclude_unset=True), user["username"])


@router.delete("/api/deals/{deal_id}/", status_code=204)
def delete_deal(request: Request, deal_id: int, payload: DealDelete, db: Session = Depends(get_db)):
    user = _require_user(request)
    row = accessible_item(user, db, Deal, deal_id, "Deal")
    require_write(user, db, row.customer_id, sales_access.CAP_OPPORTUNITIES, "opportunities")
    service.delete_deal(db, row, payload.expected_version)
