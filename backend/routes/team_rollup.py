"""Authorized manager team rollups."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services.team_rollup_service import team_rollup_for

router = APIRouter(tags=["team-rollups"])


@router.get("/api/rollups/team/")
def team_rollup(request: Request, db: Session = Depends(get_db)):
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    return team_rollup_for(db, user)
