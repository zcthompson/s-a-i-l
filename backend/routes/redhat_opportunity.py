"""Red Hat account opportunity report import and scoped customer read."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import redhat_opportunity_service as service
from backend.services import sales_access

router = APIRouter(tags=["redhat-opportunities"])


def _user(request):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


def _manager(request):
    user = _user(request)
    if sales_access.effective_role(user) not in {"system_admin", "sales_manager"}:
        raise HTTPException(403, "Manager access required")
    return user


@router.post("/api/redhat-opportunity-import/")
async def upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    return await service.import_workbook(db, file, _manager(request), request)


@router.get("/api/redhat-opportunity-import/")
def imports(request: Request, db: Session = Depends(get_db)):
    return service.history(db, _manager(request))


@router.get("/api/redhat-opportunity-import/{batch_id}/unmatched/")
def unmatched(batch_id: int, request: Request, db: Session = Depends(get_db)):
    return service.unmatched_report(db, _manager(request), batch_id)


@router.get("/api/customers/{customer_id}/redhat-opportunities/")
def customer_report(customer_id: int, request: Request, db: Session = Depends(get_db)):
    return service.customer_report(db, _user(request), customer_id)
