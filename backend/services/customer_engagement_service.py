"""Recorded interactions and durable, versioned follow-up tasks."""

from datetime import UTC, date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import (
    ACTIVITY_TYPES,
    TASK_STATUSES,
    CustomerActivity,
    CustomerTask,
    activity_contacts,
    task_evidence_activities,
    task_evidence_notes,
)
from backend.models.customer_technology import CustomerTechnology
from backend.models.intelligence_import import PartnerPipeline
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, User
from backend.services import email_service, record_cleanup, sales_access
from backend.services.collaboration_service import CollaborationService

CONFLICT = "Task changed since you loaded it; reload and retry"
TRANSITIONS = {
    "open": {"in_progress", "completed", "cancelled"},
    "in_progress": {"open", "completed", "cancelled"},
    "completed": {"open"}, "cancelled": set(),
}
TASK_NOTIFICATION_TYPES = ("task_assigned", "task_reassigned", "task_completed", "task_due_soon", "task_overdue")


def utc(value):
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _wire(row):
    result = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        result[column.name] = (utc(value).isoformat() if isinstance(value, datetime)
                               else value.isoformat() if isinstance(value, date) else value)
    return result


def due_flags(task, now=None):
    now = utc(now or datetime.now(UTC))
    if task.status not in ("open", "in_progress"):
        return {"overdue": False, "due_soon": False}
    if task.due_at:
        due = utc(task.due_at)
        return {"overdue": due < now, "due_soon": now < due <= now + timedelta(hours=24)}
    if task.due_date:
        return {"overdue": task.due_date < now.date(), "due_soon": task.due_date == now.date()}
    return {"overdue": False, "due_soon": False}


def render_due(task):
    return utc(task.due_at).strftime("%Y-%m-%d %H:%M UTC") if task.due_at else task.due_date.isoformat()


def _dates(data, current, prefix, required=False):
    instant, day = f"{prefix}_at", f"{prefix}_date"
    at = data.get(instant, getattr(current, instant, None))
    on = data.get(day, getattr(current, day, None))
    if at and on:
        raise HTTPException(422, f"Provide {'exactly' if required else 'at most'} one of {instant} or {day}")
    if required and not (at or on):
        raise HTTPException(422, "An activity needs an occurred date (occurred_at or occurred_date)")
    if data.get(instant):
        data[instant] = utc(data[instant]).replace(tzinfo=None)


def _user(db, value, label):
    if value is None or db.query(User.id).filter_by(username=value).first() is None:
        raise HTTPException(422, f"Unknown {label}")


def _links(db, customer_id, data, specs):
    links = []
    for field, table, key, model, label in specs:
        if field not in data:
            continue
        ids = sorted(set(data.pop(field)))
        found = {row[0] for row in db.query(model.id).filter(model.id.in_(ids), model.customer_id == customer_id)} if ids else set()
        for related_id in ids:
            if related_id not in found:
                raise HTTPException(422, f"Related {label} {related_id} does not belong to this customer")
        links.append((table, key, ids))
    return links


def _replace_links(db, row_id, parent_key, links):
    for table, key, ids in links:
        db.execute(delete(table).where(table.c[parent_key] == row_id))
        if ids:
            db.execute(table.insert(), [{parent_key: row_id, key: value} for value in ids])


ACTIVITY_LINKS = (("contact_ids", activity_contacts, "contact_id", CustomerContact, "contact"),)
TASK_LINKS = (("evidence_note_ids", task_evidence_notes, "note_id", SalesNote, "note"),
              ("evidence_activity_ids", task_evidence_activities, "activity_id", CustomerActivity, "activity"))


def _activity_payload(db, customer_id, payload, current=None):
    data = dict(payload)
    _dates(data, current, "occurred", required=True)
    if data.get("type", getattr(current, "type", None)) not in ACTIVITY_TYPES:
        raise HTTPException(422, "Unknown activity type")
    if current is None or "actor" in data:
        _user(db, data.get("actor"), "actor")
    links = _links(db, customer_id, data, ACTIVITY_LINKS)
    allowed = {"type", "occurred_at", "occurred_date", "actor", "source", "outcome"}
    return {k: v for k, v in data.items() if k in allowed}, links


