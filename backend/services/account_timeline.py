"""Account 360 timeline: a DERIVED, read-only, reverse-chronological feed.

One bounded query per source, merged and ordered in Python (no UNION, no
stored event table). Imports are labelled ``imported`` and are never business
events; the feed does not feed engagement recency. All date math uses the
injected ``now`` (H6 A2 pattern). The service never writes.

Ordering (ascending sort key == feed order):
    (timestamp is null, timestamp desc, kind order, id desc nulls last)
Date-only items sort at 00:00 UTC of their day, so on a shared day an
instant precedes a date-only item; exact ties fall through to kind order.
"""

import base64
import binascii
import json
from datetime import UTC, date, datetime

from sqlalchemy import case, exists, func, select

from backend.models.account_strategy import AccountStrategySnapshot
from backend.models.collaboration import AuditLog
from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.deal import Deal, DealStageHistory, PipelineStage
from backend.models.intelligence_import import IntelligenceImport, PartnerPipeline
from backend.models.rep_intelligence import RepIntelligenceImport, RepIntelligenceRow
from backend.models.rvtools_import import RvToolsImport
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer
from backend.services.account_qbr import qbr_state_for

KINDS = ("note", "activity", "task", "contact", "pipeline_import", "rep_import",
         "rvtools_import", "strategy_snapshot", "qbr", "membership", "deal")
KIND_ORDER = {kind: index for index, kind in enumerate(KINDS)}
DEFAULT_LIMIT = 30
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 1024
DETAIL_MAX = 160
CAPS = {"note": 50, "activity": 50, "task": 30, "contact": 20, "pipeline_import": 10,
        "rep_import": 10, "rvtools_import": 10, "strategy_snapshot": 10, "membership": 10, "deal": 50}
ACTIVITY_LABELS = {"call": "Call", "meeting": "Meeting", "email": "Email", "demo": "Demo", "qbr": "QBR"}
MEMBERSHIP_ACTIONS = ("membership.add", "membership.remove", "ownership.transfer")
TASK_STATUSES = ("open", "in_progress", "completed")
NOT_RECORDED = "not recorded"


class InvalidCursor(ValueError):
    """Raised for any cursor that does not decode to a valid position."""


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def _window(text):
    if text is None:
        return None
    collapsed = " ".join(str(text).split())
    if not collapsed:
        return None
    return collapsed if len(collapsed) <= DETAIL_MAX else collapsed[:DETAIL_MAX - 1] + "…"


def _item(kind, row_id, title, *, when=None, detail=None, actor=None, imported=False,
          source_ref=True):
    """Build an item; ``when`` is a date (date_only) or datetime (instant) or None."""
    if isinstance(when, datetime):
        instant, timestamp, date_only = _utc(when), _utc(when).isoformat(), False
    elif isinstance(when, date):
        instant = datetime(when.year, when.month, when.day, tzinfo=UTC)
        timestamp, date_only = when.isoformat(), True
    else:
        instant, timestamp, date_only = None, None, False
    item = {"kind": kind, "id": row_id, "title": title, "detail": _window(detail), "actor": actor,
            "timestamp": timestamp, "date_only": date_only, "imported": imported,
            "source_ref": f"module={kind}&id={row_id}" if source_ref and row_id is not None else None}
    return item, instant


def _sort_key(instant, kind, row_id):
    return (instant is None, -instant.timestamp() if instant else 0.0,
            KIND_ORDER[kind], row_id is None, -(row_id or 0))


# ── sources (one bounded query each) ─────────────────────────────────────


def _notes(db, cid):
    rows = (db.query(SalesNote).filter(SalesNote.customer_id == cid, SalesNote.note_date.is_not(None))
            .order_by(SalesNote.note_date.desc(), SalesNote.id.desc()).limit(CAPS["note"]).all())
    return [_item("note", r.id, r.title, when=r.note_date, detail=r.content, actor=r.author) for r in rows]


def _activities(db, cid):
    rows = (db.query(CustomerActivity)
            .filter(CustomerActivity.customer_id == cid,
                    (CustomerActivity.occurred_at.is_not(None)) | (CustomerActivity.occurred_date.is_not(None)))
            .order_by(func.coalesce(CustomerActivity.occurred_at, CustomerActivity.occurred_date).desc(),
                      CustomerActivity.id.desc())
            .limit(CAPS["activity"]).all())
    return [_item("activity", r.id, ACTIVITY_LABELS.get(r.type, r.type),
                  when=r.occurred_at or r.occurred_date, detail=r.outcome, actor=r.actor) for r in rows]


