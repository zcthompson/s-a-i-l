"""Customer sharing and user management routes.

Handles:
- Adding/removing users from customers (owner/admin only)
- Listing users for a customer
- Listing all customers for current user
- Changing roles within a customer
- Checking access permissions

Access control: the user-list read is 404-first (R4/Q7) — a customer outside
the caller's read scope returns the same 404 as a missing one. The team-
mutation routes keep their existing 403s, and the ``/access/`` probe keeps
its 200 + ``has_access`` shape (the FE access gate depends on it).
"""


from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.dependencies import get_db
from backend.models.collaboration import AuditLog
from backend.models.use_case import Customer
from backend.services import customer_access, sales_access
from backend.services.customer_user_service import CustomerUserService, UserRef
from backend.services.customers_service import get_customer_by_name

router = APIRouter(prefix="/api/customers", tags=["customer-sharing"])


def _record_audit(db: Session, user: dict, action: str, customer: Customer,
                  target_id: int | None = None, details: str | None = None,
                  request: Request | None = None):
    """Record an audit log entry for a customer sharing operation."""
    ip = None
    if request:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
        else:
            ip = request.client.host if request.client else None
    entry = AuditLog(
        user_id=user.get("user_id", 0) or 0,
        username=user.get("username", "unknown"),
        action=action,
        customer_id=customer.id,
        target_id=target_id,
        details=details,
        ip_address=ip,
    )
    db.add(entry)
    db.commit()


def _require_manage_team(user: dict, db: Session, customer: Customer,
                         granting_role: str | None = None) -> None:
    """Resolver gate for team mutations on ``customer``.

    CAP_MANAGE_TEAM always; granting the ``owner`` role is an ownership
    transfer and additionally needs CAP_TRANSFER_OWNERSHIP.
    """
    caps = [sales_access.CAP_MANAGE_TEAM]
    if granting_role == "owner":
        caps.append(sales_access.CAP_TRANSFER_OWNERSHIP)
    for cap in caps:
        if not sales_access.can(user, db, cap, customer.id):
            raise HTTPException(status_code=403, detail="Not authorized to modify this customer")


@router.get("/{customer_name}/users/")
def list_customer_users(
    customer_name: str,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """List all users with access to a customer. Owner/admin only."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Part 13 R1 (2026-10-29): central policy read (was the legacy
    # junction-only CustomerUserService.has_access — DV3); out-of-scope is
    # a 404 like a missing customer (R4/Q7).
    customer = customer_access.read_by_name_or_404(db, user, customer_name)
    
    users = CustomerUserService.list_customer_users(db, customer)
    return {"users": users}


@router.post("/{customer_name}/users/")
def add_user_to_customer(
    customer_name: str,
    user_id: int = Query(..., description="User ID to add"),
    role: str = Query("member", description="Role: owner | member | auditor"),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Add a user to a customer. Owner/admin only."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Check admin/owner status
    customer = get_customer_by_name(db, customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if not CustomerUserService.is_admin_for_customer(db, UserRef(id=user.get("user_id", 0), is_admin=user.get("is_admin", 0)), customer):
        # 404-first (R4/Q7): a caller who is not an owner/admin of this
        # customer is out of scope — the same 404 as a missing customer.
        raise HTTPException(status_code=404, detail="Customer not found")
    if role == "owner" and user.get("is_admin") != 1:
        raise HTTPException(status_code=403, detail="Only admins can grant owner role")
    _require_manage_team(user, db, customer, granting_role=role)
    
    # Add user
    try:
        mock_user = UserRef(id=user_id, username="unknown")
        result = CustomerUserService.add_user_to_customer(db, customer, mock_user, UserRef(id=user.get("user_id", 0), is_admin=user.get("is_admin", 0)), role=role)
        _record_audit(db, user, "add_user", customer, target_id=user_id, details=f"Role: {role}", request=request)
        return {"message": f"User {user_id} added to {customer_name}", "customer_id": result.customer_id, "user_id": result.user_id, "role": result.role}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{customer_name}/users/{user_id}/")
def remove_user_from_customer(
    customer_name: str,
    user_id: int,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Remove a user from a customer. Owner/admin only."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    customer = get_customer_by_name(db, customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if not CustomerUserService.is_admin_for_customer(db, UserRef(id=user.get("user_id", 0), is_admin=user.get("is_admin", 0)), customer):
        # 404-first (R4/Q7): out of scope == missing.
        raise HTTPException(status_code=404, detail="Customer not found")
    _require_manage_team(user, db, customer)
    
    success = CustomerUserService.remove_user_from_customer(db, customer, UserRef(id=user_id))
    if not success:
        raise HTTPException(status_code=404, detail="User not found in customer")
    
    _record_audit(db, user, "remove_user", customer, target_id=user_id, details="User removed from customer", request=request)
    return {"message": f"User {user_id} removed from {customer_name}"}


@router.get("/me/customers/")
def get_my_customers(
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """List all customers assigned/shared with current user."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if "user_id" not in user:
        raise HTTPException(status_code=400, detail="User ID not available")
    
    rows = CustomerUserService.list_user_customer_access(
        db, user["user_id"], user.get("is_admin", 0)
    )
    return [row for row in rows if sales_access.can(user, db, sales_access.CAP_READ, row["customer_id"])]


@router.put("/{customer_name}/users/{user_id}/")
def update_user_role(
    customer_name: str,
    user_id: int,
    role: str = Query(..., description="New role: owner | member | auditor"),
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Update a user's role within a customer. Owner/admin only."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    customer = get_customer_by_name(db, customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    if not CustomerUserService.is_admin_for_customer(db, UserRef(id=user.get("user_id", 0), is_admin=user.get("is_admin", 0)), customer):
        # 404-first (R4/Q7): out of scope == missing.
        raise HTTPException(status_code=404, detail="Customer not found")
    if role == "owner" and user.get("is_admin") != 1:
        raise HTTPException(status_code=403, detail="Only admins can grant owner role")
    _require_manage_team(user, db, customer, granting_role=role)
    
    try:
        result = CustomerUserService.update_role(db, customer, UserRef(id=user_id), role)
        _record_audit(db, user, "update_role", customer, target_id=user_id, details=f"Role changed to {role}", request=request)
        return {"message": f"User {user_id} role updated to {role}", "customer_id": result.customer_id, "user_id": result.user_id, "role": result.role}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{customer_name}/access/")
def check_access(
    customer_name: str,
    request: Request = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
):
    """Check if current user has access to a customer and what role."""
    user = get_user_from_request(request) if request else None
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    customer = get_customer_by_name(db, customer_name)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    
    # Part 13 R1 (2026-10-29): has_access follows the CENTRAL read policy
    # (was the legacy junction-only CustomerUserService.has_access — DV3).
    # The 200 + has_access:false shape is preserved (the FE access gate
    # depends on it); permission_level stays the junction role (display —
    # the server enforces every write capability per route).
    has_access = (
        user.get("is_admin") == 1
        or sales_access.can(user, db, sales_access.CAP_READ, customer.id)
    )
    permission_level = CustomerUserService.get_permission_level(db, UserRef(id=user.get("user_id", 0), is_admin=user.get("is_admin", 0)), customer.id)
    
    return {
        "has_access": has_access,
        "permission_level": permission_level,
        "customer_name": customer.name,
        "customer_id": customer.id,
    }
