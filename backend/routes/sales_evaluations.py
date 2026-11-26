"""Sales evaluations API routes.

CRUD endpoints for cross-domain sales evaluations:
    GET  /api/sales-evaluations/           — list evaluations for customer
    POST /api/sales-evaluations/           — create new evaluation (triggers engine)
    GET  /api/sales-evaluations/{id}       — get full evaluation
    PUT  /api/sales-evaluations/{id}       — update evaluation name/status
    DELETE /api/sales-evaluations/{id}     — delete evaluation

Persona-driven evaluations:
    GET  /api/sales-evaluations/personas/  — centralized persona registry
    POST /api/sales-evaluations/preview/   — pre-generation view (no persist)
    persona on POST / (audience context) and GET / (?persona= filter)
"""


from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.sales_evaluation import SalesEvaluation
from backend.models.use_case import Customer
from backend.schemas.sales_evaluation import (
    SalesEvaluationCreate,
    SalesEvaluationPreviewRequest,
    SalesEvaluationResponse,
    SalesEvaluationUpdate,
    SalesPersona,
)
from backend.services import customer_access, sales_access
from backend.services.evaluation_engine import (
    create_sales_evaluation,
    preview_sales_evaluation,
)
from backend.services.sales_personas import validate_persona

router = APIRouter(prefix="/api/sales-evaluations", tags=["sales-evaluations"])


def _evaluation_in_scope_or_404(request: Request, evaluation: SalesEvaluation,
                                db: Session) -> dict:
    """By-id gate: an out-of-scope evaluation is the same 404 as a missing one.

    Keeps the existing order (lookup 404, then 401) so only the out-of-scope
    403 changes; returns the authenticated user.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not customer_access.can_read(user, db, evaluation.customer_id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return user


def _require_edit(user: dict, db: Session, customer_id: int) -> None:
    """403 unless the caller holds the resolver's EDIT capability (in-scope
    capability denial — an auditor junction is read-only)."""
    if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to modify this customer",
        )


def _require_customer_write(request: Request, customer_id: int, db: Session) -> dict:
    """WRITE gate for sales-evaluation mutations (shift-to-global-customer-mgmt
    phase 3 — closes the auditor write gap).

    ``customer_access.read_auth_or_404`` is a READ gate (any in-scope caller passes,
    including an ``auditor`` junction role). A "read gate is not a write gate"
    rule: mutations additionally require the central
    resolver's EDIT capability, which an auditor does NOT have (level =
    auditor). System admins still pass; ps_admin is confined (no sales
    capability); a legacy owner/member junction keeps working (no lockout).
    """
    user = customer_access.read_auth_or_404(request, db, customer_id)
    _require_edit(user, db, customer_id)
    return user


# ── persona registry + pre-generation preview ─────────────────────
# NOTE: declared before /{evaluation_id} so "personas"/"preview" never hit the
# int path-parameter route.


@router.get("/personas/", response_model=list[SalesPersona])
def list_personas(request: Request):
    """List the centralized sales persona registry.

    Global catalog (not customer data): auth-gated (401) but not
    customer-gated. The registry in backend/services/sales_personas.py is
    the single source of truth — the frontend consumes this endpoint.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    from backend.services.sales_personas import list_personas as _registry

    return _registry()


@router.post("/preview/")
def preview_evaluation(
    body: SalesEvaluationPreviewRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Pre-generation view: selected customer, persona,
    available related intelligence, generation intent, and the sections that
    WOULD be generated — computed without persisting anything.
    """
    customer_access.read_auth_or_404(request, db, body.customer_id)

    err = validate_persona(body.persona)
    if err:
        raise HTTPException(status_code=422, detail=err)

    customer = db.query(Customer).filter(Customer.id == body.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    return preview_sales_evaluation(db, body.customer_id, persona_id=body.persona)


@router.get("/", response_model=list[SalesEvaluationResponse])
def list_evaluations(
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
    persona: str | None = None,
):
    """List all evaluations for a customer (auth-gated).

    Optional ``persona`` query param filters by the audience
    context the evaluation was generated for.
    """
    customer_access.read_auth_or_404(request, db, customer_id)

    query = db.query(SalesEvaluation).filter(
        SalesEvaluation.customer_id == customer_id
    )
    if persona is not None:
        query = query.filter(SalesEvaluation.persona == persona)
    evaluations = query.order_by(SalesEvaluation.created_at.desc()).all()
    return evaluations


@router.post("/", response_model=SalesEvaluationResponse)
def create_evaluation(
    body: SalesEvaluationCreate,
    customer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new sales evaluation (triggers the engine).

    Pulls organizational readiness + environment knowledge,
    runs gap/risk/growth analysis, persists result.

    ``persona`` (body) selects the audience context; the persona id
    is persisted with the evaluation (historical context) and the
    generated sections are persona-tailored.
    """
    _require_customer_write(request, customer_id, db)

    err = validate_persona(body.persona)
    if err:
        raise HTTPException(status_code=422, detail=err)

    # Verify customer exists
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    evaluation = create_sales_evaluation(
        db=db,
        customer_id=customer_id,
        evaluation_name=body.evaluation_name,
        persona_id=body.persona,
    )
    return evaluation


@router.get("/{evaluation_id}", response_model=SalesEvaluationResponse)
def get_evaluation(
    evaluation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get full evaluation with gap/risk/growth details (404-first)."""
    evaluation = db.query(SalesEvaluation).filter(
        SalesEvaluation.id == evaluation_id
    ).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    _evaluation_in_scope_or_404(request, evaluation, db)
    return evaluation


@router.put("/{evaluation_id}", response_model=SalesEvaluationResponse)
def update_evaluation(
    evaluation_id: int,
    body: SalesEvaluationUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update evaluation name/status (404-first; in-scope EDIT else 403)."""
    evaluation = db.query(SalesEvaluation).filter(
        SalesEvaluation.id == evaluation_id
    ).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    user = _evaluation_in_scope_or_404(request, evaluation, db)
    _require_edit(user, db, evaluation.customer_id)  # type: ignore[arg-type]

    if body.evaluation_name is not None:
        evaluation.evaluation_name = body.evaluation_name
    if body.status is not None:
        evaluation.status = body.status

    from datetime import datetime
    evaluation.updated_at = datetime.now(UTC)

    db.commit()
    db.refresh(evaluation)
    return evaluation


@router.delete("/{evaluation_id}", response_model=dict)
def delete_evaluation(
    evaluation_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete an evaluation (404-first; in-scope EDIT else 403)."""
    evaluation = db.query(SalesEvaluation).filter(
        SalesEvaluation.id == evaluation_id
    ).first()
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    user = _evaluation_in_scope_or_404(request, evaluation, db)
    _require_edit(user, db, evaluation.customer_id)  # type: ignore[arg-type]

    db.delete(evaluation)
    db.commit()
    return {"status": "deleted", "id": evaluation_id}
