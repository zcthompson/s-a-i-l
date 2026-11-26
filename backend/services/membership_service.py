"""Account-membership rules (RBAC model): who holds which role on which
account, section grants for inside sales, ownership transfer and the
ownership-review queue.

Routes are HTTP only; every rule lives here. Mutations are audited
(``AuditLog``) in the same transaction as the change. The authorization
vocabulary (roles, caps, grant policy) comes from ``sales_access`` — the one
policy layer. ``CustomerUser`` remains the legacy junction of record, so
primary-owner changes are mirrored onto its owner/member rows to keep every
legacy code path consistent.
"""

import json

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.account_membership import (
    ACCOUNT_SECTIONS,
    MEMBERSHIP_ROLES,
    MEMBERSHIP_SOURCES,
    SECTION_LEVELS,
    AccountMembership,
)
from backend.models.collaboration import AuditLog
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import sales_access

SEED_ACTOR_NAME = "system:seed"


class MembershipError(Exception):
    """Rule violation; ``status_code`` is the HTTP status to surface."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ── helpers ────────────────────────────────────────────────────────────────


def _name(user: User) -> str:
    return user.display_name or user.username


def _ip(request) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _audit(db: Session, actor: User | None, action: str, customer_id: int | None,
           target_id: int | None, details: dict, request=None) -> None:
    """Stage an audit row (no commit; it rides the caller's transaction)."""
    db.add(AuditLog(
        user_id=actor.id if actor else 0,
        username=actor.username if actor else SEED_ACTOR_NAME,
        action=action,
        customer_id=customer_id,
        target_id=target_id,
        details=json.dumps(details, sort_keys=True, default=str),
        ip_address=_ip(request),
    ))


def stage_prospect_audit(db: Session, creator_id: int, customer: Customer, request=None) -> None:
    """Audit a manager-created prospect entering the ownership-review queue."""
    creator = db.query(User).filter(User.id == creator_id).first()
    _audit(db, creator, "account.prospect_create", customer.id, creator_id, {
        "name": customer.name, "ownership_status": customer.ownership_status,
        "provisional_owner": creator.username if creator else None,
    }, request)


def actor_context(db: Session, actor_id: int | None) -> dict:
    """User dict for the resolver, built the way ``get_user_from_request`` does."""
    user = db.query(User).filter(User.id == actor_id).first() if actor_id else None
    if user is None:
        raise MembershipError(401, "Actor not found")
    rows = db.query(CustomerUser).filter(CustomerUser.user_id == user.id).all()
    ctx = {
        "username": user.username, "user_id": user.id, "is_admin": user.is_admin,
        "role": user.role, "sales_role": user.sales_role,
        "customer_ids": [r.customer_id for r in rows],
        "junction_roles": {r.customer_id: r.role for r in rows},
    }
    sales_access.load_membership_context(ctx, db)
    return ctx


def _get_customer(db: Session, customer_id: int) -> Customer:
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise MembershipError(404, "Customer not found")
    return customer


def _get_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise MembershipError(404, f"User not found: {user_id}")
    return user


def _snapshot(db: Session, customer_id: int) -> list[dict]:
    rows = (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer_id)
        .order_by(AccountMembership.id)
        .all()
    )
    return [{"user_id": r.user_id, "role": r.role, "section_grants": r.section_grants} for r in rows]


def _validate_grants(grants) -> dict:
    if not isinstance(grants, dict):
        raise MembershipError(400, "section_grants must be an object")
    for section, level in grants.items():
        if section not in ACCOUNT_SECTIONS:
            raise MembershipError(400, f"Unknown section: {section}")
        if level not in SECTION_LEVELS:
            raise MembershipError(400, f"Invalid grant level for {section}: {level}")
    return dict(grants)


def _sync_junction_owner(db: Session, customer_id: int, user_id: int, owner: bool,
                         granted_by: int | None) -> None:
    """Mirror primary-owner status onto the legacy junction row."""
    row = (
        db.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer_id, CustomerUser.user_id == user_id)
        .first()
    )
    if owner:
        if row is None:
            db.add(CustomerUser(
                customer_id=customer_id, user_id=user_id, role="owner", granted_by=granted_by,
            ))
        elif row.role != "owner":
            row.role = "owner"
    elif row is not None and row.role == "owner":
        row.role = "member"


