"""Authenticated generic CSV imports with per-row central authorization."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import rep_intelligence_service as service

router = APIRouter(prefix="/api/rep-intelligence", tags=["rep-intelligence"])


def _require_user(request):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


@router.get("/template/")
def template(request: Request):
    _require_user(request)
    return service.template()


@router.post("/", status_code=201)
async def upload(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
):
    return await service.import_csv(db, file, _require_user(request), request)


@router.get("/")
def list_imports(request: Request, db: Session = Depends(get_db)):
    return service.list_imports(db, _require_user(request))


@router.get("/{import_id}/")
def get_import(import_id: int, request: Request, db: Session = Depends(get_db)):
    return service.get_import(db, import_id, _require_user(request))


@router.get("/{import_id}/source/")
def source(import_id: int, request: Request, db: Session = Depends(get_db)):
    return service.source(db, import_id, _require_user(request))


@router.get("/{import_id}/issues.csv/")
def issues_csv(import_id: int, request: Request, db: Session = Depends(get_db)):
    return service.issues_csv(db, import_id, _require_user(request))


@router.delete("/{import_id}/")
def delete_import(import_id: int, request: Request, db: Session = Depends(get_db)):
    return service.delete_import(db, import_id, _require_user(request), request)
