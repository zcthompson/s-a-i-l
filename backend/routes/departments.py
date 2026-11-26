"""REST API routes for department operations.

Access control (404-first):
- Admin users: unrestricted access.
- Other users: access limited to their central READ scope (sales_access).
- Unauthenticated: 401.

The unscoped list is limited to the caller's readable customers. A record or
customer outside the caller's reach returns the same 404 as a missing one, so
a by-id or by-name probe cannot reveal existence. In-scope capability denials
keep their exact 403.
"""


from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.schemas.use_case import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
)
from backend.services import customer_access, sales_access
from backend.services.departments_service import (
    check_department_name_exists,
    get_all_departments,
    get_customer_by_name,
    get_department_by_id,
    get_department_use_cases,
    get_departments_for_customer,
    get_departments_for_customers,
    update_department_use_cases_null,
)

router = APIRouter(prefix="/api/departments", tags=["departments"])


def _require_user(request: Request) -> dict:
    """Return authenticated user or 401."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


def _require_manage_team(user: dict, db: Session, customer_id: int) -> None:
    """403 unless the caller holds CAP_MANAGE_TEAM on the customer."""
    if not sales_access.can(user, db, sales_access.CAP_MANAGE_TEAM, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


@router.get("/", response_model=list[DepartmentResponse])
def list_departments(
    request: Request,
    customer_name: str | None = None,
    db: Session = Depends(get_db),
):
    """List departments, optionally filtered by customer (access-controlled).

    The unscoped list is limited to the caller's readable customers (admin
    sees all); a customer the caller cannot reach is never enumerated.
    """
    user = _require_user(request)
    if customer_name:
        customer = get_customer_by_name(db, customer_name)
        if customer is None or not customer_access.can_read(user, db, customer.id):  # type: ignore[arg-type]
            raise HTTPException(status_code=404, detail="Customer not found")
        return [d.to_dict() for d in get_departments_for_customer(db, customer.id)]
    if user.get("is_admin") == 1:
        return [d.to_dict() for d in get_all_departments(db)]
    scope = sales_access.customer_scope(user, db)
    return [d.to_dict() for d in get_departments_for_customers(db, scope)]


@router.get("/{department_id}/", response_model=DepartmentResponse)
def get_department(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get a department by ID (404-first: out-of-scope == missing)."""
    user = _require_user(request)
    department = get_department_by_id(db, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if not customer_access.can_read(user, db, department.customer_id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Department not found")
    return department.to_dict()


@router.post("/", response_model=DepartmentResponse, status_code=201)
def create_department(
    data: DepartmentCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create a new department under a customer. Admin or owner only."""
    user = _require_user(request)
    if user.get("is_admin") != 1:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    customer = get_customer_by_name(db, data.customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    _require_manage_team(user, db, customer.id)
    existing = check_department_name_exists(db, data.name, customer.id)
    if existing:
        raise HTTPException(status_code=400, detail="Department already exists for this customer")
    from backend.models.use_case import Department
    department = Department(name=data.name, customer_id=customer.id)
    db.add(department)
    db.commit()
    db.refresh(department)
    return department.to_dict()


@router.put("/{department_id}/", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    data: DepartmentUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update a department name. In-scope team-managers only (404-first)."""
    user = _require_user(request)
    department = get_department_by_id(db, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if not customer_access.can_read(user, db, department.customer_id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Department not found")
    _require_manage_team(user, db, department.customer_id)  # type: ignore[arg-type]
    existing = check_department_name_exists(db, data.name, department.customer_id, department_id)  # type: ignore[arg-type]
    if existing:
        raise HTTPException(status_code=400, detail="Department name already exists for this customer")
    department.name = data.name
    db.commit()
    db.refresh(department)
    return department.to_dict()


@router.delete("/{department_id}/", status_code=204)
def delete_department(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Delete a department. In-scope team-managers only (404-first)."""
    user = _require_user(request)
    department = get_department_by_id(db, department_id)
    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")
    if not customer_access.can_read(user, db, department.customer_id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Department not found")
    _require_manage_team(user, db, department.customer_id)  # type: ignore[arg-type]
    update_department_use_cases_null(db, department_id)
    db.delete(department)
    db.commit()


@router.get("/{department_id}/use-cases/", response_model=list[dict])
def get_department_use_cases_route(
    department_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Get all use cases for a department (404-first: out-of-scope == missing)."""
    user = _require_user(request)
    department = get_department_by_id(db, department_id)
    if department is None or not customer_access.can_read(user, db, department.customer_id):  # type: ignore[arg-type]
        raise HTTPException(status_code=404, detail="Department not found")
    use_cases = get_department_use_cases(db, department)
    return [uc.to_dict() for uc in use_cases]
