"""Advanced analytics routes.

All endpoints require authentication. Department trends and score-impact
correlations accept an optional ``customer_id`` scope. Unscoped calls return
global data for admins and the caller's central READ scope
(``sales_access.customer_scope``) for everyone else, so non-admins never see
aggregates for customers outside their scope.

Saved predictions can be deleted by global admins or the owning customer's
owner via ``DELETE /api/analytics/predictions/{prediction_id}/``.

By-id and customer-id lookups are 404-first (R4/Q7): a record or customer
outside the caller's central READ scope returns the same 404 as a missing one.
In-scope capability denials keep their exact 403.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.services import customer_access, sales_access
from backend.services.analytics_service import AnalyticsService
from backend.services.assessment_service import AI_SCORING_UNAVAILABLE, GenericAssessmentError
from backend.services.insight_service import InsightService
from backend.services.prediction_service import AIPredictionService
from backend.services.use_case_service import UseCaseService

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _require_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _scope_kwargs(db: Session, user: dict, customer_id: int | None) -> dict[str, Any]:
    """Resolve analytics scoping for the caller.

    - Explicit customer_id: requires central READ on the customer (else the
      same 404 as a missing customer — 404-first, R4/Q7).
    - No customer_id: admins get global; everyone else gets their central
      READ scope (``sales_access.customer_scope``, resolved once).
    """
    if customer_id is not None:
        if not customer_access.can_read(user, db, customer_id):
            # 404-first (R4/Q7): out of scope == missing.
            raise HTTPException(status_code=404, detail="Customer not found")
        return {"customer_id": customer_id}
    if sales_access.is_unrestricted(user):
        return {}
    return {"customer_ids": sorted(sales_access.customer_scope(user, db))}


@router.get("/readiness-insight/")
def get_readiness_insight(
    request: Request,
    customer_id: int = Query(...),
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    customer_access.read_or_404(db, user, customer_id)
    insight = InsightService.get_cached(db, customer_id)
    state = insight["state"] if insight else InsightService.scope_state(db, customer_id)
    return {
        "insight": insight,
        "state": state,
        "stale": insight["stale"] if insight else False,
    }


@router.post("/readiness-insight/generate/")
async def generate_readiness_insight(
    request: Request,
    customer_id: int = Query(...),
    db: Session = Depends(get_db),
):
    user = _require_user(request)
    customer_access.read_or_404(db, user, customer_id)
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    try:
        return await InsightService.generate(
            db, customer_id, generated_by=user.get("username") or "system"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"Insight generation failed: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Insight generation failed: {exc}")


@router.get("/predictions/")
def get_saved_predictions(
    request: Request,
    customer_id: int | None = Query(None, description="Filter by customer ID"),
    db: Session = Depends(get_db),
):
    """List model-generated predictions (customer-scoped, newest first)."""
    user = _require_user(request)
    return AIPredictionService.list_saved(db, **_scope_kwargs(db, user, customer_id))


@router.post("/predictions/generate/")
async def generate_saved_prediction(
    request: Request,
    use_case_id: int = Query(..., description="Use case to predict for"),
    days: int = Query(45, ge=1, le=730, description="Prediction horizon in days"),
    db: Session = Depends(get_db),
):
    """Generate a readiness prediction via the configured model and persist it.

    The model (AI endpoint from .env) determines the predicted score; the
    application only validates and stores the result.
    """
    user = _require_user(request)
    uc = UseCaseService.get_by_id(db, use_case_id)
    if not uc:
        raise HTTPException(status_code=404, detail="Use case not found")
    if uc.customer_id is not None and not customer_access.can_read(user, db, uc.customer_id):
        raise HTTPException(status_code=404, detail="Use case not found")
    if not sales_access.can(user, db, sales_access.CAP_EDIT, uc.customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    try:
        return await AIPredictionService.generate(db, use_case_id, days, user)
    except GenericAssessmentError:
        raise HTTPException(status_code=422, detail=AI_SCORING_UNAVAILABLE) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"Prediction generation failed: {e!s}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction generation failed: {e!s}")


@router.delete("/predictions/{prediction_id}/")
def delete_saved_prediction(
    prediction_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a saved model-generated prediction."""
    user = _require_user(request)
    prediction = AIPredictionService.get_by_id(db, prediction_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    if prediction.customer_id is None:
        if not user.get("is_admin"):
            raise HTTPException(status_code=403, detail="Prediction has no customer assignment")
    else:
        if not customer_access.can_read(user, db, prediction.customer_id):
            raise HTTPException(status_code=404, detail="Prediction not found")
        try:
            AIPredictionService.assert_delete_access(db, user, prediction.customer_id)
        except ValueError as e:
            raise HTTPException(status_code=403, detail=str(e))
        if not sales_access.can(user, db, sales_access.CAP_EDIT, prediction.customer_id):
            raise HTTPException(status_code=403, detail="Not authorized to modify this customer")
    AIPredictionService.delete(db, prediction_id)
    return {"message": f"Prediction {prediction_id} deleted"}


@router.get("/predictive/{use_case_id}/")
def get_trend_prediction(
    use_case_id: int,
    request: Request,
    days: int = Query(30, ge=1, le=730, description="Forecast horizon in days (default 30)"),
    db: Session = Depends(get_db),
):
    """Predict future scores based on historical trend (access-controlled).

    ``days`` selects the forecast horizon. The customer analytics stack
    requests three: 45 (30–60 days), 135 (3–6 months), 270 (6–12 months).
    """
    user = _require_user(request)
    use_case = UseCaseService.get_by_id(db, use_case_id)
    if not use_case:
        raise HTTPException(status_code=404, detail="Use case not found")
    if use_case.customer_id is None:
        # Unassigned use cases have no customer context — whatever the central
        # policy answers for a customer-less READ (admin-only; G6).
        if not sales_access.can(user, db, sales_access.CAP_READ, None):
            raise HTTPException(status_code=403, detail="Use case has no customer assignment")
    elif not customer_access.can_read(user, db, use_case.customer_id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Use case not found")
    result = AnalyticsService.get_trend_prediction(db, use_case_id, days=days)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/department-trends/")
def get_department_trends(
    request: Request,
    customer_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Get department-level trend analysis (customer-scoped, access-controlled)."""
    user = _require_user(request)
    return AnalyticsService.get_department_trends(db, **_scope_kwargs(db, user, customer_id))


@router.get("/correlations/")
def get_score_impact_correlation(
    request: Request,
    customer_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Analyze correlation between business impact and readiness scores (scoped)."""
    user = _require_user(request)
    # "error" dicts (e.g. no scored use cases in scope) intentionally stay
    # 200: the frontend renders an empty state for them.
    return AnalyticsService.get_score_impact_correlation(db, **_scope_kwargs(db, user, customer_id))
