"""Thin routes for recorded customer interactions."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.customer_engagement import CustomerActivity
from backend.routes.customer_contact import _read, _require_user
from backend.schemas.engagement import ActivityCreate, ActivityUpdate
from backend.services import customer_engagement_service as service
from backend.services import sales_access
from backend.services.customer_access import read_or_404, require_account_read_service

router = APIRouter(tags=["activities"])


def accessible_item(user, db, model, item_id, label):
    from fastapi import HTTPException
    row = db.query(model).filter_by(id=item_id).first()
    if row is None:
        raise HTTPException(404, f"{label} not found")
    try:
        require_account_read_service(db, user, row.customer_id)
    except HTTPException as exc:
        if exc.status_code in (403, 404):
            raise HTTPException(404, f"{label} not found") from exc
        raise
    return row


def require_write(user, db, customer_id, capability, section):
    from fastapi import HTTPException
    if not sales_access.can(user, db, capability, customer_id, section=section):
        raise HTTPException(403, "Not authorized to modify this customer")


@router.get("/api/customers/{customer_id}/activities/")
def list_activities(request: Request, customer_id: int, db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    return service.list_activities(db, customer_id)


@router.post("/api/customers/{customer_id}/activities/", status_code=201)
def create_activity(request: Request, customer_id: int, payload: ActivityCreate,
                    db: Session = Depends(get_db)):
    user = _require_user(request)
    read_or_404(db, user, customer_id)
    require_write(user, db, customer_id, sales_access.CAP_ACTIVITIES, "activities")
    return service.create_activity(db, customer_id, payload.model_dump(), user["username"])


@router.get("/api/activities/{activity_id}/")
def get_activity(request: Request, activity_id: int, db: Session = Depends(get_db)):
    row = accessible_item(_require_user(request), db, CustomerActivity, activity_id, "Activity")
    return service.list_activities(db, row.customer_id, row.id)[0]


@router.put("/api/activities/{activity_id}/")
def update_activity(request: Request, activity_id: int, payload: ActivityUpdate,
                    db: Session = Depends(get_db)):
    user = _require_user(request)
    row = accessible_item(user, db, CustomerActivity, activity_id, "Activity")
    require_write(user, db, row.customer_id, sales_access.CAP_ACTIVITIES, "activities")
    return service.update_activity(db, row, payload.model_dump(exclude_unset=True), user["username"])


@router.delete("/api/activities/{activity_id}/", status_code=204)
def delete_activity(request: Request, activity_id: int, db: Session = Depends(get_db)):
    user = _require_user(request)
    row = accessible_item(user, db, CustomerActivity, activity_id, "Activity")
    require_write(user, db, row.customer_id, sales_access.CAP_ACTIVITIES, "activities")
    service.delete_activity(db, row)
