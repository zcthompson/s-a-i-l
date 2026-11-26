"""Shared customer-access authorization helpers (S-A-I-L).

Single home for the per-customer access gates (the per-route-module
re-implementations consolidated here as explicit
variants; the sales-notes / customer-knowledge /
pipeline-import surfaces moved onto the same central basis; subsequent
consolidation
moved the remaining nine junction-only divergences).

Account (central-policy) variants — the single authority is the central
``sales_access`` READ capability; ``can_read`` is equivalent
to the customer being in the caller's ``customer_scope`` (admin
unrestricted):

- ``can_read`` — the boolean central READ capability.
- ``read_or_404`` — load by id; missing OR out-of-scope → the same 404
  (404-first — no existence leakage).
- ``read_existing_or_404`` — same, for a pre-loaded customer object.
- ``read_by_name_or_404`` — same, resolving by customer name.
- ``read_or_403`` — authenticate + central READ, 403-first (the
  documented ordering kept by ``sales_section``).

PS-surface variants (3rd-party services) — junction-only BY DELIBERATE
DESIGN (the central policy confines
``ps_admin`` to exactly this surface, so it is never migrated to the
central basis; the other variants above must NOT be used here):

- ``ps_role_ok`` — admin or the ``ps_admin`` global role (third-party
  admin: cross-account read+write on the 3rd-party PS surface only, no
  CustomerUser row required; NOTHING else).
- ``require_ps_customer_access`` — read gate for the PS surface: passes
  for ps_role_ok callers and for callers holding a junction row
  (owner/member/auditor — same read semantics as everywhere else).
- ``ps_customer_read_ok`` — the boolean form of the PS read basis
  (ps_role_ok or a junction row).
- ``ps_customer_write_ok`` — write gate: ps_role_ok, else an owner/member
  junction role (junction-``auditor`` rows are read-only — same rule as
  sales notes / comments, the ``junction_roles`` pattern from ``auth.py``).

``get_user_from_request`` builds the user dict from the DB (auth.py), so
``role`` is always the live DB value — no JWT payload change.
"""

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from backend.auth import get_user_from_request
from backend.models.use_case import Customer
from backend.services import sales_access


def can_read(user: dict, db: Session, customer_id: int) -> bool:
    """The central READ capability (the single authority on account reads)."""
    return sales_access.can(user, db, sales_access.CAP_READ, customer_id)


def read_or_404(db: Session, user: dict, customer_id: int) -> Customer:
    """Load the customer by id; missing or out-of-scope → the same 404.

    404-first: a customer-id probe cannot reveal existence.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None or not can_read(user, db, customer_id):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def read_existing_or_404(db: Session, user: dict, customer: Customer | None) -> Customer:
    """The pre-loaded variant of ``read_or_404`` (customer already resolved)."""
    if customer is None or not can_read(user, db, customer.id):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def read_by_name_or_404(db: Session, user: dict, customer_name: str) -> Customer:
    """The name-resolving variant of ``read_or_404``."""
    from backend.services.customers_service import get_customer_by_name

    customer = get_customer_by_name(db, customer_name)
    if customer is None or not can_read(user, db, customer.id):
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def read_or_403(request: Request, db: Session, customer_id: int) -> dict:
    """Authenticate + central READ, 403-first (the documented
    ordering — ``sales_section`` keeps this deliberate ordering)."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not can_read(user, db, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized for this customer")
    return user


def read_auth_or_404(request: Request, db: Session, customer_id: int) -> dict:
    """Authenticate, then ``read_or_404`` (401 unauthenticated → 404
    missing/out-of-scope). Returns the user dict."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    read_or_404(db, user, customer_id)
    return user


def require_account_read_service(db: Session, user: dict, customer_id: int) -> Customer:
    """Resolve the customer, then enforce the central account-read policy.

    Missing customers return 404 before authorization; existing customers
    outside the caller's policy scope return 403. No content is assembled.
    """
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not sales_access.can(user, db, sales_access.CAP_READ, customer_id):
        raise HTTPException(status_code=403, detail="Not authorized for this customer")
    return customer


def require_account_read(request: Request, db: Session, customer_id: int) -> tuple[dict, Customer]:
    """Authenticate an HTTP caller and authorize account reads before assembly."""
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user, require_account_read_service(db, user, customer_id)


def ps_customer_read_ok(user: dict, customer_id: int) -> bool:
    """PS-surface read basis — junction-only BY DESIGN:
    ps_role_ok or a CustomerUser row. This
    surface is NOT on the central basis on purpose (ps_admin confinement)."""
    return ps_role_ok(user) or customer_id in user.get("customer_ids", [])


def ps_role_ok(user: dict) -> bool:
    """True for admin or the ``ps_admin`` (third-party admin) global role."""
    return user.get("is_admin") == 1 or user.get("role") == "ps_admin"


def require_ps_customer_access(request: Request, customer_id: int) -> dict:
    """Read gate for the 3rd-party PS surface.

    Passes for ps_role_ok callers (any account, no junction row required)
    and for callers holding a CustomerUser row for the customer (existing
    semantics). Raises 401/403 otherwise.
    """
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if ps_role_ok(user):
        return user
    if customer_id not in user.get("customer_ids", []):
        raise HTTPException(status_code=403, detail="Not authorized for this customer")
    return user


def ps_customer_write_ok(user: dict, customer_id: int) -> bool:
    """Write gate for the PS surface: ps_role_ok, else an owner/member
    junction role (auditor rows are read-only)."""
    if ps_role_ok(user):
        return True
    return (user.get("junction_roles") or {}).get(customer_id) in ("owner", "member")