def list_activities(db, customer_id, activity_id=None):
    query = db.query(CustomerActivity).filter_by(customer_id=customer_id)
    if activity_id is not None:
        query = query.filter(CustomerActivity.id == activity_id)
    rows = query.order_by(func.coalesce(CustomerActivity.occurred_date, func.date(CustomerActivity.occurred_at)).desc(),
                          CustomerActivity.id).all()
    ids = [row.id for row in rows]
    links = db.execute(select(activity_contacts).where(activity_contacts.c.activity_id.in_(ids))).all()
    contacts = dict(db.query(CustomerContact.id, CustomerContact.display_name).filter(
        CustomerContact.id.in_({row.contact_id for row in links})).all())
    attendees = {row_id: [] for row_id in ids}
    for link in sorted(links, key=lambda link: (link.activity_id, link.contact_id)):
        attendees[link.activity_id].append({"contact_id": link.contact_id, "display_name": contacts[link.contact_id]})
    return [{**_wire(row), "attendees": attendees[row.id]} for row in rows]


def create_activity(db, customer_id, payload, username):
    data, links = _activity_payload(db, customer_id, payload)
    row = CustomerActivity(customer_id=customer_id, created_by=username, **data)
    db.add(row)
    db.flush()
    _replace_links(db, row.id, "activity_id", links)
    row_id = row.id
    db.commit()
    return list_activities(db, customer_id, row_id)[0]


def update_activity(db, row, payload, username):
    data, links = _activity_payload(db, row.customer_id, payload, row)
    for key, value in data.items():
        setattr(row, key, value)
    _replace_links(db, row.id, "activity_id", links)
    row_id, customer_id = row.id, row.customer_id
    db.commit()
    return list_activities(db, customer_id, row_id)[0]


def delete_activity(db, row):
    record_cleanup.activities(db, [row.id])
    db.delete(row)
    db.commit()


def _task_payload(db, customer_id, payload, current=None):
    data = dict(payload)
    _dates(data, current, "due")
    if current is None or "title" in data:
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            raise HTTPException(422, "title is required")
        data["title"] = data["title"].strip()
    if data.get("assignee") is not None:
        _user(db, data["assignee"], "assignee")
    if "status" in data and data["status"] not in TASK_STATUSES:
        raise HTTPException(422, "Unknown task status")
    links = _links(db, customer_id, data, TASK_LINKS)
    allowed = {"title", "detail", "assignee", "due_at", "due_date", "status"}
    return {k: v for k, v in data.items() if k in allowed}, links


def _task_query(db, counts=False):
    assignee = aliased(User)
    readable = sales_access.account_read_predicate(assignee, CustomerTask.customer_id)
    needs = and_(CustomerTask.assignee.is_not(None), or_(assignee.id.is_(None),
                  func.coalesce(assignee.is_active, 0) != 1, ~readable))
    query = db.query(CustomerTask, needs.label("needs_reassignment")).outerjoin(
        assignee, assignee.username == CustomerTask.assignee)
    if counts:
        for table in (task_evidence_notes, task_evidence_activities):
            query = query.add_columns(select(func.count()).select_from(table).where(
                table.c.task_id == CustomerTask.id).correlate(CustomerTask).scalar_subquery())
    return query


def _task_dict(row, notes=0, activities=0, now=None):
    task, needs = row[:2]
    return {**_wire(task), "evidence_note_count": notes, "evidence_activity_count": activities,
            **due_flags(task, now), "needs_reassignment": bool(needs)}


def _due_order():
    due = func.coalesce(CustomerTask.due_date, func.date(CustomerTask.due_at))
    return (due.is_(None), due, CustomerTask.id)


