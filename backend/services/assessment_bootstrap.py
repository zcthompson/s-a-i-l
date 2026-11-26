"""Vertical-aware template-assessment bootstrap.

Starting a *template* assessment for a customer no longer seeds a single
draft use case. Instead it produces a meaningful starting point:

* the four departments most likely to request an AI assessment for the
  customer's vertical are created (reused if they already exist), and
* one draft use case per template goal is seeded under those departments
  (goal text → department via deterministic keyword rules), and
* any vertical department left with zero use cases is pre-seeded with one
  draft "good example" use case drawn from the deterministic
  ``backend.example_use_cases`` registry — vertical-determined,
  fill-empty-only, never a duplicate, idempotent on re-bootstrap.

Transaction structure: the active
round is ensured via ``AssessmentService.ensure_active`` — an existing unit
of work that commits on its own when it creates the first round
(shared with the single-use-case create path). If the subsequent
department/use-case commit fails, the rollback leaves at most an EMPTY
active round behind — a legitimate, self-healing state (rounds with zero
use cases already exist via the manual round-create endpoint) — while the
department/use-case writes themselves are single-transaction: every new
department, every per-goal draft use case, and every pre-seeded
example use case are added together and committed once, so partial
seeding is impossible.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.example_use_cases import example_for_department
from backend.models.use_case import Customer, Department, UseCase
from backend.services import sales_access
from backend.services.assessment_service import AssessmentService
from backend.services.departments_service import get_department_by_name_and_customer
from backend.templates import TEMPLATES, truncate_goal_title
from backend.verticals import map_goal_to_department, resolve_departments


class UnknownTemplateError(ValueError):
    """Raised when the template id is not in the registry (route → 404)."""


class AssessmentBootstrapService:
    """Business logic for the vertical-aware template bootstrap."""

    @staticmethod
    def bootstrap_template_assessment(
        db: Session,
        customer: Customer,
        template_id: str,
        user: dict,
    ) -> dict:
        # 1. Access — admin bypass, else central CAP_EDIT on the customer
        # (replaces the legacy
        # owner/member junction check).
        if not sales_access.can(user, db, sales_access.CAP_EDIT, customer.id):
            raise ValueError("Not authorized to modify this customer")

        # 2. Template lookup.
        template = TEMPLATES.get(template_id)
        if template is None:
            raise UnknownTemplateError(f"Template '{template_id}' not found")

        username = user.get("username")

        # 3. Active round (auto-created on first use).
        assessment = AssessmentService.ensure_active(db, customer.id, username)

        # 4. Departments for the customer's vertical.
        dept_names = resolve_departments(customer.vertical)
        dept_by_name: dict[str, Department] = {}
        created_flags: dict[str, bool] = {}
        pending: list = []
        for name in dept_names:
            existing = get_department_by_name_and_customer(db, name, customer.id)
            if existing is not None:
                dept_by_name[name] = existing
                created_flags[name] = False
            else:
                dept = Department(name=name, customer_id=customer.id)
                dept_by_name[name] = dept
                created_flags[name] = True
                pending.append(dept)

        # Existing use-case counts per already-present 4-set department
        # (any status) — one grouped query, run now while the session has
        # no pending use cases so autoflush stays quiet. Newly created
        # departments are empty by construction and skip the query.
        existing_ids = [
            dept_by_name[name].id for name in dept_names if not created_flags[name]
        ]
        existing_counts: dict[int, int] = {}
        if existing_ids:
            existing_counts = dict(
                db.query(UseCase.department_id, func.count(UseCase.id))
                .filter(
                    UseCase.customer_id == customer.id,
                    UseCase.department_id.in_(existing_ids),
                )
                .group_by(UseCase.department_id)
                .all()
            )

        # 5. Draft use cases — one per goal (or one from the template when
        #    the template carries no goals).
        goals = list(template.get("default_goals") or [])
        template_department = template.get("default_department")
        challenges = template.get("default_challenges")
        pain_points = template.get("default_pain_points")
        description = template.get("description")
        impact_category = template.get("impact_category")
        impact_description = template.get("impact_description")
        timeline = template.get("timeline")

        new_use_cases: list[UseCase] = []
        if not goals:
            goals_iter = [(0, None)]
        else:
            goals_iter = list(enumerate(goals))

        for i, goal in goals_iter:
            if goal is None:
                title = template.get("default_title") or template.get("name")
                uc_goals = []
            else:
                title = truncate_goal_title(goal)
                uc_goals = [goal]
            mapped = map_goal_to_department(
                goal or "", dept_names, template_department, i
            )
            dept = dept_by_name.get(mapped) or dept_by_name[dept_names[0]]
            uc = UseCase(
                title=title,
                description=description,
                customer_id=customer.id,
                department=mapped,
                status="draft",
                goals=uc_goals,
                challenges=challenges,
                pain_points=pain_points,
                impact_category=impact_category,
                impact_description=impact_description,
                timeline_estimate=timeline,
                created_by=username,
                assessment_id=assessment.id,
            )
            uc.department_obj = dept
            new_use_cases.append(uc)

        # 6. Guarantee — every vertical department has ≥1 use case.
        #    Fill only the departments that (a) received no new goal UC in
        #    this call and (b) have no existing use case for this customer
        #    under that department_id (any status — see ``existing_counts``
        #    above). Newly created departments are always empty.
        seeded_names = {uc.department for uc in new_use_cases}
        preseeded_use_cases: list[UseCase] = []
        for name in dept_names:
            if name in seeded_names:
                continue
            dept = dept_by_name[name]
            if not created_flags[name] and existing_counts.get(dept.id, 0) > 0:
                continue
            example = example_for_department(name, customer.vertical)
            uc = UseCase(
                title=example["title"],
                description=example["description"],
                customer_id=customer.id,
                department=name,
                status="draft",
                goals=list(example["goals"]),
                challenges=list(example["challenges"]),
                pain_points=list(example["pain_points"]),
                impact_category=example["impact_category"],
                impact_description=example["impact_description"],
                estimated_savings=example["estimated_savings"],
                estimated_revenue=example["estimated_revenue"],
                timeline_estimate=example["timeline_estimate"],
                created_by=username,
                assessment_id=assessment.id,
            )
            uc.department_obj = dept
            preseeded_use_cases.append(uc)

        db.add_all(pending + new_use_cases + preseeded_use_cases)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        for uc in new_use_cases + preseeded_use_cases:
            db.refresh(uc)

        return {
            "assessment_id": assessment.id,
            "assessment_name": assessment.name,
            # template bootstrap always works on an AI
            # round (ensure_active creates 'ai'); the fields are passthrough.
            "assessment_type": assessment.assessment_type or "ai",
            "purpose": assessment.purpose,
            "departments": [
                {"name": name, "created": created_flags[name]} for name in dept_names
            ],
            "use_cases": [
                {"id": uc.id, "title": uc.title, "department": uc.department}
                for uc in new_use_cases
            ],
            "preseeded": [
                {"id": uc.id, "title": uc.title, "department": uc.department}
                for uc in preseeded_use_cases
            ],
            "count": len(new_use_cases) + len(preseeded_use_cases),
        }
