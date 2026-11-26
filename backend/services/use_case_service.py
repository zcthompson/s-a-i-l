"""Service layer for use case CRUD operations.

Multi-customer support: non-admin users are filtered by the central
policy's READ scope (``sales_access.customer_scope``).
"""

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import asc, desc
from sqlalchemy.orm import Session

from backend.auth import _user_has_dept_access as _check_dept_access
from backend.models.use_case import UseCase
from backend.services import record_cleanup, sales_access

logger = logging.getLogger(__name__)

UNASSIGNED_ADMIN_ONLY = "Unassigned use cases are admin-only"


def assert_assigned_or_admin(customer_id: int | None, user: dict | None) -> None:
    """Write gate for use cases with no customer (R2): system admin only.

    ``user is None`` is a trusted in-process caller and is not decided here;
    assigned use cases are gated by their customer's capability check.
    Reads of unassigned use cases are denied by ``UseCaseService.get_by_id``
    through the central policy (``sales_access.can`` is admin-only for a
    customer-less target), so they surface as 404 like a missing row.
    """
    if customer_id is not None or user is None or user.get("is_admin") == 1:
        return
    raise HTTPException(status_code=403, detail=UNASSIGNED_ADMIN_ONLY)


def _user_can_access_dept(user: dict | None, department: str | None,
                          customer_name: str | None = None) -> bool:
    """Check if user has permission to access a department, customer-scoped.

    Returns True if:
    - No restrictions configured (open access)
    - User has 'all' access (admin)
    - Department is in user's global allowed list
    - Department is in user's allowed list for this specific customer
    - User is anonymous (auth disabled)
    """
    if user is None or department is None:
        return True

    if _check_dept_access(user, department):
        return True

    # Customer-scoped check: department is allowed for this specific customer
    if customer_name:
        customer_deps = user.get("customer_allowed_departments", {})
        if customer_name in customer_deps and department in customer_deps[customer_name]:
            return True

    return False


