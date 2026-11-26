"""Manager mutations and customer-scoped RVTools inventory reads."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import rvtools_import_service as service
from backend.services import sales_access

router = APIRouter(tags=["rvtools-import"])
import_router = APIRouter(prefix="/api/rvtools-import")


def _require_user(request):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


def _require_manager(request):
    user = _require_user(request)
    if sales_access.effective_role(user) not in {"system_admin", "sales_manager", "sales_admin"}:
        raise HTTPException(403, "Manager access required")
    return user


def _accessible_customer_ids(user, db):
    # Central READ scope (Part 13 DV wave, ruling R1); admin -> None (all).
    return None if user.get("is_admin") == 1 else sales_access.customer_scope(user, db)


@import_router.post("/", status_code=201)
async def upload_rvtools(
    request: Request, file: UploadFile = File(...), customer_name: str | None = Form(None),
    db: Session = Depends(get_db),
):
    # customer_name = a customer name OR alias (case-insensitive); imports
    # never create a customer (Part 14 import remediation).
    return await service.import_rvtools(
        db, file, _require_manager(request), customer_name, request,
    )


@import_router.get("/")
def list_rvtools_imports(request: Request, db: Session = Depends(get_db)):
    user = _require_manager(request)
    return service.list_imports(db, _accessible_customer_ids(user, db))


@import_router.get("/{import_id}/")
def get_rvtools_import(
    import_id: int, request: Request, vm_limit: int = 100, vm_offset: int = 0,
    db: Session = Depends(get_db),
):
    user = _require_manager(request)
    return service.get_import(db, import_id, _accessible_customer_ids(user, db), vm_limit, vm_offset)


@import_router.delete("/{import_id}/")
def delete_rvtools_import(import_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_manager(request)
    return service.delete_import(db, import_id, user, _accessible_customer_ids(user, db), request)


@router.get("/api/customers/{name}/rvtools/")
def get_customer_rvtools(name: str, request: Request, db: Session = Depends(get_db)):
    user = _require_user(request)
    return service.customer_rvtools(db, name, _accessible_customer_ids(user, db))


router.include_router(import_router)
