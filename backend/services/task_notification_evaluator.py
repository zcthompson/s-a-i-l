"""Explicitly started, restart-safe task notification evaluation."""

import logging
import threading
from datetime import UTC, datetime

from sqlalchemy import or_

from backend.models.account_membership import AccountMembership
from backend.models.customer_engagement import CustomerTask, TaskNotificationWindow
from backend.models.use_case import Customer, CustomerUser, User, get_session
from backend.services import customer_engagement_service as service
from backend.services import sales_access
from backend.services.dialect_insert import insert_for

INITIAL_DELAY_SECONDS = 60
SCAN_INTERVAL_SECONDS = 900
logger = logging.getLogger(__name__)


def _batched_user_contexts(db, usernames) -> tuple[dict, dict]:
    """One batched load of the resolver context for the given assignees
    (re-recon A-7 — was one query per flagged task).

    Returns {username: user dict} with the junction customer ids and the
    live membership roles preloaded, so ``sales_access`` never issues
    follow-up lookups for them. Expired memberships are excluded (the
    same rule as ``load_membership_context``).
    """
    now = datetime.utcnow()
    users = {
        u.username: u
        for u in db.query(User).filter(User.username.in_(usernames), User.is_active == 1)
    }
    if not users:
        return {}, {}
    uids = [u.id for u in users.values()]
    junction: dict[int, list] = {}
    for row in db.query(CustomerUser).filter(CustomerUser.user_id.in_(uids)).all():
        junction.setdefault(row.user_id, []).append(row.customer_id)
    memberships: dict[int, dict] = {}
    rows = (
        db.query(AccountMembership)
        .filter(
            AccountMembership.user_id.in_(uids),
            or_(AccountMembership.expires_at.is_(None), AccountMembership.expires_at > now),
        )
        .all()
    )
    for m in rows:
        memberships.setdefault(m.user_id, {}).setdefault(m.customer_id, []).append(m.role)
    contexts = {
        username: {
            "user_id": u.id, "username": u.username, "is_admin": u.is_admin,
            "role": u.role, "sales_role": u.sales_role,
            "customer_ids": junction.get(u.id, []),
            "membership_roles": memberships.get(u.id, {}),
        }
        for username, u in users.items()
    }
    return contexts, users


def _read_ok(db, user: dict, cache: dict, customer_id: int) -> bool:
    """Central READ on ``customer_id`` — byte-equivalent to
    ``sales_access.can(user, db, CAP_READ, customer_id)`` (for every role:
    admin unrestricted; ps_admin confined to nothing here; auditor /
    sales_admin read-all, which ``customer_scope`` already models; and for
    all other roles every in-scope customer carries at least an auditor
    level in ``_access``). The scope is computed once per user per scan."""
    if user.get("is_admin") == 1:
        return True
    if sales_access.effective_role(user) == "ps_admin":
        return False
    scope = cache.get(user["user_id"])
    if scope is None:
        scope = sales_access.customer_scope(user, db)
        cache[user["user_id"]] = scope
    return customer_id in scope


def scan_task_notifications(db, now=None):
    """One DB-only pass; no timers or process-local deduplication state."""
    now = service.utc(now or datetime.now(UTC))
    tasks = db.query(CustomerTask).filter(CustomerTask.status.in_(("open", "in_progress")),
        or_(CustomerTask.due_at.is_not(None), CustomerTask.due_date.is_not(None))).all()
    flagged = []
    for task in tasks:
        flags = service.due_flags(task, now)
        window = "overdue" if flags["overdue"] else "due_soon" if flags["due_soon"] else None
        if window is None or task.assignee is None:
            continue
        flagged.append((task, window))
    notifications = []
    if flagged:
        contexts, orm_users = _batched_user_contexts(db, {task.assignee for task, _ in flagged})
        scopes: dict = {}
        # ONE batched customer-name lookup for the flagged tasks (re-recon
        # A-7 — the notification message embeds the customer name).
        customer_names = {
            c.id: c.name
            for c in db.query(Customer).filter(
                Customer.id.in_({task.customer_id for task, _ in flagged})
            )
        }
        for task, window in flagged:
            user = contexts.get(task.assignee)
            if user is None or not _read_ok(db, user, scopes, task.customer_id):
                continue
            result = db.execute(insert_for(db, TaskNotificationWindow).values(task_id=task.id, window=window,
                user_name=task.assignee).on_conflict_do_nothing(index_elements=["task_id", "window", "user_name"])
                .returning(TaskNotificationWindow.id)).scalar_one_or_none()
            if result is not None:
                # Pre-resolved recipient/name: the per-task lookups inside
                # _notification are skipped on the batched path (the access
                # decision is the evaluator's _read_ok above, equivalent to
                # the central READ — see its docstring).
                notification = service._notification(db, task, task.assignee, f"task_{window}",
                                                     recipient=orm_users.get(task.assignee),
                                                     customer_name=customer_names.get(task.customer_id))
                if notification is not None:
                    notifications.append(notification)
    service._commit(db, notifications)
    return len(notifications)


def start_task_evaluator():
    """Start only from app lifespan; return a stop event for clean shutdown."""
    stop = threading.Event()

    def run():
        if stop.wait(INITIAL_DELAY_SECONDS):
            return
        while not stop.is_set():
            try:
                with get_session() as db:
                    scan_task_notifications(db)
            except Exception:
                logger.exception("Task notification scan failed")
            if stop.wait(SCAN_INTERVAL_SECONDS):
                return

    threading.Thread(target=run, name="task-notification-evaluator", daemon=True).start()
    return stop