class UseCaseService:
    """Business logic for use case operations."""

    @staticmethod
    def create(db: Session, title: str,
               description: str | None = None,
               department: str | None = None,
               department_id: int | None = None,
               status: str | None = None,
               goals: list[str] | None = None,
               challenges: list[str] | None = None,
               pain_points: list[str] | None = None,
               impact_category: str | None = None,
               impact_description: str | None = None,
               estimated_savings: float | None = None,
               estimated_revenue: float | None = None,
               timeline_estimate: str | None = None,
               user: dict | None = None,
               scores: dict | None = None,
               overall_score: float | None = None,
               customer_id: int | None = None,
               # Technology tracking fields (WP27+)
               tech_stack: dict | None = None,
               devices: dict | None = None,
               software: dict | None = None,
               vendor: str | None = None) -> UseCase:
        """Create a new use case with customer isolation.
        
        Prefer department_id (FK to Department model). The legacy
        department string field is deprecated — it will be auto-
        resolved from department_id when both are provided.
        """
        created_by = user.get("username") if user else "anonymous"
        
        # Enforce junction access for non-admin users
        if user and user.get("is_admin") != 1 and customer_id is not None:
            junction_roles = user.get("junction_roles", {})
            user_role = junction_roles.get(customer_id)
            if not user_role or user_role not in ("owner", "member"):
                raise HTTPException(status_code=403, detail=f"No access to customer {customer_id}")
        
        # R2: a customer-less use case is admin-only
        assert_assigned_or_admin(customer_id, user)

        use_case = UseCase(
            title=title,
            description=description,
            customer_id=customer_id,
        )
        # Attach to the customer's active assessment round (auto-created on
        # first use — one active round per customer is the working set).
        if customer_id is not None:
            from backend.services.assessment_service import AssessmentService
            assessment = AssessmentService.ensure_active(
                db, customer_id, user.get("username") if user else None
            )
            use_case.assessment_id = assessment.id
        # Set department via new method (handles deprecation logic)
        use_case.set_department(department, department_id)
        # Set remaining fields directly
        use_case.status = status
        use_case.goals = goals
        use_case.challenges = challenges
        use_case.pain_points = pain_points
        use_case.impact_category = impact_category
        use_case.impact_description = impact_description
        use_case.estimated_savings = estimated_savings
        use_case.estimated_revenue = estimated_revenue
        use_case.timeline_estimate = timeline_estimate
        # Technology tracking fields (WP27+)
        use_case.tech_stack = tech_stack
        use_case.devices = devices
        use_case.software = software
        use_case.vendor = vendor
        use_case.scores = scores
        use_case.overall_score = overall_score
        use_case.created_by = created_by
        db.add(use_case)
        db.commit()
        db.refresh(use_case)
        return use_case

    @staticmethod
    def get_by_id(db: Session, use_case_id: int, user: dict | None = None) -> UseCase | None:
        """Get a use case by ID with department and customer isolation.

        With a ``user`` the caller must hold central read access to the use
        case's customer; otherwise the row is reported as missing (None), so
        out-of-scope reads are indistinguishable from absent ones (R4). A
        customer-less use case is readable only by system admin (R2).
        """
        use_case = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if use_case:
            customer_name = use_case.customer.name if use_case.customer else None
            # type: ignore[union-attr] — SQLAlchemy attribute resolves to str at runtime
            if not _user_can_access_dept(user, str(use_case.department), customer_name):
                return None  # Access denied
            if user is not None and not sales_access.can(
                user, db, sales_access.CAP_READ, use_case.customer_id
            ):
                return None  # Out of scope (or unassigned for a non-admin)
        return use_case

    # ── Multi-customer support ────────────────────────────────────────────────

    @staticmethod
    def get_all(db: Session, skip: int = 0, limit: int = 100,
                department: str | None = None,
                status: str | None = None,
                search: str | None = None,
                customer_id: int | None = None,
                user: dict | None = None,
                sort: str = "updated") -> list[UseCase]:
        """Get all use cases with optional filtering, department and customer isolation.

        ``sort`` selects the ordering (updated|created|score|title) with a
        unique ``id`` tie-breaker so equal values do not destabilize
        pagination pages (BE-03/FE-03).
        """
        query = db.query(UseCase)

        # Apply department isolation based on user permissions (customer-scoped)
        if user is not None:
            allowed = user.get("allowed_departments")
            if allowed is not None and "all" not in allowed:
                if not user.get("customer_allowed_departments"):
                    query = query.filter(UseCase.department.in_(allowed))

        # Apply user-customer isolation. An explicit customer_id is always
        # honored — for non-admins it is further constrained to their
        # accessible customers (never widened).
        if user is not None and not sales_access.is_unrestricted(user):
            # Central READ scope (Part 13 DV5), computed once per call.
            user_customer_ids = sales_access.customer_scope(user, db)
            if customer_id is not None:
                if customer_id not in user_customer_ids:
                    return []
                query = query.filter(UseCase.customer_id == customer_id)
            elif user_customer_ids:
                query = query.filter(UseCase.customer_id.in_(user_customer_ids))
            else:
                # Non-admin with no access: show nothing
                return []
        elif customer_id is not None:
            # Admin or no user: respect an explicit customer_id filter.
            # ``is not None`` (not truthiness) so a zero/negative ID is a
            # *documented validation error at the route*, never silently
            # widened to the global set (BE-02).
            query = query.filter(UseCase.customer_id == customer_id)

        if department:
            query = query.filter(UseCase.department == department)
        if status:
            query = query.filter(UseCase.status == status)
        if search:
            query = query.filter(
                UseCase.title.ilike(f"%{search}%") |
                UseCase.description.ilike(f"%{search}%")
            )

        # Unique tie-breaker after the sort key so equal values do not
        # destabilize pagination pages (BE-03). SQLite treats NULLs as the
        # smallest value, so a DESC score puts unscored rows last — a stable,
        # documented order for the FE's "Sort by Score" page control.
        if sort == "created":
            order = desc(UseCase.created_at)
        elif sort == "score":
            order = desc(UseCase.overall_score)
        elif sort == "title":
            order = asc(UseCase.title)
        else:  # "updated" (default)
            order = desc(UseCase.updated_at)
        return (
            query.order_by(order, UseCase.id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @staticmethod
    def update(
        db: Session,
        use_case_id: int,
        user: dict | None = None,
        **kwargs,
    ) -> UseCase | None:
        """Update a use case."""
        use_case = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if not use_case:
            return None

        # R2: a customer-less use case is admin-only
        assert_assigned_or_admin(use_case.customer_id, user)

        # Archived assessment rounds are read-only (export only)
        from backend.services.assessment_service import AssessmentService
        AssessmentService.assert_not_archived(db, use_case)

        # Enforce junction role restrictions for non-admin users
        if user and user.get("is_admin") != 1 and use_case.customer_id is not None:
            junction_roles = user.get("junction_roles", {})
            user_role = junction_roles.get(use_case.customer_id)
            if user_role == "auditor":
                raise HTTPException(status_code=403, detail="Auditors have read-only access")

        # R3: a use case never moves between customers (the route rejects a
        # differing customer_id; this keeps any other caller from doing it)
        kwargs.pop("customer_id", None)

        old_status = use_case.status
        for key, value in kwargs.items():
            if hasattr(use_case, key) and value is not None:
                setattr(use_case, key, value)

        updated_by = user.get("username") if user else "anonymous"
        use_case.updated_by = updated_by
        use_case.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(use_case)

        # Broadcast customer-level notification on status change
        if (
            old_status != use_case.status
            and use_case.customer_id
        ):
            from backend.services.collaboration_service import CollaborationService

            message = (
                f"Use case '{use_case.title}' status changed from "
                f"'{old_status}' to '{use_case.status}'."
            )
            CollaborationService.broadcast_to_customer(
                db, use_case.customer_id, "status_change", message
            )

            if use_case.status == "completed" and AssessmentService.is_generic(db, use_case):
                # Part 13 WS5 (R5): the org-wide readiness insight is
                # AI-round only — skip (background path: never raise).
                logger.warning(
                    "Readiness insight trigger skipped: use case %s (customer %s) "
                    "belongs to a generic assessment",
                    use_case.id, use_case.customer_id,
                )
            elif use_case.status == "completed":
                from backend.services.insight_service import InsightService
                InsightService.trigger_async(
                    use_case.customer_id,
                    "full",
                    generated_by=(user.get("username") or "system") if user else "system",
                )

        return use_case

    @staticmethod
    def delete(db: Session, use_case_id: int, user: dict | None = None) -> bool:
        """Delete a use case.

        Non-admin callers need the owner role on the use case's customer
        (CustomerUser junction is authoritative — same pattern as create/update).
        """
        use_case = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if not use_case:
            return False
        # R2: a customer-less use case is admin-only
        assert_assigned_or_admin(use_case.customer_id, user)
        # Archived assessment rounds are read-only (export only)
        from backend.services.assessment_service import AssessmentService
        AssessmentService.assert_not_archived(db, use_case)
        # Enforce owner/admin for non-admin deletions
        if user and user.get("is_admin") != 1 and use_case.customer_id is not None:
            junction_roles = user.get("junction_roles", {})
            user_role = junction_roles.get(use_case.customer_id)
            if user_role != "owner":
                raise HTTPException(
                    status_code=403,
                    detail="Only customer owners or admins can delete use cases",
                )
        record_cleanup.use_cases(db, [use_case_id])
        db.delete(use_case)
        db.commit()
        return True

    @staticmethod
    def get_stats(db: Session, user: dict | None = None) -> dict:
        """Get aggregate statistics with department AND customer isolation.

        Customer isolation (BE-01 sibling defect): non-admins are scoped to
        their accessible customers (``CustomerUser`` union); admins see global.
        Previously this applied only department isolation, so a non-admin
        caller received aggregates blended across every customer.
        """
        query = db.query(UseCase)

        # Apply department isolation for stats
        if user is not None:
            allowed = user.get("allowed_departments")
            if allowed is not None and "all" not in allowed:
                query = query.filter(UseCase.department.in_(allowed))

        # Apply user-customer isolation (same rule as get_all). An empty
        # accessible set is a terminal "no data" scope (never widens).
        if user is not None and not sales_access.is_unrestricted(user):
            user_customer_ids = sales_access.customer_scope(user, db)
            if user_customer_ids:
                query = query.filter(UseCase.customer_id.in_(user_customer_ids))
            else:
                query = query.filter(UseCase.customer_id == -1)

        use_cases = query.all()
        total = len(use_cases)
        scored = sum(1 for uc in use_cases if uc.overall_score is not None)
        avg_score = sum(uc.overall_score for uc in use_cases if uc.overall_score) / scored if scored else 0

        by_status = {}
        for uc in use_cases:
            by_status[uc.status] = by_status.get(uc.status, 0) + 1

        by_department = {}
        for uc in use_cases:
            dept = uc.department or "Unassigned"
            by_department[dept] = by_department.get(dept, 0) + 1

        return {
            "total_use_cases": total,
            "scored_use_cases": scored,
            "average_score": round(avg_score, 1),
            "by_status": by_status,
            "by_department": by_department,
        }