def _primary_owner_rows(db: Session, customer_id: int) -> list[AccountMembership]:
    return (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer_id,
                AccountMembership.role == "primary_owner")
        .order_by(AccountMembership.id)
        .all()
    )


def _require_grant(db: Session, actor_ctx: dict, role: str, customer_id: int) -> None:
    if not sales_access.may_grant_role(actor_ctx, role, customer_id, db):
        raise MembershipError(403, f"Not permitted to manage the {role} role on this account")


def assert_can_read(db: Session, actor_ctx: dict, customer_id: int) -> None:
    if not sales_access.can(actor_ctx, db, sales_access.CAP_READ, customer_id):
        raise MembershipError(403, "Not permitted to view this account")


# ── reads ──────────────────────────────────────────────────────────────────


def list_memberships(db: Session, customer_id: int) -> list[dict]:
    rows = (
        db.query(AccountMembership, User)
        .join(User, User.id == AccountMembership.user_id)
        .filter(AccountMembership.customer_id == customer_id)
        .order_by(AccountMembership.id)
        .all()
    )
    return [
        {
            "user_id": u.id,
            "username": u.username,
            "name": _name(u),
            "role": m.role,
            "section_grants": m.section_grants,
            "source": m.source,
            "expires_at": m.expires_at.isoformat() if m.expires_at else None,
        }
        for m, u in rows
    ]


# ── writes ─────────────────────────────────────────────────────────────────


def _insert(db: Session, customer: Customer, user: User, role: str,
            section_grants, source: str, granted_by: int | None) -> AccountMembership:
    if role not in MEMBERSHIP_ROLES:
        raise MembershipError(400, f"Invalid role: {role}")
    if source not in MEMBERSHIP_SOURCES:
        raise MembershipError(400, f"Invalid source: {source}")
    if role == "inside_sales":
        grants = _validate_grants(section_grants) if section_grants is not None else None
    else:
        if section_grants:
            raise MembershipError(400, "section_grants apply to inside_sales only")
        grants = None
    existing = (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer.id,
                AccountMembership.user_id == user.id,
                AccountMembership.role == role)
        .first()
    )
    if existing is not None:
        raise MembershipError(409, "Membership already exists")
    if role == "primary_owner" and _primary_owner_rows(db, customer.id):
        raise MembershipError(409, "Account already has a primary owner; use ownership transfer")
    row = AccountMembership(
        user_id=user.id, customer_id=customer.id, role=role,
        section_grants=grants, source=source,
    )
    db.add(row)
    if role == "primary_owner":
        _sync_junction_owner(db, customer.id, user.id, True, granted_by)
    return row


def add_membership(db: Session, customer_id: int, user_id: int, role: str, actor_id: int,
                   section_grants=None, source: str = "manual", request=None) -> dict:
    customer = _get_customer(db, customer_id)
    target = _get_user(db, user_id)
    actor_ctx = actor_context(db, actor_id)
    if role not in MEMBERSHIP_ROLES:
        raise MembershipError(400, f"Invalid role: {role}")
    _require_grant(db, actor_ctx, role, customer_id)
    if target.id == actor_id and sales_access.effective_role(actor_ctx) != "system_admin":
        raise MembershipError(403, "You cannot grant yourself a role")
    actor = db.query(User).filter(User.id == actor_id).first()
    before = _snapshot(db, customer_id)
    try:
        row = _insert(db, customer, target, role, section_grants, source, actor_id)
        db.flush()
        _audit(db, actor, "membership.add", customer_id, target.id,
               {"before": before, "after": _snapshot(db, customer_id), "role": role},
               request)
        db.commit()
    except MembershipError:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        raise MembershipError(409, "Membership already exists")
    db.refresh(row)
    return row.to_dict()