def list_tasks(db, customer_id, status=None, mine=None, task_id=None):
    query = _task_query(db).filter(CustomerTask.customer_id == customer_id)
    if status is not None:
        if status not in TASK_STATUSES:
            raise HTTPException(422, "Unknown task status")
        query = query.filter(CustomerTask.status == status)
    if mine is not None:
        query = query.filter(CustomerTask.assignee == mine)
    if task_id is not None:
        query = query.filter(CustomerTask.id == task_id)
    rows = query.order_by(*_due_order()).all()
    ids = [row[0].id for row in rows]
    counts = []
    for table in (task_evidence_notes, task_evidence_activities):
        counts.append(dict(db.execute(select(table.c.task_id, func.count()).where(
            table.c.task_id.in_(ids)).group_by(table.c.task_id)).all()))
    now = datetime.now(UTC)
    return [_task_dict(row, counts[0].get(row[0].id, 0), counts[1].get(row[0].id, 0), now) for row in rows]


def my_tasks(db, user, *, limit=None, now=None):
    reader = aliased(User)
    rows = _task_query(db, counts=True).filter(CustomerTask.assignee == user["username"],
        CustomerTask.status.in_(("open", "in_progress"))).join(
            Customer, Customer.id == CustomerTask.customer_id).join(
            reader, reader.username == user["username"]).filter(
            reader.is_active == 1, sales_access.account_read_predicate(reader, CustomerTask.customer_id)
        ).order_by(*_due_order())
    if limit is not None:
        rows = rows.limit(limit)
    rows = rows.all()
    ids = {row[0].customer_id for row in rows}
    names = dict(db.query(Customer.id, Customer.name).filter(Customer.id.in_(ids)).all())
    now = now or datetime.now(UTC)
    return [{**_task_dict(row, row[2], row[3], now), "customer_name": names[row[0].customer_id]}
            for row in rows if row[0].customer_id in names]


def _notification(db, task, username, event, completer=None, recipient=None,
                  customer_name=None):
    """Stage the collaboration notification for a task event.

    ``recipient`` / ``customer_name`` are pre-resolution seams (re-recon
    A-7): a batched caller (the task notification evaluator) passes the
    already-resolved row/name so the per-task lookups are skipped; the
    single-event callers (assign / reassign / complete) omit them and the
    lookups run exactly as before.
    """
    if not username:
        return None
    if recipient is None:
        recipient = db.query(User).filter(User.username == username, User.is_active == 1,
            sales_access.account_read_predicate(User, task.customer_id)).first()
    if recipient is None:
        return None
    if customer_name is None:
        customer_name = db.query(Customer.name).filter_by(id=task.customer_id).scalar()
    messages = {
        "task_assigned": f"You were assigned task {task.title} on {customer_name}.",
        "task_reassigned": f"Task {task.title} on {customer_name} was reassigned to you.",
        "task_completed": f"Task {task.title} on {customer_name} was completed by {completer}.",
    }
    if event in ("task_due_soon", "task_overdue"):
        due = render_due(task)
        message = (f"Task {task.title} on {customer_name} is due soon ({due})." if event == "task_due_soon"
                   else f"Task {task.title} on {customer_name} is overdue (was due {due}).")
    else:
        message = messages[event]
    return CollaborationService.stage_notification(db, username, event, message, task.customer_id)


def _commit(db, notifications=()):
    # Flushing obtains row ids; wakes are scheduled only after the actual commit.
    db.flush()
    wakes = [(row.user_name, row.id) for row in notifications if row is not None]
    db.commit()
    from backend.services.notification_service import connection_manager
    for username, row_id in wakes:
        connection_manager.schedule_send_to_user(username, {"type": "notification", "id": row_id})
    for row in notifications:
        if row is not None:
            email_service.deliver_notification_email(db, row)


def create_task(db, customer_id, payload, username):
    data, links = _task_payload(db, customer_id, payload)
    if data.get("status") == "completed":
        data.update(completed_by=username, completed_at=datetime.now(UTC).replace(tzinfo=None))
    row = CustomerTask(customer_id=customer_id, created_by=username, version=1, **data)
    db.add(row)
    db.flush()
    _replace_links(db, row.id, "task_id", links)
    row_id = row.id
    notification = _notification(db, row, row.assignee, "task_assigned")
    _commit(db, [notification])
    return list_tasks(db, customer_id, task_id=row_id)[0]


