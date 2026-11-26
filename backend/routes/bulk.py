"""REST API routes for bulk operations and templates."""


from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.use_case import UseCase
from backend.services import sales_access
from backend.services.assessment_service import (
    AI_SCORING_UNAVAILABLE,
    GenericAssessmentError,
)
from backend.services.scoring import ScoringService
from backend.services.use_case_service import UseCaseService
from backend.templates import TEMPLATES

router = APIRouter(prefix="/api/bulk", tags=["bulk"])


def _require_user(request: Request) -> dict:
    """Return authenticated user or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("/score-multiple/")
def bulk_score_use_cases(
    use_case_ids: list[int],
    req: Request,
    db: Session = Depends(get_db),
):
    """Score multiple use cases in bulk.

    Requires authentication. Each use case is access-checked against the
    central policy's CAP_EDIT (see ScoringService.assert_scoring_access):
    unauthorized ids are reported as per-item errors and are never scored.
    """
    user = get_user_from_request(req)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    results = []
    errors = []

    for use_case_id in use_case_ids:
        # Existing per-use-case access rules first (their messages are part
        # of the contract), then the resolver write gate on the customer
        # derived from the persisted use case. Denied ids are reported per
        # item and never scored; a missing use case falls through to the
        # service layer (404-style error).
        target = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if target is not None:
            # an id the caller cannot reach (out of read scope — or an
            # unassigned use case for a non-admin) reports the SAME per-item
            # error as a missing id, so a batch probe cannot confirm
            # existence. In-scope capability denials (the auditor rule) keep
            # their exact messages.
            if user.get("is_admin") != 1 and (
                target.customer_id is None
                or not sales_access.can(user, db, sales_access.CAP_READ, target.customer_id)
            ):
                errors.append({"use_case_id": use_case_id,
                               "error": f"Use case {use_case_id} not found"})
                continue
            try:
                ScoringService.assert_scoring_access(db, user, target)
            except ValueError as e:
                errors.append({"use_case_id": use_case_id, "error": str(e)})
                continue
            if target.customer_id is not None and not sales_access.can(
                user, db, sales_access.CAP_EDIT, target.customer_id
            ):
                errors.append({
                    "use_case_id": use_case_id,
                    "error": "Not authorized to modify this customer",
                })
                continue
        try:
            result = ScoringService.score_use_case_sync(db, use_case_id, user=user)
            results.append(result)
        except GenericAssessmentError:
            # generic-round use case — AI scoring refused at
            # the shared seam; reported per item with the exact message, never
            # scored, and the insight trigger below never sees it.
            errors.append({
                "use_case_id": use_case_id,
                "error": AI_SCORING_UNAVAILABLE,
            })
        except ValueError as e:
            # Access/permission violations — reported per item, never scored
            errors.append({
                "use_case_id": use_case_id,
                "error": str(e),
            })
        except Exception as e:
            errors.append({
                "use_case_id": use_case_id,
                "error": str(e),
            })

    if results:
        successful_ids = [result["use_case"]["id"] for result in results]
        customer_ids = {
            customer_id for (customer_id,) in db.query(UseCase.customer_id).filter(
                UseCase.id.in_(successful_ids),
                UseCase.customer_id.isnot(None),
            ).distinct().all()
        }
        from backend.services.insight_service import InsightService
        for customer_id in customer_ids:
            InsightService.trigger_async(
                customer_id,
                "bulk",
                generated_by=user.get("username") or "system",
            )

    return {
        "success_count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
    }


@router.get("/templates/")
def get_templates(req: Request, db: Session = Depends(get_db)):
    """Get available use case templates."""
    _require_user(req)
    return {
        "templates": TEMPLATES,
        "count": len(TEMPLATES),
    }


@router.get("/templates/{template_id}/")
def get_template(template_id: str, req: Request, db: Session = Depends(get_db)):
    """Get a specific template by ID."""
    _require_user(req)
    if template_id not in TEMPLATES:
        raise HTTPException(status_code=404, detail="Template not found")

    return {
        "id": template_id,
        **TEMPLATES[template_id],
    }


class CreateFromTemplateRequest(BaseModel):
    """Request body for creating a use case from a template."""
    template_id: str
    title: str
    department: str
    customer_id: int | None = None


@router.post("/create-from-template/")
def create_from_template(
    request: CreateFromTemplateRequest,
    req: Request,
    db: Session = Depends(get_db),
):
    """Create a new use case from a template.

    Requires authentication. When a customer_id is provided, the caller's
    junction access is enforced by UseCaseService.create (non-admins need
    owner/member role).
    """
    user = _require_user(req)
    if request.template_id not in TEMPLATES:
        raise HTTPException(status_code=404, detail="Template not found")

    template = TEMPLATES[request.template_id]

    # 404-first: a customer the caller cannot reach is the same 404
    # as a missing one; grant holders keep the in-scope capability 403.
    if (
        request.customer_id is not None
        and user.get("is_admin") != 1
        and request.customer_id not in (user.get("customer_ids") or [])
    ):
        raise HTTPException(status_code=404, detail="Customer not found")
    # Callers with no relationship to the customer fall through to the
    # service's own access error; a grant (e.g. auditor) must pass the gate.
    if (
        request.customer_id is not None
        and request.customer_id in (user.get("customer_ids") or [])
        and not sales_access.can(user, db, sales_access.CAP_EDIT, request.customer_id)
    ):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")

    use_case = UseCaseService.create(
        db,
        title=request.title,
        department=request.department,
        goals=template["default_goals"],
        challenges=template["default_challenges"],
        pain_points=template["default_pain_points"],
        user=user,
        customer_id=request.customer_id,
    )

    return use_case.to_dict()
