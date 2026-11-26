"""Shared scoping for the report export endpoints (PDF/CSV/Excel).

All three export routes (``/api/export/pdf/``, ``/api/stats/export/csv/``,
``/api/stats/export/excel/``) resolve their scope through
:func:`resolve_export_scope` so scoping, access checks, and report
metadata stay consistent across formats.

Scoping options (combinable):

- ``assessment_id``: export exactly one customer assessment round —
  active or archived (archived rounds are read-only but remain
  exportable, per the CustomerAssessment lifecycle).
- ``customer_name``: export all of a customer's use cases.
- ``use_case_ids``: explicit row-level filter (legacy behavior, kept for
  the ScoringDashboard scoped export).

An unknown customer name or assessment is an error (404), not a silent
global export — customer-scoped reports must not silently widen.
"""

import re

from sqlalchemy.orm import Session

from backend.models.use_case import Customer, UseCase
from backend.services import sales_access
from backend.services.assessment_service import AssessmentService
from backend.services.customers_service import (
    check_customer_access,
    get_customer_by_name,
)


class ExportScopeError(Exception):
    """Rejected export scope: HTTP status code + user-facing detail."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def assert_scoped_or_admin(
    user: dict,
    customer_name: str | None,
    assessment_id: int | None,
    use_case_ids: list[int] | None,
) -> None:
    """R5: an export with no customer, assessment or ID filter is the whole
    portfolio, which only a system admin may take. Scoped exports pass through
    unchanged. Call before ``resolve_export_scope``.
    """
    if customer_name is None and assessment_id is None and not use_case_ids:
        if user.get("is_admin") != 1:
            raise ExportScopeError(403, "Full-portfolio export requires admin")


def resolve_export_scope(
    db: Session,
    user: dict,
    customer_name: str | None = None,
    assessment_id: int | None = None,
    use_case_ids: list[int] | None = None,
) -> tuple[list[int] | None, int | None, dict | None]:
    """Resolve the export scope for one export request.

    Returns ``(id_list, customer_id, meta)``:

    - ``id_list``: explicit use case IDs to export (None = no row filter),
    - ``customer_id``: customer scope (None = none),
    - ``meta``: customer/assessment context for the report header
      (None for an unscoped global export).

    Raises :class:`ExportScopeError` on unknown/mismatched scope or
    denied access.
    """
    id_list: list[int] | None = list(use_case_ids) if use_case_ids else None
    customer_id: int | None = None
    meta: dict | None = None

    if assessment_id is not None:
        assessment = AssessmentService.get_by_id(db, assessment_id)
        if assessment is None:
            raise ExportScopeError(404, "Assessment not found")
        customer = (
            db.query(Customer)
            .filter(Customer.id == assessment.customer_id)
            .first()
        )
        if customer is None:
            raise ExportScopeError(404, "Customer for this assessment not found")
        if not check_customer_access(db, customer, user):
            # 404-first (R4/Q7): an out-of-scope assessment is the same 404
            # as a missing one (no existence oracle).
            raise ExportScopeError(404, "Assessment not found")
        if customer_name is not None:
            named = get_customer_by_name(db, customer_name)
            if named is None or named.id != customer.id:
                raise ExportScopeError(
                    400,
                    "assessment_id does not belong to the given customer_name",
                )
        assessment_uc_ids = [uc.id for uc in assessment.use_cases]
        if id_list is not None:
            # Explicit row filter intersects with the assessment scope.
            id_list = [i for i in id_list if i in assessment_uc_ids]
        else:
            id_list = assessment_uc_ids
        customer_id = customer.id
        meta = {
            "customer_name": customer.name,
            "customer_id": customer.id,
            "assessment_id": assessment.id,
            "assessment_name": assessment.name,
            "assessment_status": assessment.status,
            # Part 13 WS5 (R9): additive round type + purpose (round-scoped only).
            "assessment_type": assessment.assessment_type or "ai",
            "purpose": assessment.purpose,
            "created_by": assessment.created_by,
            "created_at": assessment.created_at.isoformat() if assessment.created_at else None,
            "archived_at": assessment.archived_at.isoformat() if assessment.archived_at else None,
            "use_case_count": len(assessment_uc_ids),
        }
        return id_list, customer_id, meta

    if customer_name is not None:
        customer = get_customer_by_name(db, customer_name)
        if customer is None or not check_customer_access(db, customer, user):
            # 404-first (R4/Q7): out-of-scope == missing.
            raise ExportScopeError(404, "Customer not found")
        customer_id = customer.id
        meta = {
            "customer_name": customer.name,
            "customer_id": customer.id,
            "assessment_id": None,
            "assessment_name": None,
            "assessment_status": None,
            "created_by": None,
            "created_at": None,
            "archived_at": None,
            "use_case_count": None,
        }
        return id_list, customer_id, meta

    # Unscoped global export (existing behavior for admins / scoped users).
    if id_list is not None and user.get("is_admin") != 1:
        # Part 13 (2026-10-29, WB stop-and-report): an explicit ID request is
        # a cross-customer read — the ID path had no caller check at all.
        # Intersect the IDs with the caller's central read scope; unassigned
        # use cases are admin-only (R2) and drop out. All-out-of-scope or all
        # missing => 404, indistinguishable from a not-found request (R4).
        found = dict(
            db.query(UseCase.id, UseCase.customer_id)
            .filter(UseCase.id.in_(id_list))
            .all()
        )
        readable = {
            cid for cid in set(found.values())
            if cid is not None and sales_access.can(user, db, sales_access.CAP_READ, cid)
        }
        scoped = [uc_id for uc_id, cust_id in found.items() if cust_id in readable]
        if not scoped:
            raise ExportScopeError(404, "Use cases not found")
        id_list = scoped
    return id_list, None, None


def _slug(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value or "").strip("_").lower() or "global"


def report_filename(meta: dict | None, ext: str) -> str:
    """Attachment filename for an export response.

    Scoped exports name the file after the customer and assessment round;
    unscoped exports keep the legacy global names.
    """
    if meta and meta.get("assessment_name"):
        base = f"assessment_report_{_slug(meta.get('customer_name'))}_{_slug(meta['assessment_name'])}"
    elif meta:
        base = f"assessment_report_{_slug(meta.get('customer_name'))}"
    else:
        base = "sail_report" if ext == "pdf" else "sail_export"
    return f"{base}.{ext}"
