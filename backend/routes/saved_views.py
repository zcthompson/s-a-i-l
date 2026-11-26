"""Authenticated personal preferences and worklist routes."""

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.user_appearance import UserAppearance
from backend.services import saved_view_service as service
from backend.services.customer_access import read_or_404
from backend.services.dialect_insert import insert_for
from backend.services.worklist_service import worklist_for

router = APIRouter(tags=["saved-views"])
worklist_router = APIRouter(tags=["worklist"])


class ViewPayload(BaseModel):
    surface: Any
    name: Any
    params: Any


def _require_user(request):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return user


@router.get("/api/saved-views/")
def list_views(request: Request, surface: str = "portfolio", customer_id: int | None = None, db: Session = Depends(get_db)):
    user = _require_user(request)
    service.validate_surface(surface)
    if surface in service.ACCOUNT_PARAMS:
        if customer_id is None:
            raise HTTPException(422, "customer_id is required")
        read_or_404(db, user, customer_id)
    return {"views": service.list_views(db, user["user_id"], surface, customer_id)}


@router.post("/api/saved-views/")
def save_view(request: Request, payload: ViewPayload, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request)
    service.validate_surface(payload.surface)
    params = service.validate_params(payload.params, payload.surface)
    if payload.surface in service.ACCOUNT_PARAMS:
        read_or_404(db, user, int(params["customer_id"]))
    view, created = service.save_view(db, user["user_id"], **payload.model_dump())
    response.status_code = 201 if created else 200
    return {"view": view, "created": created}


@router.delete("/api/saved-views/{view_id}/", status_code=204)
def delete_view(request: Request, view_id: int, db: Session = Depends(get_db)):
    service.delete_view(db, _require_user(request)["user_id"], view_id)
    return Response(status_code=204)


@worklist_router.get("/api/worklist/mine/")
def mine(request: Request, db: Session = Depends(get_db)):
    return worklist_for(db, _require_user(request))


class AppearancePayload(BaseModel):
    model_config = {"extra": "forbid"}
    theme: Literal["light", "dark"]
    fontSize: Literal["small", "medium", "large"]


@router.get("/api/preferences/appearance/")
def get_appearance(request: Request, response: Response, db: Session = Depends(get_db)):
    user = _require_user(request)
    response.headers["Cache-Control"] = "private, no-store"
    row = db.get(UserAppearance, user["user_id"])
    return {"appearance": {"theme": row.theme, "fontSize": row.font_size} if row else None}


@router.put("/api/preferences/appearance/")
def put_appearance(request: Request, payload: AppearancePayload, db: Session = Depends(get_db)):
    user = _require_user(request)
    statement = insert_for(db, UserAppearance).values(
        user_id=user["user_id"], theme=payload.theme, font_size=payload.fontSize)
    db.execute(statement.on_conflict_do_update(index_elements=["user_id"], set_={
        "theme": payload.theme, "font_size": payload.fontSize}))
    db.commit()
    return {"appearance": payload.model_dump()}