def _tasks(db, cid):
    rows = (db.query(CustomerTask)
            .filter(CustomerTask.customer_id == cid, CustomerTask.status.in_(TASK_STATUSES))
            .order_by(func.coalesce(CustomerTask.completed_at, CustomerTask.updated_at).desc(),
                      CustomerTask.id.desc())
            .limit(CAPS["task"]).all())
    items = []
    for r in rows:
        if r.status == "completed":
            items.append(_item("task", r.id, f"Task completed: {r.title}",
                               when=r.completed_at or r.updated_at, actor=r.completed_by))
        else:
            items.append(_item("task", r.id, f"Task {r.status}: {r.title}",
                               when=r.updated_at, actor=r.assignee))
    return items


def _contacts(db, cid):
    event_time = case((CustomerContact.archived.is_(True), CustomerContact.updated_at),
                      else_=CustomerContact.created_at)
    rows = (db.query(CustomerContact).filter(CustomerContact.customer_id == cid)
            .order_by(event_time.desc(), CustomerContact.id.desc())
            .limit(CAPS["contact"]).all())
    return [_item("contact", r.id, f"Contact archived: {r.display_name}", when=r.updated_at)
            if r.archived else
            _item("contact", r.id, f"Contact added: {r.display_name}", when=r.created_at, detail=r.title)
            for r in rows]


def _pipeline_imports(db, cid):
    linked = exists().where(PartnerPipeline.import_id == IntelligenceImport.id,
                            PartnerPipeline.customer_id == cid)
    rows = (db.query(IntelligenceImport.id, IntelligenceImport.imported_by, IntelligenceImport.created_at)
            .filter(linked).order_by(IntelligenceImport.created_at.desc(), IntelligenceImport.id.desc())
            .limit(CAPS["pipeline_import"]).all())
    return [_item("pipeline_import", rid, f"Pipeline import #{rid}", when=created,
                  detail=f"imported {by}", imported=True) for rid, by, created in rows]


def _rep_imports(db, cid):
    linked = exists().where(RepIntelligenceRow.import_id == RepIntelligenceImport.id,
                            RepIntelligenceRow.customer_id == cid)
    rows = (db.query(RepIntelligenceImport.id, RepIntelligenceImport.imported_by,
                     RepIntelligenceImport.created_at)
            .filter(linked).order_by(RepIntelligenceImport.created_at.desc(), RepIntelligenceImport.id.desc())
            .limit(CAPS["rep_import"]).all())
    return [_item("rep_import", rid, f"Rep intelligence import #{rid}", when=created,
                  detail=f"imported {by}", imported=True) for rid, by, created in rows]


def _rvtools_imports(db, cid):
    # The model has no "environment source" in ``summary`` (numeric totals
    # only); the vCenter name is the recorded environment identity.
    rows = (db.query(RvToolsImport.id, RvToolsImport.vcenter, RvToolsImport.created_at)
            .filter(RvToolsImport.customer_id == cid)
            .order_by(RvToolsImport.created_at.desc(), RvToolsImport.id.desc())
            .limit(CAPS["rvtools_import"]).all())
    return [_item("rvtools_import", rid, f"RVTools import #{rid}", when=created,
                  detail=f"vCenter {vcenter}" if vcenter else None, imported=True)
            for rid, vcenter, created in rows]


def _snapshots(db, cid):
    rows = (db.query(AccountStrategySnapshot.id, AccountStrategySnapshot.plan_number,
                     AccountStrategySnapshot.note, AccountStrategySnapshot.published_at)
            .filter(AccountStrategySnapshot.customer_id == cid)
            .order_by(AccountStrategySnapshot.published_at.desc(), AccountStrategySnapshot.id.desc())
            .limit(CAPS["strategy_snapshot"]).all())
    return [_item("strategy_snapshot", rid, f"Strategy plan #{number} published", when=published,
                  detail=note) for rid, number, note, published in rows]


def _details(raw):
    try:
        parsed = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else NOT_RECORDED


def membership_title(action, raw_details):
    """Whitelisted rendering — only ``role`` / ``new_username`` are ever read.

    Transfer records created before the username was recorded retain an
    explicit "not recorded" value; never infer it from other audit fields.
    """
    details = _details(raw_details)
    if action == "membership.add":
        return f"Membership added: {_text(details.get('role'))}"
    if action == "membership.remove":
        return f"Membership removed: {_text(details.get('role'))}"
    return f"Ownership transferred to {_text(details.get('new_username'))}"


