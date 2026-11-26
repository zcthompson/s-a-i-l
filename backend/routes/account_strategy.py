"""Account-scoped strategy routes."""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.dependencies import get_db
from backend.models.account_strategy import AccountStrategy, AccountStrategySnapshot
from backend.routes.customer_contact import _read, _require_user
from backend.schemas.strategy import (
    SnapshotPublish,
    SnapshotRestore,
    StrategyLinksUpdate,
    StrategyUpdate,
)
from backend.services import account_strategy as service
from backend.services import sales_access
from backend.services.customer_access import read_or_404

router = APIRouter(tags=["account strategy"])


def _write(request, db, cid):
    user = _require_user(request)
    read_or_404(db, user, cid)
    if not sales_access.can(user, db, sales_access.CAP_STRATEGY, cid, section="strategy"):
        raise HTTPException(403, "Not authorized to modify this customer")
    return user


def _snapshot(request, db, snapshot_id):
    user = _require_user(request)
    row = db.get(AccountStrategySnapshot, snapshot_id)
    if row is None:
        raise HTTPException(404, "Strategy snapshot not found")
    read_or_404(db, user, row.customer_id)
    return user, row


@router.get("/api/customers/{customer_id}/strategy/")
def get_strategy(request: Request, customer_id: int, db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    return service.get_strategy(db, customer_id)


@router.put("/api/customers/{customer_id}/strategy/")
def save_strategy(request: Request, customer_id: int, payload: StrategyUpdate, db: Session = Depends(get_db)):
    user = _write(request, db, customer_id)
    return service.save_strategy(db, customer_id, payload.model_dump(exclude_unset=True), user["username"])


@router.put("/api/customers/{customer_id}/strategy/links/")
def set_links(request: Request, customer_id: int, payload: StrategyLinksUpdate, db: Session = Depends(get_db)):
    user = _write(request, db, customer_id)
    row = db.query(AccountStrategy).filter_by(customer_id=customer_id).first()
    return service.set_links(db, row.id if row else None, payload.model_dump(exclude_unset=True), user["username"])


@router.post("/api/customers/{customer_id}/strategy/snapshots/", status_code=201)
def publish(request: Request, customer_id: int, payload: SnapshotPublish, db: Session = Depends(get_db)):
    user = _write(request, db, customer_id)
    return service.publish_snapshot(db, customer_id, payload.model_dump(exclude_unset=True), user["username"])


@router.get("/api/customers/{customer_id}/strategy/snapshots/")
def snapshots(request: Request, customer_id: int, db: Session = Depends(get_db)):
    _read(request, db, customer_id)
    return {"snapshots": service.list_snapshots(db, customer_id)}


@router.get("/api/strategy-snapshots/{snapshot_id}/")
def snapshot(request: Request, snapshot_id: int, db: Session = Depends(get_db)):
    _, row = _snapshot(request, db, snapshot_id)
    return service.get_snapshot(db, row.customer_id, row.id)


@router.post("/api/strategy-snapshots/{snapshot_id}/restore/")
def restore(request: Request, snapshot_id: int, payload: SnapshotRestore, db: Session = Depends(get_db)):
    user, row = _snapshot(request, db, snapshot_id)
    if not sales_access.can(user, db, sales_access.CAP_STRATEGY, row.customer_id, section="strategy"):
        raise HTTPException(403, "Not authorized to modify this customer")
    return service.restore_snapshot(db, row.customer_id, row.id, payload.model_dump(exclude_unset=True), user["username"])
