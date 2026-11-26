"""Service layer for customer-user junction table CRUD operations.

Handles many-to-many relationships between Customer and User with
role assignment (owner/member/auditor).  All write operations enforce
that only an owner or admin can manage access.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.models.account_membership import AccountMembership
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import email_service
from backend.services.notification_service import notify_user

# ── Constants ────────────────────────────────────────────────────────────────

VALID_JUNCTION_ROLES = ("owner", "member", "auditor")
# Global (non-junction) roles — mirrors UserService.ROLE_VALUES. ps_admin
# (third-party admin) grants cross-account access to the 3rd-party
# professional services surface ONLY.
GLOBAL_ROLES = ("admin", "user", "auditor", "ps_admin")


# ── Minimal user reference ──────────────────────────────────────────────────


@dataclass
class UserRef:
    """Minimal user identity for service-level access checks.

    Routes pass the caller's identity (id, is_admin, optional username)
    without coupling the services to full ORM ``User`` rows or request
    dicts. Replaces the legacy ``type("MockUser", ...)`` duck-typed
    objects.
    """

    id: int
    is_admin: int = 0
    username: str = "unknown"


# ── Role helpers ─────────────────────────────────────────────────────────────

def is_readonly(junction_role: str) -> bool:
    """Return True when the junction role confers read-only access."""
    return junction_role in ("auditor",)


def has_write_access(junction_role: str) -> bool:
    """Return True when the junction role allows editing use cases."""
    return junction_role in ("owner", "member")


def has_admin_access(junction_role: str) -> bool:
    """Return True when the junction role can manage users."""
    return junction_role in ("owner",)


# ── Service ──────────────────────────────────────────────────────────────────

class CustomerUserService:
    """Manage customer-user relationships (junction table CRUD)."""

    @staticmethod
    def get_user_customer_ids(db: Session, user: dict) -> list[int]:
        """Return all customer IDs a user has access to via junction table.

        Admin users get ``[]`` (empty list → caller shows all).
        """
        if user.get("is_admin") == 1:
            return []

        user_id = user.get("user_id") or user.get("id")
        if not user_id:
            return []

        junction_customers = (
            db.query(CustomerUser.customer_id)
            .filter(CustomerUser.user_id == user_id)
            .all()
        )
        return [c[0] for c in junction_customers]

    @staticmethod
    def get_user_for_customer(
        db: Session,
        customer: Customer,
        user: User,
    ) -> CustomerUser | None:
        """Return the junction record for a specific customer–user pair."""
        return (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )

    @staticmethod
    def get_junction_role(
        db: Session,
        user: User,
        customer_id: int,
    ) -> str | None:
        """Return the user's role for *customer_id*, or None if not in junction."""
        record = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer_id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )
        return record.role if record else None

    @staticmethod
    def add_user_to_customer(
        db: Session,
        customer: Customer,
        user: User,
        granting_user: User,
        role: str = "member",
    ) -> CustomerUser:
        """Add *user* to *customer* with *role*.  Must be called by owner or admin."""
        if role not in VALID_JUNCTION_ROLES:
            raise ValueError(f"Invalid junction role {role!r}; must be one of {VALID_JUNCTION_ROLES}")

        existing = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )
        if existing:
            raise ValueError(f"User {user.username} is already assigned to {customer.name}")

        record = CustomerUser(
            customer_id=customer.id,
            user_id=user.id,
            role=role,
            granted_by=granting_user.id,
            granted_at=datetime.now(UTC),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def remove_user_from_customer(
        db: Session,
        customer: Customer,
        user: User,
    ) -> bool:
        """Remove a user from a customer.  Owner or admin only."""
        record = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )
        memberships = db.query(AccountMembership).filter_by(
            customer_id=customer.id, user_id=user.id,
        ).all()
        if not record and not memberships:
            return False
        if record:
            db.delete(record)
        for membership in memberships:
            db.delete(membership)
        db.commit()
        return True

    @staticmethod
    def update_role(
        db: Session,
        customer: Customer,
        user: User,
        new_role: str,
    ) -> CustomerUser:
        """Update a user's role within a customer.  Owner or admin only."""
        if new_role not in VALID_JUNCTION_ROLES:
            raise ValueError(f"Invalid junction role {new_role!r}; must be one of {VALID_JUNCTION_ROLES}")

        record = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )
        if not record:
            raise ValueError(f"User {user.username} not assigned to {customer.name}")

        if record.role == "owner" and new_role != "owner":
            memberships = db.query(AccountMembership).filter(
                AccountMembership.customer_id == customer.id,
                AccountMembership.user_id == user.id,
                AccountMembership.role.in_(("primary_owner", "co_owner")),
            ).all()
            for membership in memberships:
                db.delete(membership)
        record.role = new_role
        db.commit()
        db.refresh(record)
        return record

    @staticmethod
    def list_customer_users(
        db: Session,
        customer: Customer,
    ) -> list[dict]:
        """Return list of all users assigned to a customer with their roles."""
        records = (
            db.query(CustomerUser)
            .filter(CustomerUser.customer_id == customer.id)
            .order_by(CustomerUser.granted_at)
            .all()
        )
        return [r.to_dict() for r in records]

    @staticmethod
    def get_all_customers_for_user(
        db: Session,
        user: User,
    ) -> list[dict]:
        """Return all customers a user has access to (via junction table)."""
        records = (
            db.query(CustomerUser)
            .filter(CustomerUser.user_id == user.id)
            .order_by(CustomerUser.granted_at)
            .all()
        )
        return [r.to_dict() for r in records]

    @staticmethod
    def has_access(
        db: Session,
        user: User,
        customer_id: int,
    ) -> bool:
        """Return True if the user has junction-level access or is a global admin."""
        if getattr(user, "is_admin", 0) == 1:
            return True
        return (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer_id,
                CustomerUser.user_id == user.id,
            )
            .first()
            is not None
        )

    @staticmethod
    def get_permission_level(
        db: Session,
        user: User,
        customer_id: int,
    ) -> str:
        """Return 'owner' | 'member' | 'auditor' | 'none'.

        Admin users always return 'owner' regardless of junction records.
        'none' means the user has no junction access (admin override
        handled by the caller in the service layer).
        """
        if getattr(user, "is_admin", 0) == 1:
            return "owner"
        record = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer_id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )
        return record.role if record else "none"

    @staticmethod
    def notify_user_of_sharing(db: Session, customer: Customer, user: User, granted_by: User) -> None:
        """Create a notification when a customer is shared with a user.

        The collaboration service (or notification service) should
        actually persist this; this is a convenience helper that
        constructs the notification payload.
        """
        from backend.models.collaboration import Notification

        notification = Notification(
            user_name=user.username,
            type="customer_shared",
            message=f"You have been granted {customer.name} access. Shared by {granted_by.username}.",
            customer_id=customer.id,
        )
        db.add(notification)
        db.commit()
        db.refresh(notification)
        # Per-recipient real-time push for the sharing notification.
        notify_user(user.username, notification.to_dict())  # type: ignore[arg-type]
        email_service.deliver_notification_email(db, notification)

    @staticmethod
    def is_owner_or_admin(
        db: Session,
        user: User,
        customer: Customer,
    ) -> bool:
        """Return True if the user is the owner of this customer or is a global admin."""
        if getattr(user, "is_admin", 0) == 1:
            return True
        record = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == user.id,
                CustomerUser.role == "owner",
            )
            .first()
        )
        return record is not None

    @staticmethod
    def get_junction(
        db: Session, customer_id: int, user_id: int
    ) -> CustomerUser | None:
        """Return the junction record for a customer–user pair, or None."""
        return (
            db.query(CustomerUser)
            .filter_by(customer_id=customer_id, user_id=user_id)
            .first()
        )

    @staticmethod
    def list_user_customer_access(db: Session, user_id: int, is_admin) -> list[dict]:
        """Return the caller's customer access with junction role info.

        Admin users see every customer with an implicit owner role.
        Junction users see the customers they are granted access to.
        """
        if is_admin == 1:
            all_customers = db.query(Customer).all()
            return [
                {
                    "customer_id": c.id,
                    "customer_name": c.name,
                    "description": c.description,
                    "role": "owner",
                    "id": 0,  # placeholder — admin doesn't use this
                    "granted_by": None,
                    "granted_at": None,
                }
                for c in all_customers
            ]
        junction_records = (
            db.query(CustomerUser)
            .filter(CustomerUser.user_id == user_id)
            .all()
        )
        # ONE batched lookup for the referenced customers (was one query
        # per junction row).
        customers = {
            c.id: c
            for c in db.query(Customer).filter(
                Customer.id.in_([cu.customer_id for cu in junction_records])
            )
        } if junction_records else {}
        result = []
        for cu in junction_records:
            c = customers.get(cu.customer_id)
            if c:
                result.append({
                    "customer_id": c.id,
                    "customer_name": c.name,
                    "description": c.description,
                    "role": cu.role,
                    "id": cu.id,
                    "granted_by": cu.granted_by,
                    "granted_at": cu.granted_at.isoformat() if cu.granted_at else None,
                })
        return result

    @staticmethod
    def is_admin_for_customer(
        db: Session,
        user: User,
        customer: Customer,
    ) -> bool:
        """Return True if the user can manage users for this customer."""
        # Global admin always has access
        if getattr(user, "is_admin", 0) == 1:
            return True
        # Check junction role
        record = (
            db.query(CustomerUser)
            .filter(
                CustomerUser.customer_id == customer.id,
                CustomerUser.user_id == user.id,
            )
            .first()
        )
        if not record:
            return False
        return record.role == "owner"
