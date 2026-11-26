"""Per-customer sales-team reads and corrections (admin correction surface).

The primary rep is the customer's owner junction row (``CustomerUser`` stays
the sole ownership authority). The manager comes from ``SalesReporting`` for
that rep; inside sales and sales ops are customer-specific assignment rows.
Callers own authorization; this module owns the data rules.
"""


from sqlalchemy.orm import Session

from backend.models.sales_access import (
    InsideSalesAssignment,
    SalesOpsAssignment,
    SalesReporting,
)
from backend.models.use_case import Customer, CustomerUser, User
from backend.schemas.sales_team import SalesTeamUpdate
from backend.services import membership_service, sales_access


class SalesTeamError(Exception):
    """Rule violation; ``status_code`` is the HTTP status to surface."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _name(user: User) -> str:
    return user.display_name or user.username


def _primary_owner(db: Session, customer_id: int) -> User | None:
    owners = (
        db.query(User)
        .join(CustomerUser, CustomerUser.user_id == User.id)
        .filter(CustomerUser.customer_id == customer_id, CustomerUser.role == "owner")
        .order_by(CustomerUser.id)
        .all()
    )
    rep_owners = [o for o in owners if o.sales_role == "rep"]
    if len(rep_owners) == 1:
        return rep_owners[0]
    return owners[0] if owners else None


def get_sales_team(db: Session, customer: Customer) -> dict:
    """Editor state (with user ids) for ``customer``'s sales team."""
    owner = _primary_owner(db, customer.id)
    primary_rep = None
    manager = None
    if owner is not None:
        primary_rep = {
            "user_id": owner.id,
            "name": _name(owner),
            "sales_role": owner.sales_role,
        }
        mgr = (
            db.query(User)
            .join(SalesReporting, SalesReporting.manager_user_id == User.id)
            .filter(SalesReporting.rep_user_id == owner.id)
            .first()
        )
        if mgr is not None:
            manager = {"user_id": mgr.id, "name": _name(mgr)}

    inside_users = (
        db.query(User)
        .join(InsideSalesAssignment, InsideSalesAssignment.inside_sales_user_id == User.id)
        .filter(InsideSalesAssignment.customer_id == customer.id)
        .order_by(InsideSalesAssignment.id)
        .all()
    )
    inside_assignments = (
        db.query(InsideSalesAssignment)
        .filter(InsideSalesAssignment.customer_id == customer.id)
        .order_by(InsideSalesAssignment.id)
        .all()
    )
    # Match each user to its assignment row by id order (both queries order
    # by assignment id, so the zipped pairs correspond).
    ops = (
        db.query(User)
        .join(SalesOpsAssignment, SalesOpsAssignment.user_id == User.id)
        .filter(SalesOpsAssignment.customer_id == customer.id)
        .order_by(SalesOpsAssignment.id)
        .all()
    )
    return {
        "customer_id": customer.id,
        "primary_rep": primary_rep,
        "manager": manager,
        "inside_sales": [
            {
                "user_id": u.id,
                "name": _name(u),
                "auto_linked": a.auto_linked,
                "link_reason": a.link_reason,
            }
            for u, a in zip(inside_users, inside_assignments)
        ],
        "sales_ops": [{"user_id": u.id, "name": _name(u)} for u in ops],
    }


def _dedupe(ids: list[int]) -> list[int]:
    return list(dict.fromkeys(ids))


