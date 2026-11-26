"""Service layer for department CRUD operations.

Handles department creation, listing, deletion, and use case aggregation
per customer.
"""

from sqlalchemy.orm import Session

from backend.models.use_case import Customer, Department, UseCase
from backend.services import record_cleanup


def get_departments_for_customer(db: Session, customer_id: int) -> list[Department]:
    """Return all departments for a customer."""
    return db.query(Department).filter(Department.customer_id == customer_id).all()


def get_department_by_name_and_customer(
    db: Session, name: str, customer_id: int
) -> Department | None:
    """Look up a department by name within a customer."""
    return (
        db.query(Department)
        .filter(
            Department.name == name,
            Department.customer_id == customer_id,
        )
        .first()
    )


def get_department_use_cases(db: Session, department: Department) -> list[UseCase]:
    """Return all use cases for a department."""
    return (
        db.query(UseCase)
        .filter(
            UseCase.department_id == department.id,
            UseCase.status != "archived",
        )
        .all()
    )


def delete_department_with_use_cases(db: Session, department: Department) -> None:
    """Cascade delete: remove all use cases (with their children), then the department."""
    ids = [row[0] for row in db.query(UseCase.id).filter(UseCase.department_id == department.id)]
    record_cleanup.use_cases(db, ids)
    db.query(UseCase).filter(UseCase.id.in_(ids)).delete(synchronize_session=False)
    db.delete(department)
    db.flush()


def get_customer_by_name(db: Session, name: str) -> Customer | None:
    """Look up a customer by name."""
    return db.query(Customer).filter(Customer.name == name).first()


def get_department_by_id(db: Session, department_id: int) -> Department | None:
    """Look up a department by ID."""
    return db.query(Department).filter(Department.id == department_id).first()


def check_department_name_exists(
    db: Session, name: str, customer_id: int, exclude_id: int | None = None
) -> Department | None:
    """Check if a department with this name exists for a customer (excluding a specific ID)."""
    if exclude_id:
        return (
            db.query(Department)
            .filter(
                Department.customer_id == customer_id,
                Department.name == name,
                Department.id != exclude_id,
            )
            .first()
        )
    return (
        db.query(Department)
        .filter(
            Department.customer_id == customer_id,
            Department.name == name,
        )
        .first()
    )


def update_department_use_cases_null(db: Session, department_id: int) -> None:
    """Set department_id to NULL for all use cases in this department."""
    db.query(UseCase).filter(UseCase.department_id == department_id).update(
        {"department_id": None}
    )


def get_all_departments(db: Session) -> list[Department]:
    """Return all departments (no filter)."""
    return db.query(Department).all()


def get_departments_for_customers(db: Session, customer_ids) -> list[Department]:
    """Return all departments for the given set of customer ids (empty = none)."""
    ids = set(customer_ids)
    if not ids:
        return []
    return db.query(Department).filter(Department.customer_id.in_(ids)).all()
