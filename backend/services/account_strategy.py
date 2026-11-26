"""Recorded account strategies and evidence-derived suggestions."""
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, update

from backend.models.account_strategy import (
    AccountStrategy,
    AccountStrategySnapshot,
    strategy_contact_links,
    strategy_note_links,
    strategy_task_links,
)
from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import CustomerTask
from backend.models.customer_technology import CustomerTechnology
from backend.models.sales_note import SalesNote
from backend.models.use_case import UseCase
from backend.services import customer_contact_service, pipeline_read_model
from backend.services.customer_engagement_service import (
    _due_order,
    _links,
    _replace_links,
    render_due,
    utc,
)

FIELDS = ("objectives", "desired_outcomes", "risks", "plays", "discovery_gaps")
MAX_FIELD = 10000
CONFLICT = "Strategy changed since you loaded it; reload and retry"
SUGGESTION_CALC_VERSION = "strategy-suggestions/1"
SPECS = (("task_ids", strategy_task_links, "task_id", CustomerTask, "task"),
         ("contact_ids", strategy_contact_links, "contact_id", CustomerContact, "contact"),
         ("note_ids", strategy_note_links, "note_id", SalesNote, "note"))


def _iso(value):
    return utc(value).isoformat() if value else None


def _plan(row):
    return {"id": row.id, **{f: getattr(row, f) for f in FIELDS}, "version": row.version,
            "created_by": row.created_by, "created_at": _iso(row.created_at),
            "updated_by": row.updated_by, "updated_at": _iso(row.updated_at)}


def _linked(db, row_id):
    result = {}
    for name, table, key, model, columns in (
        ("tasks", strategy_task_links, "task_id", CustomerTask, (CustomerTask.id, CustomerTask.title, CustomerTask.status)),
        ("contacts", strategy_contact_links, "contact_id", CustomerContact, (CustomerContact.id, CustomerContact.display_name)),
        ("notes", strategy_note_links, "note_id", SalesNote, (SalesNote.id, SalesNote.title))):
        rows = db.query(*columns).join(table, table.c[key] == model.id).filter(table.c.strategy_id == row_id).order_by(model.id).all()
        keys = (key, "title", "status") if name == "tasks" else (key, "display_name" if name == "contacts" else "title")
        result[name] = [dict(zip(keys, row)) for row in rows]
    return result


def suggestions_for(db, customer_id, *, reference_date=None, as_of=None):
    now = datetime.now(UTC)
    reference_date = reference_date or now.date()
    as_of = as_of or now.isoformat()
    if isinstance(as_of, datetime):
        as_of = utc(as_of).isoformat()
    result = {"calculation_version": SUGGESTION_CALC_VERSION, "as_of": as_of,
              "reference_date": reference_date.isoformat(), **{f: [] for f in FIELDS}, "next_actions": []}
    def add(field, text, source):
        result[field].append({"text": text, "source": source})
    pipeline = pipeline_read_model.pipeline_summary_for(db, customer_id)
    grain, source = pipeline["grain"], pipeline["source"]
    if grain["line_count"]:
        add("objectives", f"Advance the recorded partner-pipeline opportunities ({grain['line_count']} line(s), {grain['opportunity_count']} opportunity number(s)) — source: pipeline import #{source['import_id']} ({source['source_file']})", "partner pipeline")
    renewal = pipeline_read_model.renewal_attention_summaries_for(db, [customer_id], reference_date=reference_date, as_of=as_of)[customer_id]
    buckets = renewal["buckets"]
    count = sum(len(buckets[k]) for k in ("overdue", "within_30", "within_60", "within_90"))
    if count:
        add("objectives", f"Work the {count} recorded renewal(s) due within 90 days or past their recorded end date — source: recorded renewal evidence", "recorded renewal evidence")
    for card in (buckets["overdue"] + buckets["within_30"])[:3]:
        add("risks", f"Renewal {card['opportunity_number']} ({card['opportunity_name'] or 'not recorded'}): recorded end date {card['renewal_date'] or 'not recorded'}, {card['days']} days from reference — source: recorded renewal evidence", "recorded renewal evidence")
    tech = db.query(CustomerTechnology).filter_by(customer_id=customer_id, support_state="no_support").order_by(CustomerTechnology.name, CustomerTechnology.id).limit(2).all()
    for item in tech:
        add("risks", f"{item.name} ({item.version_edition or 'not recorded'}) recorded with support state no_support — source: technology inventory", "technology inventory")
    cases = db.query(UseCase).filter_by(customer_id=customer_id).order_by(UseCase.updated_at.desc(), UseCase.id.desc()).limit(3).all()
    for item in cases:
        add("desired_outcomes", f'Assessed use case: "{item.title}" — source: assessment records', "assessment records")
    tasks = db.query(CustomerTask).filter(CustomerTask.customer_id == customer_id, CustomerTask.status.in_(("open", "in_progress"))).order_by(*_due_order()).all()
    def due(task):
        return render_due(task) if task.due_at or task.due_date else None
    if tasks:
        add("plays", f"Follow through on the {len(tasks)} open task(s) (next due: {due(tasks[0]) or 'none recorded'}) — source: task records", "task records")
    result["next_actions"] = [{"task_id": t.id, "title": t.title, "status": t.status, "due": due(t), "assignee": t.assignee} for t in tasks[:5]]
    coverage = customer_contact_service.contact_coverage_for(db, customer_id)
    if coverage["contacts_recorded"]:
        add("plays", f"Work the {coverage['contacts_recorded']} recorded contact(s) — source: contact records", "contact records")
    for gap in coverage["gaps"]:
        add("discovery_gaps", gap, "contact coverage")
    if coverage["last_contacted"] is None:
        add("discovery_gaps", "No recorded activity or dated note — source: engagement basis", "engagement basis")
    return result


