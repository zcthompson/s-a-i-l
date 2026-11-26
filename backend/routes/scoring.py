"""REST API routes for scoring operations."""



from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.collaboration import AuditLog
from backend.models.use_case import UseCase
from backend.schemas.use_case import (
    DimensionConfigCreate,
    DimensionConfigResponse,
    DimensionInfo,
    ManualScoreRequest,
    ManualScoreResponse,
    ScoredUseCaseResponse,
    ScoringRequest,
    ScoringResponse,
    ScoringValidationRequest,
    ScoringValidationResponse,
    UseCaseResponse,
)
from backend.services import sales_access
from backend.services.assessment_service import (
    AI_SCORING_UNAVAILABLE,
    AssessmentService,
    GenericAssessmentError,
)
from backend.services.scoring import ScoringService
from backend.services.use_case_service import UseCaseService

router = APIRouter(prefix="/api/scoring", tags=["scoring"])


def _require_edit_for_use_case(user: dict, db: Session, use_case_id: int) -> None:
    """403 unless the caller holds CAP_EDIT on the use case's customer.

    The customer is derived from the persisted use case (never from the
    request). A missing or unassigned use case is left to the service layer
    (404 / its existing admin-only rule).
    """
    row = db.query(UseCase.customer_id).filter(UseCase.id == use_case_id).first()
    if row is None or row[0] is None:
        return
    # 404-first: out of read scope == missing; in-scope capability
    # denials keep their exact 403. The detail matches the missing-use-case
    # pattern (id echoed) so a by-id probe is indistinguishable.
    if not sales_access.can(user, db, sales_access.CAP_READ, row[0]):
        raise HTTPException(status_code=404, detail=f"Use case {use_case_id} not found")
    if not sales_access.can(user, db, sales_access.CAP_EDIT, row[0]):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


def _require_ai_round(db: Session, use_case_id: int) -> None:
    """422 when the use case belongs to a generic round.

    Legacy use cases with no round resolve to 'ai' and pass. Runs after the
    access gates so out-of-scope/denied callers keep their 404/403.
    """
    try:
        AssessmentService.assert_ai_round_by_id(db, use_case_id)
    except GenericAssessmentError:
        raise HTTPException(status_code=422, detail=AI_SCORING_UNAVAILABLE) from None


@router.post("/", response_model=ScoredUseCaseResponse)
async def score_use_case(request: ScoringRequest, req: Request, db: Session = Depends(get_db)):
    """Score a use case using AI readiness assessment."""
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    _require_edit_for_use_case(user, db, request.use_case_id)
    _require_ai_round(db, request.use_case_id)
    try:
        result = await ScoringService.score_use_case(db, request.use_case_id, user=user)
        # Record audit log for successful scoring operation
        ip = None
        if req.client:
            ip = req.client.host
        user_id = user.get("user_id", 0) or 0
        username = user.get("username", "unknown")
        customer_ids = user.get("customer_ids")
        customer_id = customer_ids[0] if customer_ids else None
        db.add(AuditLog(
            user_id=user_id,
            username=username,
            action="score",
            customer_id=customer_id,
            target_id=request.use_case_id,
            details=f"Scoring triggered for use case {request.use_case_id}",
            ip_address=ip,
        ))
        db.commit()
        return result
    except ValueError as e:
        # 404-first: a MISSING use case is not a
        # capability denial — the same 404 as an out-of-scope id.
        if f"Use case {request.use_case_id} not found" == str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=403, detail=str(e))
    except TimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Scoring timed out: {e!s} Please try again or check your AI endpoint configuration."
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"AI scoring failed: {e!s}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scoring failed: {e!s}")


@router.get("/dimensions/", response_model=list[DimensionInfo])
def get_scoring_dimensions():
    """Return available scoring dimensions and their weights."""
    return ScoringService.DIMENSIONS


@router.get("/health/")
def scoring_health(req: Request):
    """Check if scoring service is properly configured. Requires authentication."""
    if get_user_from_request(req) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    from backend.config import get_settings
    settings = get_settings()

    configured = bool(settings.ai_endpoint and settings.ai_api_key)
    return {
        "configured": configured,
        "endpoint": settings.ai_endpoint,
        "model": settings.ai_model,
        "dimensions": len(ScoringService.DIMENSIONS),
    }


