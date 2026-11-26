"""Assessment-round service (simplified lifecycle).

One assessment round per customer is the working set ("the assessment you
are working on"). To start a new round the current one must be archived
first (or its use cases deleted). Archived rounds are read-only: their use
cases cannot be edited, scored, or deleted, but they remain exportable
through the established export endpoints.

Round types: ``ai`` (the default — AI readiness /
use-case scoring) or ``generic`` (non-AI customer discovery). The
one-active-round invariant spans both types. AI-only surfaces (AI scoring,
manual dimension scoring, prediction generation) refuse generic-round use
cases via ``assert_ai_round``; a use case with no round (``assessment_id``
NULL — pre-round-linkage legacy) resolves to ``ai``.
"""
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.models.use_case import Customer, CustomerAssessment, UseCase

ASSESSMENT_TYPES = ("ai", "generic")
_TYPE_LABELS = {"ai": "AI", "generic": "Generic"}
AI_SCORING_UNAVAILABLE = "AI scoring is not available on generic assessments"


class GenericAssessmentError(Exception):
    """An AI-only surface was asked to act on a generic-round use case
    (routes map this to 422 with ``AI_SCORING_UNAVAILABLE``).

    Deliberately NOT a ValueError: existing ``except ValueError`` handlers
    map to 400/403 and must not swallow it.
    """

    def __init__(self) -> None:
        super().__init__(AI_SCORING_UNAVAILABLE)


class AssessmentService:
    """Business logic for customer assessment rounds."""

    @staticmethod
    def get_active(db: Session, customer_id: int) -> CustomerAssessment | None:
        return (
            db.query(CustomerAssessment)
            .filter(CustomerAssessment.customer_id == customer_id,
                    CustomerAssessment.status == "active")
            .first()
        )

    @staticmethod
    def get_by_id(db: Session, assessment_id: int) -> CustomerAssessment | None:
        """Return the assessment with this id (any customer), or None."""
        return (
            db.query(CustomerAssessment)
            .filter(CustomerAssessment.id == assessment_id)
            .first()
        )

    @staticmethod
    def get_by_id_for_customer(
        db: Session, assessment_id: int, customer_id: int
    ) -> CustomerAssessment | None:
        """Return the assessment with this id for this customer, or None."""
        return (
            db.query(CustomerAssessment)
            .filter(
                CustomerAssessment.id == assessment_id,
                CustomerAssessment.customer_id == customer_id,
            )
            .first()
        )

    @staticmethod
    def list_for_customer(db: Session, customer_id: int) -> list[dict]:
        rows = (
            db.query(CustomerAssessment)
            .filter(CustomerAssessment.customer_id == customer_id)
            .order_by(CustomerAssessment.created_at.desc())
            .all()
        )
        return [r.to_dict() for r in rows]

    @staticmethod
    def create(
        db: Session,
        customer_id: int,
        name: str,
        username: str | None = None,
        assessment_type: str = "ai",
        purpose: str | None = None,
    ) -> CustomerAssessment:
        """Create a new round. Fails if an active round (of ANY type) already
        exists — the current round must be archived (or its use cases
        deleted) first. The message names the active round's type.

        The check-then-insert window is pre-existing and unchanged (no new
        concurrency guard; R3)."""
        if assessment_type not in ASSESSMENT_TYPES:
            raise ValueError(
                f"Unknown assessment type '{assessment_type}'. "
                f"Must be one of: {', '.join(ASSESSMENT_TYPES)}"
            )
        active = AssessmentService.get_active(db, customer_id)
        if active is not None:
            label = _TYPE_LABELS.get(active.assessment_type or "ai", "AI")
            raise ValueError(
                f"This customer already has an active assessment ({label}). "
                "Archive it (or delete its use cases) before starting a new one."
            )
        assessment = CustomerAssessment(
            customer_id=customer_id,
            name=name,
            status="active",
            assessment_type=assessment_type,
            purpose=purpose,
            created_by=username,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return assessment

    @staticmethod
    def ensure_active(db: Session, customer_id: int, username: str | None = None) -> CustomerAssessment:
        """Return the active round, auto-creating the first one if missing."""
        assessment = AssessmentService.get_active(db, customer_id)
        if assessment is not None:
            return assessment
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        count = db.query(CustomerAssessment).filter(
            CustomerAssessment.customer_id == customer_id
        ).count()
        base_name = customer.name if customer else f"Customer {customer_id}"
        return AssessmentService.create(
            db, customer_id, f"{base_name} — Assessment {count + 1}", username
        )

    @staticmethod
    def archive(db: Session, assessment_id: int, username: str | None = None) -> CustomerAssessment:
        assessment = db.query(CustomerAssessment).filter(CustomerAssessment.id == assessment_id).first()
        if not assessment:
            raise ValueError("Assessment not found")
        if assessment.status != "active":
            raise ValueError("Assessment is already archived")
        assessment.status = "archived"
        assessment.archived_at = datetime.now(UTC).replace(tzinfo=None)
        db.commit()
        db.refresh(assessment)
        return assessment

    @staticmethod
    def is_archived(db: Session, use_case: UseCase) -> bool:
        """True if the use case belongs to an archived assessment round."""
        if use_case.assessment_id is None:
            return False
        assessment = (
            db.query(CustomerAssessment)
            .filter(CustomerAssessment.id == use_case.assessment_id)
            .first()
        )
        return bool(assessment and assessment.status == "archived")

    @staticmethod
    def assert_not_archived(db: Session, use_case: UseCase) -> None:
        """Raise ValueError when the use case's assessment round is archived
        (archived data is export-only)."""
        if AssessmentService.is_archived(db, use_case):
            name = use_case.assessment.name if use_case.assessment else "(unknown)"
            raise ValueError(
                f"Assessment '{name}' is archived — its use cases are read-only. "
                "Use the export endpoints to extract this data."
            )

    @staticmethod
    def round_type_for(db: Session, use_case: UseCase) -> str:
        """Resolve a use case's round type (R5): no round (legacy NULL
        ``assessment_id``) → ``'ai'``; otherwise the linked round's type."""
        if use_case.assessment_id is None:
            return "ai"
        row = (
            db.query(CustomerAssessment.assessment_type)
            .filter(CustomerAssessment.id == use_case.assessment_id)
            .first()
        )
        return (row[0] if row and row[0] else "ai")

    @staticmethod
    def is_generic(db: Session, use_case: UseCase) -> bool:
        return AssessmentService.round_type_for(db, use_case) == "generic"

    @staticmethod
    def assert_ai_round(db: Session, use_case: UseCase) -> None:
        """Raise GenericAssessmentError when the use case belongs to a
        generic round (AI-only surfaces → 422)."""
        if AssessmentService.is_generic(db, use_case):
            raise GenericAssessmentError()

    @staticmethod
    def assert_ai_round_by_id(db: Session, use_case_id: int) -> None:
        """``assert_ai_round`` by id; a missing use case is left to the
        caller's existing not-found handling."""
        uc = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if uc is not None:
            AssessmentService.assert_ai_round(db, uc)