def update_sales_team(
    db: Session, customer: Customer, payload: SalesTeamUpdate, actor_id: int | None
) -> list[dict]:
    """Apply a correction; returns audit events ``{action, target_id, details}``.

    Raises ``SalesTeamError`` (400/404) before any write when the request is
    invalid; all writes commit together.
    """
    if payload.primary_rep_user_id is None:
        raise SalesTeamError(400, "cannot clear primary rep")

    inside_ids = _dedupe(payload.inside_sales_user_ids)
    ops_ids = _dedupe(payload.sales_ops_user_ids)
    wanted = {payload.primary_rep_user_id, *inside_ids, *ops_ids}
    if payload.manager_user_id is not None:
        wanted.add(payload.manager_user_id)
    found = {
        u.id: u for u in db.query(User).filter(User.id.in_(wanted)).all()
    }
    missing = sorted(wanted - set(found))
    if missing:
        raise SalesTeamError(404, f"User not found: {missing[0]}")

    rep = found[payload.primary_rep_user_id]
    if payload.manager_user_id is not None:
        if payload.manager_user_id == rep.id:
            raise SalesTeamError(400, "A rep cannot report to themselves")
        if payload.manager_user_id in sales_access._transitive_report_ids(db, rep.id):
            raise SalesTeamError(400, "Manager assignment would create a reporting cycle")

    before = get_sales_team(db, customer)
    events: list[dict] = []

    # Primary rep: single owner junction row; displaced owners keep access.
    owner_rows = (
        db.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer.id, CustomerUser.role == "owner")
        .all()
    )
    for row in owner_rows:
        if row.user_id != rep.id:
            row.role = "member"
    rep_row = (
        db.query(CustomerUser)
        .filter(CustomerUser.customer_id == customer.id, CustomerUser.user_id == rep.id)
        .first()
    )
    if rep_row is None:
        db.add(CustomerUser(
            customer_id=customer.id, user_id=rep.id, role="owner", granted_by=actor_id,
        ))
    else:
        rep_row.role = "owner"
    prev_rep = (before["primary_rep"] or {}).get("user_id")
    if prev_rep != rep.id:
        events.append({
            "action": "set_primary_rep",
            "target_id": rep.id,
            "details": f"primary_rep={rep.id} ({_name(rep)}); previous={prev_rep}",
        })

    # Manager: this rep's reporting row only.
    db.query(SalesReporting).filter(SalesReporting.rep_user_id == rep.id).delete(
        synchronize_session=False
    )
    if payload.manager_user_id is not None:
        db.add(SalesReporting(rep_user_id=rep.id, manager_user_id=payload.manager_user_id))
    prev_mgr = (before["manager"] or {}).get("user_id")
    if prev_mgr != payload.manager_user_id or prev_rep != rep.id:
        mgr = found.get(payload.manager_user_id)
        events.append({
            "action": "set_manager",
            "target_id": payload.manager_user_id,
            "details": (
                f"rep={rep.id}; manager={payload.manager_user_id}"
                + (f" ({_name(mgr)})" if mgr else "")
            ),
        })

    # Inside sales / sales ops: replace this customer's assignment rows.
    db.query(InsideSalesAssignment).filter(
        InsideSalesAssignment.customer_id == customer.id
    ).delete(synchronize_session=False)
    for uid in inside_ids:
        db.add(
            InsideSalesAssignment(
                inside_sales_user_id=uid,
                customer_id=customer.id,
                rep_user_id=rep.id,
                auto_linked=False,
                link_reason=None,
            )
        )
    if inside_ids != [u["user_id"] for u in before["inside_sales"]]:
        events.append({
            "action": "set_inside_sales",
            "target_id": None,
            "details": "inside_sales=" + ", ".join(f"{i} ({_name(found[i])})" for i in inside_ids),
        })

    db.query(SalesOpsAssignment).filter(
        SalesOpsAssignment.customer_id == customer.id
    ).delete(synchronize_session=False)
    for uid in ops_ids:
        db.add(SalesOpsAssignment(user_id=uid, customer_id=customer.id))
    if ops_ids != [u["user_id"] for u in before["sales_ops"]]:
        events.append({
            "action": "set_sales_ops",
            "target_id": None,
            "details": "sales_ops=" + ", ".join(f"{i} ({_name(found[i])})" for i in ops_ids),
        })

    # keep the account_memberships rows in step with the junction/assignments
    db.flush()
    membership_service.sync_from_sales_team(
        db, customer.id, rep.id, inside_ids, ops_ids, actor_id,
    )

    db.commit()
    return events
