"""Thin NetSuite import API; service enforces role, scope and transactions."""

from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import netsuite_import_service as service

router = APIRouter(tags=["netsuite-import"])


@router.post("/api/netsuite-import/")
async def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await service.import_file(db, file, get_user_from_request(request), request)


@router.get("/api/netsuite-import/")
def history(request: Request, db: Session = Depends(get_db)):
    return service.history(db, get_user_from_request(request))


@router.get("/api/netsuite-import/{batch_id}/")
def detail(batch_id: int, request: Request, db: Session = Depends(get_db)):
    return service.detail(db, get_user_from_request(request), batch_id)


@router.get("/api/netsuite-import/{batch_id}/unmatched/")
def unmatched(batch_id: int, request: Request, db: Session = Depends(get_db)):
    return service.unmatched(db, get_user_from_request(request), batch_id)


@router.post("/api/netsuite-import/{batch_id}/rematch/")
def rematch(batch_id: int, request: Request, db: Session = Depends(get_db)):
    return service.rematch(db, get_user_from_request(request), batch_id, request)