def remove_membership(db: Session, customer_id: int, user_id: int, role: str,
                      actor_id: int, request=None) -> dict:
    _get_customer(db, customer_id)
    actor_ctx = actor_context(db, actor_id)
    if role not in MEMBERSHIP_ROLES:
        raise MembershipError(400, f"Invalid role: {role}")
    _require_grant(db, actor_ctx, role, customer_id)
    row = (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer_id,
                AccountMembership.user_id == user_id,
                AccountMembership.role == role)
        .first()
    )
    if row is None:
        raise MembershipError(404, "Membership not found")
    if role == "primary_owner" and len(_primary_owner_rows(db, customer_id)) <= 1:
        raise MembershipError(409, "Cannot remove the last primary owner; transfer ownership")
    actor = db.query(User).filter(User.id == actor_id).first()
    before = _snapshot(db, customer_id)
    removed = row.to_dict()
    try:
        db.delete(row)
        if role == "primary_owner":
            _sync_junction_owner(db, customer_id, user_id, False, actor_id)
        db.flush()
        _audit(db, actor, "membership.remove", customer_id, user_id,
               {"before": before, "after": _snapshot(db, customer_id), "role": role},
               request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return removed


def _do_transfer(db: Session, customer: Customer, new_owner: User, actor: User | None,
                 request=None, review: bool = False, source: str = "manual") -> dict:
    """Transfer body: stages every change + audit row, no commit."""
    before = _snapshot(db, customer.id)
    old_rows = [r for r in _primary_owner_rows(db, customer.id) if r.user_id != new_owner.id]
    own_row = next((r for r in _primary_owner_rows(db, customer.id)
                    if r.user_id == new_owner.id), None)
    if own_row is not None and not old_rows:
        raise MembershipError(409, "User is already the primary owner")

    for row in old_rows:
        dup = (
            db.query(AccountMembership)
            .filter(AccountMembership.customer_id == customer.id,
                    AccountMembership.user_id == row.user_id,
                    AccountMembership.role == "co_owner")
            .first()
        )
        if dup is not None:
            db.delete(row)          # already a co-owner: just drop the PO row
        else:
            row.role = "co_owner"   # kept, never dropped
        _sync_junction_owner(db, customer.id, row.user_id, False, actor.id if actor else None)

    if own_row is None:
        # the new owner's co-owner row (if any) is superseded by primary_owner
        db.query(AccountMembership).filter(
            AccountMembership.customer_id == customer.id,
            AccountMembership.user_id == new_owner.id,
            AccountMembership.role == "co_owner",
        ).delete(synchronize_session=False)
        db.flush()
        db.add(AccountMembership(
            user_id=new_owner.id, customer_id=customer.id, role="primary_owner",
            source=source,
        ))
    _sync_junction_owner(db, customer.id, new_owner.id, True, actor.id if actor else None)

    was_flagged = customer.ownership_status == "needs_review"
    if was_flagged:
        customer.ownership_status = None
    db.flush()
    after = _snapshot(db, customer.id)
    _audit(db, actor, "ownership.transfer", customer.id, new_owner.id, {
        "before": before, "after": after,
        "previous_owners": [r.user_id for r in old_rows],
        "new_username": new_owner.username,
        "cleared_needs_review": was_flagged, "review": review,
    }, request)
    return {"customer_id": customer.id, "primary_owner_user_id": new_owner.id,
            "previous_owner_user_ids": [r.user_id for r in old_rows],
            "ownership_status": customer.ownership_status}


def _require_transfer(db: Session, actor_ctx: dict, customer_id: int) -> None:
    role = sales_access.effective_role(actor_ctx)
    ok = role in ("system_admin", "sales_admin") or sales_access.can(
        actor_ctx, db, sales_access.CAP_TRANSFER_OWNERSHIP, customer_id
    )
    if not ok or not sales_access.may_grant_role(actor_ctx, "primary_owner", customer_id, db):
        raise MembershipError(403, "Not permitted to transfer ownership of this account")


def transfer_ownership(db: Session, customer_id: int, new_owner_user_id: int,
                       actor_id: int, request=None, review: bool = False,
                       source: str = "manual") -> dict:
    customer = _get_customer(db, customer_id)
    new_owner = _get_user(db, new_owner_user_id)
    actor_ctx = actor_context(db, actor_id)
    _require_transfer(db, actor_ctx, customer_id)
    if new_owner.id == actor_id and sales_access.effective_role(actor_ctx) != "system_admin":
        # self-escalation: only an existing owner "transfers" to themselves
        # (which is a no-op the rule below rejects)
        held = {m.role for m in _primary_owner_rows(db, customer_id) if m.user_id == actor_id}
        if not held:
            raise MembershipError(403, "You cannot transfer ownership to yourself")
    actor = db.query(User).filter(User.id == actor_id).first()
    try:
        result = _do_transfer(db, customer, new_owner, actor, request, review=review,
                              source=source)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def set_section_grants(db: Session, customer_id: int, user_id: int, grants: dict,
                       actor_id: int, request=None) -> dict:
    _get_customer(db, customer_id)
    target = _get_user(db, user_id)
    actor_ctx = actor_context(db, actor_id)
    _require_grant(db, actor_ctx, "inside_sales", customer_id)
    clean = _validate_grants(grants)
    row = (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer_id,
                AccountMembership.user_id == user_id,
                AccountMembership.role == "inside_sales")
        .first()
    )
    actor = db.query(User).filter(User.id == actor_id).first()
    before = row.section_grants if row is not None else None
    try:
        if row is None:
            row = AccountMembership(
                user_id=target.id, customer_id=customer_id, role="inside_sales",
                source="manual", section_grants=clean,
            )
            db.add(row)
        else:
            row.section_grants = clean
        db.flush()
        _audit(db, actor, "membership.grants", customer_id, target.id,
               {"before": before, "after": clean}, request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return row.to_dict()


# ── global-admin guard ─────────────────────────────────────────────────────


def block_global_admin_change(db: Session, user_id: int) -> bool:
    """True when changing ``is_admin`` on ``user_id`` would leave zero admins."""
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or user.is_admin != 1:
        return False
    others = db.query(User).filter(User.is_admin == 1, User.id != user_id).count()
    return others == 0


# ── ownership review queue ─────────────────────────────────────────────────


def list_ownership_review(db: Session) -> list[dict]:
    customers = (
        db.query(Customer)
        .filter(Customer.ownership_status == "needs_review")
        .order_by(Customer.name)
        .all()
    )
    # ONE batched owners lookup for all review customers (was one query
    # per customer); the per-customer order_by membership id
    # ordering is preserved by the global order.
    owner_rows = (
        db.query(User, AccountMembership)
        .join(AccountMembership, AccountMembership.user_id == User.id)
        .filter(AccountMembership.customer_id.in_([c.id for c in customers]),
                AccountMembership.role == "primary_owner")
        .order_by(AccountMembership.id)
        .all()
    ) if customers else []
    owners_by_customer: dict[int, list] = {}
    for user, membership in owner_rows:
        owners_by_customer.setdefault(membership.customer_id, []).append(user)
    items = []
    for c in customers:
        owners = owners_by_customer.get(c.id, [])
        items.append({
            "customer_id": c.id,
            "name": c.name,
            "current_owner": _name(owners[0]) if owners else None,
            "current_owner_user_id": owners[0].id if owners else None,
            "placeholder": True,
        })
    return items


def resolve_ownership_review(db: Session, customer_id: int, new_owner_user_id: int,
                             actor_id: int, request=None) -> dict:
    customer = _get_customer(db, customer_id)
    if customer.ownership_status != "needs_review":
        raise MembershipError(409, "Account is not awaiting ownership review")
    new_owner = _get_user(db, new_owner_user_id)
    actor_ctx = actor_context(db, actor_id)
    _require_transfer(db, actor_ctx, customer_id)
    actor = db.query(User).filter(User.id == actor_id).first()
    owners = _primary_owner_rows(db, customer_id)
    try:
        if len(owners) == 1 and owners[0].user_id == new_owner.id:
            # confirming the current owner: nothing moves, the flag clears
            customer.ownership_status = None
            _audit(db, actor, "ownership.review_resolved", customer_id, new_owner.id,
                   {"confirmed_owner": new_owner.id}, request)
            result = {"customer_id": customer_id, "primary_owner_user_id": new_owner.id,
                      "previous_owner_user_ids": [], "ownership_status": None}
        else:
            result = _do_transfer(db, customer, new_owner, actor, request, review=True)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


# ── seed / import ──────────────────────────────────────────────────────────


def add_seed_membership(db: Session, customer_id: int, user_id: int, role: str,
                        source: str = "import", details: dict | None = None,
                        request=None, actor_id: int | None = None,
                        commit: bool = True) -> dict:
    """System seed writer: idempotent, no actor grant check, audited
    ``seed.membership`` (details should carry source filename + row number).

    ``actor_id`` is the real admin running the import (audit actor); without
    it the audit actor is ``system:seed``. Re-importing an identical row is a
    no-op that returns the existing membership.
    """
    customer = _get_customer(db, customer_id)
    target = _get_user(db, user_id)
    actor = db.query(User).filter(User.id == actor_id).first() if actor_id else None
    existing = (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer_id,
                AccountMembership.user_id == user_id,
                AccountMembership.role == role)
        .first()
    )
    if existing is not None:
        return existing.to_dict()
    try:
        row = _insert(db, customer, target, role, None, source, actor_id)
        db.flush()
        _audit(db, actor, "seed.membership", customer_id, target.id,
               {"role": role, "source": source, "details": details or {}}, request)
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        raise
    return row.to_dict()