def _memberships(db, cid):
    # Older installations could reuse a deleted customer's numeric ID. Retain
    # the audit evidence, but never show a former account's events in its
    # replacement's timeline. IDs form a deletion barrier even with equal or
    # skewed timestamps; unknown account creation dates fail closed.
    deleted = AuditLog.__table__.alias("prior_account_deletions")
    last_deletion = select(func.max(deleted.c.id)).where(
        deleted.c.customer_id == cid, deleted.c.action == "customer.delete").scalar_subquery()
    rows = (db.query(AuditLog.id, AuditLog.action, AuditLog.details, AuditLog.username, AuditLog.created_at)
            .join(Customer, Customer.id == AuditLog.customer_id)
            .filter(AuditLog.customer_id == cid, AuditLog.action.in_(MEMBERSHIP_ACTIONS),
                    AuditLog.id > func.coalesce(last_deletion, 0),
                    AuditLog.created_at >= Customer.created_at)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(CAPS["membership"]).all())
    return [_item("membership", rid, membership_title(action, details), when=created, actor=username,
                  source_ref=False) for rid, action, details, username, created in rows]


def _qbr_item(qbr):
    if qbr["state"] == "overdue":
        detail = f"Last QBR {qbr['last_qbr_date']}; {abs(qbr['days_until'])} days overdue"
        title = "QBR overdue"
    elif qbr["state"] == "due_soon":
        detail = f"Due {qbr['next_qbr_due']} (in {qbr['days_until']} days)"
        title = "QBR due soon"
    else:
        return []
    return [_item("qbr", None, title, when=date.fromisoformat(qbr["next_qbr_due"]), detail=detail,
                  source_ref=False)]


def _deals(db, cid):
    rows = db.query(DealStageHistory, Deal.name, PipelineStage.label).join(Deal, Deal.id == DealStageHistory.deal_id).join(
        PipelineStage, PipelineStage.id == DealStageHistory.to_stage_id).filter(Deal.customer_id == cid).order_by(
        DealStageHistory.at.desc(), DealStageHistory.id.desc()).limit(CAPS["deal"]).all()
    items = []
    for event, name, stage in rows:
        item, instant = _item("deal", event.id, f"Deal: {name} → {stage}", when=event.at, actor=event.actor, detail=event.note)
        item["source_ref"] = f"module=deal&id={event.deal_id}"
        items.append((item, instant))
    return items


SOURCES = (_deals, _notes, _activities, _tasks, _contacts, _pipeline_imports, _rep_imports,
           _rvtools_imports, _snapshots, _memberships)


# ── cursor ───────────────────────────────────────────────────────────────


def encode_cursor(item) -> str:
    payload = json.dumps({"ts": item["timestamp"], "kind": item["kind"], "id": item["id"]},
                         separators=(",", ":"), sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str):
    """Cursor → sort key; validate bounded input before using any fields."""
    if not isinstance(cursor, str) or not 1 <= len(cursor) <= MAX_CURSOR_LENGTH:
        raise InvalidCursor
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, binascii.Error, RecursionError) as exc:
        raise InvalidCursor from exc
    if not isinstance(payload, dict) or set(payload) != {"ts", "kind", "id"}:
        raise InvalidCursor
    ts, kind, row_id = payload["ts"], payload["kind"], payload["id"]
    if not isinstance(kind, str) or kind not in KIND_ORDER:
        raise InvalidCursor
    if row_id is not None and (isinstance(row_id, bool) or not isinstance(row_id, int)
                               or not 1 <= row_id <= 2**63 - 1):
        raise InvalidCursor
    if ts is not None and (not isinstance(ts, str) or not 1 <= len(ts) <= 64):
        raise InvalidCursor
    try:
        instant = None if ts is None else (
            _utc(datetime.fromisoformat(ts)) if "T" in ts else
            datetime.combine(date.fromisoformat(ts), datetime.min.time(), UTC))
        return _sort_key(instant, kind, row_id)
    except (ValueError, OverflowError, OSError) as exc:
        # Valid ISO syntax can still overflow when an extreme offset is
        # normalized to UTC, or exceed the platform's timestamp range.
        raise InvalidCursor from exc


# ── assembly ─────────────────────────────────────────────────────────────


def build_timeline(db, customer_id, limit=DEFAULT_LIMIT, cursor=None, now=None) -> dict:
    """Assemble one page. Caller has already authorized the account read.

    ``cursor`` is the raw opaque string (raises ``InvalidCursor``);
    ``now`` drives the QBR state (no wall-clock reads when injected).
    """
    after = decode_cursor(cursor) if cursor is not None else None
    qbr = qbr_state_for(db, customer_id, now=now)
    entries = [entry for source in SOURCES for entry in source(db, customer_id)]
    entries.extend(_qbr_item(qbr))
    keyed = sorted(((_sort_key(instant, item["kind"], item["id"]), item) for item, instant in entries),
                   key=lambda pair: pair[0])
    if after is not None:
        keyed = [pair for pair in keyed if pair[0] > after]
    page = [item for _, item in keyed[:limit]]
    more = len(keyed) > limit
    return {"customer_id": customer_id, "qbr": qbr, "items": page,
            "next_cursor": encode_cursor(page[-1]) if more and page else None, "more": more}
