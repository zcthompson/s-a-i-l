"""Manager-gated import routes and customer-scoped pipeline access."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import Customer
from backend.services import intelligence_import_service as service
from backend.services import sales_access
from backend.services.customer_access import require_account_read

router = APIRouter(tags=["intelligence-import"])
import_router = APIRouter(prefix="/api/intelligence-import")


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
    # Central READ scope; admin -> None (all).
    return None if user.get("is_admin") == 1 else sales_access.customer_scope(user, db)


@import_router.post("/")
async def upload_pipeline(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
):
    return await service.import_pipeline(db, file, _require_manager(request), request)


@import_router.get("/")
def list_pipeline_imports(request: Request, db: Session = Depends(get_db)):
    _require_manager(request)
    return service.list_imports(db)


@import_router.get("/{import_id}/")
def get_pipeline_import(import_id: int, request: Request, db: Session = Depends(get_db)):
    user = _require_manager(request)
    return service.get_import(db, import_id, _accessible_customer_ids(user, db))


@import_router.delete("/{import_id}/")
def delete_pipeline_import(import_id: int, request: Request, db: Session = Depends(get_db)):
    return service.delete_import(db, import_id, _require_manager(request), request)


@router.get("/api/customers/{name}/pipeline/")
def get_customer_pipeline(
    name: str, request: Request, db: Session = Depends(get_db),
    compare_with: str | None = None,
):
    _require_user(request)
    customer_id = db.query(Customer.id).filter(Customer.name == name).scalar()
    if customer_id is None:
        raise HTTPException(404, "Customer not found")
    try:
        require_account_read(request, db, customer_id)
    except HTTPException as exc:
        # This endpoint historically hides out-of-scope account existence.
        if exc.status_code == 403:
            raise HTTPException(404, "Customer not found") from None
        raise
    return service.customer_pipeline(db, name, [customer_id], compare_with=compare_with)


router.include_router(import_router)