def stage_creator_membership(db: Session, customer: Customer, user_id: int,
                             actor_id: int, request=None) -> AccountMembership | None:
    """Stage the creator's ``primary_owner`` membership in the caller's
    transaction (NO commit — it rides the customer-create transaction).

    Closes the 2026-10-15 gap: ``create_customer`` historically wrote only
    the legacy ``CustomerUser`` owner row, leaving API/UI-created accounts
    without the directive membership model. Idempotent: returns the existing
    row without re-auditing. Defensive guard: if the account already has a
    DIFFERENT primary owner, returns None without staging (creation paths
    only — a fresh customer never has one, but this must never manufacture
    or displace ownership).
    """
    target = _get_user(db, user_id)
    existing = (
        db.query(AccountMembership)
        .filter(AccountMembership.customer_id == customer.id,
                AccountMembership.user_id == target.id,
                AccountMembership.role == "primary_owner")
        .first()
    )
    if existing is not None:
        return existing
    if any(row.user_id != target.id for row in _primary_owner_rows(db, customer.id)):
        return None
    row = AccountMembership(
        user_id=target.id, customer_id=customer.id, role="primary_owner",
        section_grants=None, source="manual",
    )
    db.add(row)
    db.flush()
    actor = db.query(User).filter(User.id == actor_id).first()
    _audit(db, actor, "membership.add", customer.id, target.id,
           {"role": "primary_owner", "source": "manual",
            "details": {"reason": "customer.create"}}, request)
    return row


