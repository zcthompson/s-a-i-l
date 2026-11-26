"""User management service.

Authoritative business logic for admin user management: profile edits,
role changes, password resets, activate/deactivate, and deletion.

Authorization invariants:
- ``is_admin`` remains the single source of admin authority. Setting the
  global ``role`` to "admin" sets ``is_admin=1``; any other role clears it.
  This never widens access: a user with role "admin" and ``is_admin=0``
  gains nothing (admin checks read ``is_admin``), and no endpoint below
  grants admin status outside this path.
- Self-protection: an admin cannot delete, deactivate, or change the role
  of their own account (lockout prevention).
"""


from sqlalchemy.orm import Session

from backend.auth import hash_password
from backend.models.use_case import User
from backend.seed import email_prefix

_UNSET = object()


class UserService:
    """Admin user-management operations."""

    ROLE_VALUES = ("admin", "user", "auditor", "ps_admin")
    SALES_ROLE_VALUES = (None, "rep", "inside_sales", "sales_manager",
                         "auditor", "sales_ops", "sales_admin")

    @staticmethod
    def get_by_id(db: Session, user_id: int) -> User | None:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_username(db: Session, username: str) -> User | None:
        return db.query(User).filter(User.username == username).first()

    @staticmethod
    def find_existing(db: Session, username: str, email: str) -> User | None:
        """Registration uniqueness check: username OR email already taken."""
        return db.query(User).filter(
            (User.username == username) | (User.email == email)
        ).first()

    @staticmethod
    def list_pending(db: Session) -> list[User]:
        return db.query(User).filter(User.approved == 0).all()

    @staticmethod
    def list_all(db: Session) -> list[User]:
        return db.query(User).all()

    @staticmethod
    def update_user(
        db: Session,
        user_id: int,
        admin_id: int,
        display_name: str | None = None,
        email: str | None = None,
        department: str | None = None,
        role: str | None = None,
        sales_role: str | None | object = _UNSET,
    ) -> dict:
        """Edit a user's profile fields and/or global role.

        Raises ValueError for business-rule violations (unknown user,
        duplicate email, invalid role, self role change).
        """
        user = UserService.get_by_id(db, user_id)
        if user is None:
            raise ValueError("User not found")
        # Directory-managed rows: the corporate directory is the password
        # authority — the app must not write a local hash on them (0.2.0 P1,
        # plan §4).
        if (user.auth_provider or "local") == "ldap":
            raise ValueError("Account is managed by the corporate directory")

        if role is not None:
            if role not in UserService.ROLE_VALUES:
                raise ValueError(f"Invalid role: {role}")
            if user_id == admin_id:
                raise ValueError("You cannot change your own role")
            # Keep is_admin as the single source of admin authority.
            user.is_admin = 1 if role == "admin" else 0
            user.role = role

        if sales_role is not _UNSET:
            if sales_role not in UserService.SALES_ROLE_VALUES:
                raise ValueError(f"Invalid sales role: {sales_role}")
            user.sales_role = sales_role

        if email is not None and email != user.email:
            duplicate = (
                db.query(User)
                .filter(User.email == email, User.id != user_id)
                .first()
            )
            if duplicate:
                raise ValueError("Email already in use")
            user.email = email

        if display_name is not None:
            user.display_name = display_name
        if department is not None:
            user.department = department

        db.commit()
        db.refresh(user)
        return user.to_dict()

    @staticmethod
    def create_user(
        db: Session,
        admin_id: int,
        username: str,
        password: str,
        display_name: str | None = None,
        email: str | None = None,
        department: str | None = None,
        role: str = "user",
        sales_role: str | None = None,
        approved: bool = False,
        is_active: bool = False,
    ) -> dict:
        """Global-admin user creation (POST /api/auth/users/, 0.2.11).

        Adds people the seed import missed (e.g. real managers after the
        2026-10-14 org correction). Rules:
          * username and email (when provided) unique — same check as the
            register path (``find_existing``);
          * ``role='admin'`` sets ``is_admin=1`` (single source of admin
            authority); creating an admin requires the caller to already be
            a system admin (route-enforced, double-guarded here);
          * ``approved``/``is_active`` default to False — the new account
            shows up under Pending, mirroring seeded users.
          * When an email is provided, the username is derived from the
            email prefix (username == email.split("@")[0].lower()).
            ``admin`` is the named exception — never apply the rule to it.
        Raises ValueError on rule violations.
        """
        if role not in UserService.ROLE_VALUES:
            raise ValueError(f"Invalid role: {role}")
        if sales_role not in UserService.SALES_ROLE_VALUES:
            raise ValueError(f"Invalid sales role: {sales_role}")
        uname = username.strip()
        if email and email.strip():
            email = email.strip()
            if uname != "admin":
                prefix = email_prefix(email)
                if prefix:
                    uname = prefix
                # Empty normalized prefix (e.g. "@x.com") — keep the provided
                # username (slug) rather than creating an empty username.
            if UserService.find_existing(db, uname, email) is not None:
                raise ValueError("Username or email already in use")
        else:
            if UserService.get_by_username(db, uname) is not None:
                raise ValueError("Username already in use")
        caller = UserService.get_by_id(db, admin_id)
        if role == "admin" and (caller is None or caller.is_admin != 1):
            raise ValueError("Only a system admin may create another admin")
        user = User(
            username=uname,
            email=email,
            display_name=(display_name.strip() if display_name and display_name.strip() else uname),
            department=department,
            hashed_password=hash_password(password),
            role=role,
            sales_role=sales_role,
            is_admin=1 if role == "admin" else 0,
            approved=1 if approved else 0,
            is_active=1 if is_active else 0,
            auth_provider="local",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.to_dict()

    @staticmethod
    def reset_password(db: Session, user_id: int, new_password: str) -> dict:
        user = UserService.get_by_id(db, user_id)
        if user is None:
            raise ValueError("User not found")
        # Directory-managed rows (auth_provider='ldap') store no local hash —
        # the directory is the password authority (0.2.0 P1, plan §4).
        if (user.auth_provider or "local") == "ldap":
            raise ValueError("Account is managed by the corporate directory")
        user.hashed_password = hash_password(new_password)
        db.commit()
        db.refresh(user)
        return user.to_dict()

    @staticmethod
    def set_active(db: Session, user_id: int, admin_id: int, active: bool) -> dict:
        user = UserService.get_by_id(db, user_id)
        if user is None:
            raise ValueError("User not found")
        if not active and user_id == admin_id:
            raise ValueError("You cannot deactivate your own account")
        user.is_active = 1 if active else 0
        db.commit()
        db.refresh(user)
        return user.to_dict()

    @staticmethod
    def delete_user(db: Session, user_id: int, admin_id: int) -> None:
        """Delete a user and every access relationship that references them.

        Runtime SQLite does not enforce the declared ON DELETE actions
        (PRAGMA foreign_keys is off), so they are applied explicitly in one
        transaction. A surviving reference could otherwise attach reporting
        or account access to an unrelated future user. Grants this user made
        to others are retained with ``granted_by`` cleared.

        Raises ValueError for self-deletion or unknown users.
        """
        from backend.models.account_membership import AccountMembership
        from backend.models.deal import Deal
        from backend.models.sales_access import (
            InsideSalesAssignment,
            SalesOpsAssignment,
            SalesReporting,
        )
        from backend.models.saved_view import SavedView
        from backend.models.use_case import CustomerUser

        user = UserService.get_by_id(db, user_id)
        if user is None:
            raise ValueError("User not found")
        if user_id == admin_id:
            raise ValueError("You cannot delete your own account")
        try:
            db.query(SalesReporting).filter(
                (SalesReporting.rep_user_id == user_id)
                | (SalesReporting.manager_user_id == user_id)
            ).delete(synchronize_session=False)
            db.query(InsideSalesAssignment).filter(
                InsideSalesAssignment.inside_sales_user_id == user_id
            ).delete(synchronize_session=False)
            db.query(InsideSalesAssignment).filter(
                InsideSalesAssignment.rep_user_id == user_id
            ).update({InsideSalesAssignment.rep_user_id: None}, synchronize_session=False)
            db.query(SalesOpsAssignment).filter(
                SalesOpsAssignment.user_id == user_id
            ).delete(synchronize_session=False)
            db.query(AccountMembership).filter(
                AccountMembership.user_id == user_id
            ).delete(synchronize_session=False)
            db.query(SavedView).filter(SavedView.user_id == user_id).delete(synchronize_session=False)
            # D4: a deal keeps its owner-name snapshot; only the user link is cleared.
            db.query(Deal).filter(Deal.owner_user_id == user_id).update(
                {Deal.owner_user_id: None}, synchronize_session=False)
            db.query(CustomerUser).filter(
                CustomerUser.granted_by == user_id, CustomerUser.user_id != user_id
            ).update({CustomerUser.granted_by: None}, synchronize_session=False)
            # Reload relationships so the ORM cascade sees the cleared grants.
            db.expire(user)
            db.delete(user)
            db.commit()
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def get_user_stats(db: Session) -> dict:
        """Global user counts for the admin dashboard."""
        from sqlalchemy import func

        total_users = db.query(User).count()
        active_users = db.query(User).filter(User.is_active == 1).count()
        pending_users = db.query(User).filter(User.approved == 0).count()
        admin_count = db.query(User).filter(User.is_admin == 1).count()

        role_counts = (
            db.query(User.role, func.count(User.id))
            .filter(User.is_admin != 1)
            .group_by(User.role)
            .all()
        )
        # Admins are counted by is_admin (the source of admin authority);
        # everyone else is grouped by their global role.
        role_breakdown = {"admin": admin_count, "user": 0, "auditor": 0}
        for role, count in role_counts:
            key = role if role in ("user", "auditor") else "user"
            role_breakdown[key] += count
        return {
            "total_users": total_users,
            "active_users": active_users,
            "pending_users": pending_users,
            "admin_count": admin_count,
            "role_breakdown": role_breakdown,
        }