def get_strategy(db, customer_id, *, reference_date=None, as_of=None):
    row = db.query(AccountStrategy).filter_by(customer_id=customer_id).first()
    plan = {**_plan(row), "links": _linked(db, row.id)} if row else None
    count = db.query(func.count(AccountStrategySnapshot.id)).filter_by(customer_id=customer_id).scalar_subquery()
    latest = db.query(AccountStrategySnapshot, count).filter_by(customer_id=customer_id).order_by(AccountStrategySnapshot.plan_number.desc()).first()
    summary = {"count": latest[1] if latest else 0, "latest": None}
    if latest:
        snap = latest[0]
        summary["latest"] = {"plan_number": snap.plan_number, "note": snap.note, "published_by": snap.published_by, "published_at": _iso(snap.published_at)}
    return {"plan": plan, "suggestions": suggestions_for(db, customer_id, reference_date=reference_date, as_of=as_of), "snapshots": summary}


def save_strategy(db, customer_id, payload, username):
    if "expected_version" not in payload:
        raise HTTPException(422, "expected_version is required")
    expected = payload["expected_version"]
    if type(expected) is not int:
        raise HTTPException(422, "expected_version must be an integer")
    data = {f: payload[f] for f in FIELDS if f in payload}
    for name, value in data.items():
        if value is not None and not isinstance(value, str):
            raise HTTPException(422, f"Field {name} must be a string or null")
        if value is not None and len(value) > MAX_FIELD:
            raise HTTPException(422, f"Field {name} must be at most 10000 characters")
    row = db.query(AccountStrategy).filter_by(customer_id=customer_id).first()
    now = datetime.now(UTC).replace(tzinfo=None)
    if row is None:
        if expected != 0:
            raise HTTPException(409, CONFLICT)
        row = AccountStrategy(customer_id=customer_id, version=1, created_by=username, updated_by=username, created_at=now, updated_at=now, **data)
        db.add(row)
    else:
        changed = db.execute(update(AccountStrategy).where(AccountStrategy.id == row.id, AccountStrategy.version == expected).values(**data, version=expected + 1, updated_by=username, updated_at=now), execution_options={"synchronize_session": False}).rowcount
        if not changed:
            db.rollback()
            raise HTTPException(409, CONFLICT)
        db.refresh(row)
    db.commit()
    db.refresh(row)
    return _plan(row)


def set_links(db, strategy_id, payload, username):
    row = db.get(AccountStrategy, strategy_id) if strategy_id is not None else None
    if row is None:
        raise HTTPException(422, "No strategy recorded; save a strategy before linking")
    for name, *_ in SPECS:
        if not isinstance(payload.get(name), list) or any(type(i) is not int for i in payload[name]):
            raise HTTPException(422, f"Field {name} must be a list of integers")
    links = _links(db, row.customer_id, dict(payload), SPECS)
    _replace_links(db, row.id, "strategy_id", links)
    db.commit()
    return _linked(db, row.id)


def _snapshot(row, content=False):
    result = {"id": row.id, "plan_number": row.plan_number, "note": row.note, "published_by": row.published_by, "published_at": _iso(row.published_at)}
    if content:
        result["content"] = row.content
    return result


def publish_snapshot(db, customer_id, payload, username):
    row = db.query(AccountStrategy).filter_by(customer_id=customer_id).first()
    if row is None or all(getattr(row, f) is None for f in FIELDS):
        raise HTTPException(422, "No strategy content recorded to publish")
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        raise HTTPException(422, "note must be a string")
    if note is not None and len(note) > 200:
        raise HTTPException(422, "note must be at most 200 characters")
    number = db.query(func.max(AccountStrategySnapshot.plan_number)).filter_by(customer_id=customer_id).scalar() or 0
    snap = AccountStrategySnapshot(customer_id=customer_id, plan_number=number + 1, note=note, published_by=username, published_at=datetime.now(UTC).replace(tzinfo=None), content={**{f: getattr(row, f) for f in FIELDS}, "version": row.version})
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return _snapshot(snap, True)


def list_snapshots(db, customer_id):
    return [_snapshot(row) for row in db.query(AccountStrategySnapshot).filter_by(customer_id=customer_id).order_by(AccountStrategySnapshot.plan_number.desc()).all()]


def get_snapshot(db, customer_id, snapshot_id):
    row = db.query(AccountStrategySnapshot).filter_by(customer_id=customer_id, id=snapshot_id).first()
    if row is None:
        raise HTTPException(404, "Strategy snapshot not found")
    return _snapshot(row, True)


def restore_snapshot(db, customer_id, snapshot_id, payload, username):
    content = get_snapshot(db, customer_id, snapshot_id)["content"]
    return save_strategy(db, customer_id, {**payload, **{f: content[f] for f in FIELDS}}, username)