def update_task(db, row, payload, username):
    expected = payload.get("expected_version")
    if expected != row.version:
        raise HTTPException(409, CONFLICT)
    data, links = _task_payload(db, row.customer_id, payload, row)
    before_status, before_assignee = row.status, row.assignee
    status = data.get("status", before_status)
    if status != before_status:
        if status not in TRANSITIONS[before_status]:
            raise HTTPException(422, f"Invalid task status transition from {before_status} to {status}")
        if status == "completed":
            data.update(completed_by=username, completed_at=datetime.now(UTC).replace(tzinfo=None))
        elif before_status == "completed":
            data.update(completed_by=None, completed_at=None)
    row_id, customer_id = row.id, row.customer_id
    # Compare-and-swap in the database handles overlapping requests, not just stale ORM rows.
    changed = db.execute(update(CustomerTask).where(CustomerTask.id == row_id,
        CustomerTask.version == expected).values(**data, version=expected + 1,
        updated_at=datetime.now(UTC).replace(tzinfo=None)), execution_options={"synchronize_session": False}).rowcount
    if not changed:
        db.rollback()
        raise HTTPException(409, CONFLICT)
    _replace_links(db, row_id, "task_id", links)
    db.refresh(row)
    notifications = []
    if row.assignee != before_assignee:
        notifications.append(_notification(db, row, row.assignee, "task_reassigned"))
    if status == "completed" and status != before_status and row.created_by != username:
        notifications.append(_notification(db, row, row.created_by, "task_completed", username))
    _commit(db, notifications)
    return list_tasks(db, customer_id, task_id=row_id)[0]


def delete_task(db, row, expected_version):
    if expected_version != row.version:
        raise HTTPException(409, CONFLICT)
    # Reserve the version before child deletes so a racing update cannot win afterwards.
    changed = db.execute(update(CustomerTask).where(CustomerTask.id == row.id,
        CustomerTask.version == expected_version).values(version=expected_version + 1),
        execution_options={"synchronize_session": False}).rowcount
    if not changed:
        db.rollback()
        raise HTTPException(409, CONFLICT)
    record_cleanup.tasks(db, [row.id])
    db.execute(delete(CustomerTask).where(CustomerTask.id == row.id))
    db.commit()


def promote_task(db, customer_id, payload, username):
    kind, source_id = payload["source_type"], payload["source_id"]
    source = None
    if kind in ("note", "renewal_attention", "eol_attention"):
        model = {"note": SalesNote, "renewal_attention": PartnerPipeline,
                 "eol_attention": CustomerTechnology}[kind]
        source = db.query(model).filter_by(id=source_id, customer_id=customer_id).first()
        valid = source is not None
    else:
        valid = kind == "contact_coverage" and source_id == customer_id
    if not valid:
        raise HTTPException(422, "Unknown or out-of-scope promotion source")
    key = f"{kind}:{source_id}"
    existing = db.query(CustomerTask.id).filter_by(customer_id=customer_id, source_key=key).scalar()
    if existing is not None:
        return {"created": False, "task": list_tasks(db, customer_id, task_id=existing)[0]}
    title = payload.get("title")
    if title is None:
        title = (f"Review EOL: {source.name}"[:255] if kind == "eol_attention" else
                 source.title if kind == "note" else
                 (source.opportunity_name or "Renewal follow-up") if kind == "renewal_attention" else "Review contact coverage")
    data, links = _task_payload(db, customer_id, {"title": title, "detail": payload.get("detail")})
    task = CustomerTask(customer_id=customer_id, created_by=username, source_type=kind,
                        source_id=source_id, source_key=key, version=1, **data)
    try:
        db.add(task)
        db.flush()
        if kind == "note":
            db.execute(task_evidence_notes.insert().values(task_id=task.id, note_id=source_id))
        task_id = task.id
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.query(CustomerTask.id).filter_by(customer_id=customer_id, source_key=key).scalar()
        if existing is None:
            raise
        return {"created": False, "task": list_tasks(db, customer_id, task_id=existing)[0]}
    return {"created": True, "task": list_tasks(db, customer_id, task_id=task_id)[0]}