def find_creator_ownership_gaps(db: Session) -> list[dict]:
    """Legacy owners (``CustomerUser`` role=owner) lacking the
    ``primary_owner`` membership row — the 2026-10-15 gap, read-only.

    ``conflict`` marks ambiguous legacy ownership or accounts where another
    user already holds the primary_owner membership. Such rows must be
    reported, never overwritten.
    """
    rows = (
        db.query(CustomerUser, Customer)
        .join(Customer, Customer.id == CustomerUser.customer_id)
        .filter(CustomerUser.role == "owner")
        .all()
    )
    candidates = {}
    for cu, customer in rows:
        account = candidates.setdefault(customer.id, {"name": customer.name, "owners": set()})
        account["owners"].add(cu.user_id)
    held = {}
    for cid, uid in db.query(AccountMembership.customer_id, AccountMembership.user_id).filter(
        AccountMembership.customer_id.in_(candidates),
        AccountMembership.role == "primary_owner",
    ).all():
        held.setdefault(cid, set()).add(uid)
    gaps = []
    for cid, account in sorted(candidates.items()):
        existing = held.get(cid, set())
        for uid in sorted(account["owners"] - existing):
            ambiguous = len(account["owners"]) > 1
            gaps.append({
                "customer_id": cid, "customer_name": account["name"],
                "owner_user_id": uid, "conflict": bool(existing) or ambiguous,
                "reason": "multiple_legacy_owners" if ambiguous else
                          "existing_primary_owner" if existing else None,
            })
    return gaps