# ── Manual Scoring Override ──────────────────────────────────────────────────

@router.post("/manual/", response_model=ManualScoreResponse)
async def manual_score_use_case(request: ManualScoreRequest, req: Request, db: Session = Depends(get_db)):
    """Manually override a use case's scores (bypasses AI).

    Requires admin or customer owner role.
    """
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    _require_edit_for_use_case(user, db, request.use_case_id)
    _require_ai_round(db, request.use_case_id)

    try:
        use_case = ScoringService.manual_score(
            db, request.use_case_id, request.scores, request.overall_score, user
        )
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if use_case is None:
        raise HTTPException(status_code=404, detail=f"Use case {request.use_case_id} not found")

    return ManualScoreResponse(
        use_case=UseCaseResponse(**use_case.to_dict()),
        scores=ScoringResponse(**request.scores),
        is_manual=True,
    )


# ── Scoring Validation ──────────────────────────────────────────────────────

@router.post("/validate/", response_model=ScoringValidationResponse)
async def validate_scoring_response(request: ScoringValidationRequest, req: Request):
    """Validate scoring AI response for correctness.

    Checks score ranges, dimension completeness, and data consistency.
    """
    if get_user_from_request(req) is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    result = ScoringService.validate_scoring_response(request.scores)
    return ScoringValidationResponse(**result)


# ── Dimension Config Management ──────────────────────────────────────────────

@router.get("/dimensions/config/")
def get_dimension_configs(req: Request, version: str = "1", db: Session = Depends(get_db)):
    """Get dimension configuration versions.

    Returns active dimension configs for the specified version.
    """
    if get_user_from_request(req) is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    return ScoringService.get_active_dimension_configs(db, version)


@router.post("/dimensions/config/", response_model=DimensionConfigResponse)
async def create_dimension_config(config: DimensionConfigCreate, req: Request, db: Session = Depends(get_db)):
    """Create a new dimension configuration version.

    Only admins can create new dimension versions.
    """
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    if ScoringService.dimension_version_exists(db, config.version):
        raise HTTPException(status_code=409, detail=f"Version {config.version} already exists")

    return ScoringService.create_dimension_config(
        db, config.version, config.name, config.weight
    )


@router.get("/history/{use_case_id}/")
def get_score_history(use_case_id: int, req: Request, db: Session = Depends(get_db)):
    """Get full score history for a use case.

    Same read scope as the use case itself: missing or out-of-scope is 404.
    """
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if UseCaseService.get_by_id(db, use_case_id, user=user) is None:
        raise HTTPException(status_code=404, detail="Use case not found")
    return ScoringService.get_score_history(db, use_case_id)


@router.put("/history/{history_id}/approve/", response_model=ManualScoreResponse)
async def approve_score_history(history_id: int, req: Request, db: Session = Depends(get_db)):
    """Approve a score from the review workflow."""
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    history = ScoringService.get_score_history_entry(db, history_id)
    if not history:
        raise HTTPException(status_code=404, detail="Score history entry not found")
    _require_edit_for_use_case(user, db, history.use_case_id)

    if history.status != "draft":
        raise HTTPException(status_code=400, detail=f"Cannot approve score in '{history.status}' status")

    use_case = ScoringService.approve_history(db, history)

    return ManualScoreResponse(
        use_case=UseCaseResponse(**use_case.to_dict()) if use_case else None,
        scores=ScoringResponse(
            dimension_scores=history.dimension_scores,
            overall_score=history.score,
            reasoning=history.reasoning,
            scored_at=history.scored_at.isoformat() if history.scored_at else None,
            scored_by=history.scored_by,
        ),
        is_manual=True,
    )


@router.put("/history/{history_id}/reject/", response_model=dict)
async def reject_score_history(history_id: int, req: Request, db: Session = Depends(get_db)):
    """Reject a score from the review workflow."""
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")

    history = ScoringService.get_score_history_entry(db, history_id)
    if not history:
        raise HTTPException(status_code=404, detail="Score history entry not found")
    _require_edit_for_use_case(user, db, history.use_case_id)

    if history.status != "draft":
        raise HTTPException(status_code=400, detail=f"Cannot reject score in '{history.status}' status")

    ScoringService.reject_history(db, history)

    return {
        "message": f"Score {history_id} rejected",
        "status": history.status,
        "use_case_id": history.use_case_id,
    }