def backfill_creator_ownerships(db: Session, dry_run: bool = True,
                                request=None) -> dict:
    """Repair unambiguous legacy owners; default to a read-only report.

    Reserve the writer before discovering candidates so concurrent
    ownership changes cannot invalidate the apply-time report. The no-op UPDATE
    acquires that reservation without modifying any customer rows, including
    when the caller already has a transaction. Lock/snapshot failures roll back
    the entire pass rather than applying a stale report.
    """
    try:
        if not dry_run:
            if db.get_bind().dialect.name == "postgresql":
                # Block concurrent ownership edits across both representations
                # until discovery and writes commit as one transaction.
                db.execute(text("LOCK TABLE customers, customer_users, account_memberships IN SHARE ROW EXCLUSIVE MODE"))
            else:
                db.execute(text("UPDATE customers SET id = id WHERE 0"))
        gaps = find_creator_ownership_gaps(db)
        to_add = [g for g in gaps if not g["conflict"]]
        conflict_ids = sorted({g["customer_id"] for g in gaps if g["conflict"]})
        if not dry_run:
            for g in to_add:
                db.add(AccountMembership(
                    user_id=g["owner_user_id"], customer_id=g["customer_id"],
                    role="primary_owner", section_grants=None, source="migration",
                ))
            if to_add:
                db.flush()
                _audit(db, None, "ownership.backfill", None, None,
                       {"added": len(to_add), "conflicts_reported": len(conflict_ids),
                        "dry_run": False}, request)
            db.commit()
    except Exception:
        if not dry_run:
            db.rollback()
        raise
    return {
        "dry_run": dry_run, "gaps": len(gaps),
        "added": len(to_add) if not dry_run else 0, "to_add": len(to_add),
        "conflicts": conflict_ids,
        "detail": [{**g, "action": "backfill" if not g["conflict"] else "report_only"}
                   for g in gaps],
    }


# ── sales-team editor sync ─────────────────────────────────────────────────
def sync_from_sales_team(db: Session, customer_id: int, rep_user_id: int,
                         inside_ids: list[int], ops_ids: list[int],
                         actor_id: int | None) -> None:
    """Mirror a sales-team editor write onto memberships (no commit).

    The editor is the operator's correction surface: primary rep becomes the
    sole primary_owner (displaced owners are kept as co_owner, matching the
    transfer rule); inside_sales / sales_ops rows are replaced by the lists
    (retained inside-sales users keep their section grants).
    """
    def rows(role):
        return (
            db.query(AccountMembership)
            .filter(AccountMembership.customer_id == customer_id,
                    AccountMembership.role == role)
            .all()
        )

    for row in rows("primary_owner"):
        if row.user_id == rep_user_id:
            continue
        dup = (
            db.query(AccountMembership)
            .filter(AccountMembership.customer_id == customer_id,
                    AccountMembership.user_id == row.user_id,
                    AccountMembership.role == "co_owner")
            .first()
        )
        if dup is not None:
            db.delete(row)
        else:
            row.role = "co_owner"
    db.flush()
    if not any(r.user_id == rep_user_id for r in rows("primary_owner")):
        db.query(AccountMembership).filter(
            AccountMembership.customer_id == customer_id,
            AccountMembership.user_id == rep_user_id,
            AccountMembership.role == "co_owner",
        ).delete(synchronize_session=False)
        db.add(AccountMembership(
            user_id=rep_user_id, customer_id=customer_id, role="primary_owner",
            source="manual",
        ))

    for role, wanted in (("inside_sales", inside_ids), ("sales_ops", ops_ids)):
        have = {r.user_id: r for r in rows(role)}
        for uid, row in have.items():
            if uid not in wanted:
                db.delete(row)
        for uid in wanted:
            if uid not in have:
                db.add(AccountMembership(
                    user_id=uid, customer_id=customer_id, role=role, source="manual",
                ))
    db.flush()
