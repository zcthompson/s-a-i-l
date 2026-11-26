"""Deals and pipeline stages: validation, compare-and-swap writes, stage history.

Authorization happens in the routes (account read for reads; CAP_OPPORTUNITIES
with the "opportunities" section for writes). Every write is one transaction.
"""

import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError

from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.customer_technology import CustomerTechnology
from backend.models.deal import (
    AMOUNT_BASES,
    CONTACT_ROLES,
    DEAL_TYPES,
    STAGE_CLASSES,
    Deal,
    DealStageHistory,
    PipelineStage,
    deal_activities,
    deal_contacts,
    deal_notes,
    deal_tasks,
    deal_technologies,
    deal_vendor_evidence,
)
from backend.models.intelligence_import import PartnerPipeline
from backend.models.sales_note import SalesNote
from backend.models.use_case import User
from backend.services import record_cleanup
from backend.services.sql_text import strip_expression

CONFLICT = "Deal changed since you loaded it; reload and retry"
# (payload field, link table, column, model that must belong to the account, label)
LINKS = (
    ("task_ids", deal_tasks, "task_id", CustomerTask, "task"),
    ("activity_ids", deal_activities, "activity_id", CustomerActivity, "activity"),
    ("note_ids", deal_notes, "note_id", SalesNote, "note"),
    ("technology_ids", deal_technologies, "technology_id", CustomerTechnology, "technology"),
)
EDITABLE = {"name", "owner_user_id", "stage_id", "close_date", "amount_minor", "currency", "amount_basis",
            "probability", "deal_type", "next_step", "next_step_date", "closed_reason"}


def _now():
    return datetime.now(UTC).replace(tzinfo=None)


# ── stages ──────────────────────────────────────────────────────────────────

def stage_wire(stage):
    return {"id": stage.id, "key": stage.key, "label": stage.label, "stage_class": stage.stage_class,
            "position": stage.position, "active": bool(stage.active),
            "default_probability": stage.default_probability}


def list_stages(db, include_inactive=False):
    query = db.query(PipelineStage)
    if not include_inactive:
        query = query.filter(PipelineStage.active.is_(True))
    return [stage_wire(s) for s in query.order_by(PipelineStage.position, PipelineStage.id)]


def _stage(db, stage_id, *, active=True):
    stage = db.get(PipelineStage, stage_id) if stage_id is not None else None
    if stage is None or (active and not stage.active):
        raise HTTPException(422, "Unknown or retired pipeline stage")
    return stage


def create_stage(db, payload):
    if payload["stage_class"] not in STAGE_CLASSES:
        raise HTTPException(422, "Unknown stage class")
    if db.query(PipelineStage.id).filter_by(key=payload["key"]).first():
        raise HTTPException(409, "A stage with this key already exists")
    stage = PipelineStage(**payload, active=True)
    db.add(stage)
    db.commit()
    return stage_wire(stage)


def update_stage(db, stage_id, payload, actor):
    stage = db.get(PipelineStage, stage_id)
    if stage is None:
        raise HTTPException(404, "Stage not found")
    remap = payload.pop("remap_to_stage_id", None)
    try:
        if payload.get("active") is False and stage.active:
            in_stage = db.query(Deal).filter(Deal.stage_id == stage.id).all()
            if in_stage:
                if remap is None:
                    raise HTTPException(409, f"{len(in_stage)} deal(s) use this stage; choose a stage to move them to")
                target = _stage(db, remap)
                if target.id == stage.id or target.stage_class != stage.stage_class:
                    raise HTTPException(422, "Move deals to a different active stage of the same class")
                for deal in in_stage:
                    _record_history(db, deal, stage.id, target.id, actor, note=f"stage {stage.key} retired")
                    deal.stage_id = target.id
                    deal.version += 1
                    deal.updated_at = _now()
        if payload.get("active") is True and not stage.active:
            stage.active = True
        for field in ("label", "position", "default_probability", "active"):
            if field in payload:
                setattr(stage, field, payload[field])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return stage_wire(stage)


# ── deals ───────────────────────────────────────────────────────────────────

def _money(minor, currency):
    return None if minor is None else {"minor": minor, "currency": currency}


def _links_for(db, deal_ids):
    out = {i: {"contacts": [], "task_ids": [], "activity_ids": [], "note_ids": [], "technology_ids": [], "vendor_evidence": []}
           for i in deal_ids}
    if not deal_ids:
        return out
    for deal_id, contact_id, role in db.query(deal_contacts.c.deal_id, deal_contacts.c.contact_id, deal_contacts.c.role)\
            .filter(deal_contacts.c.deal_id.in_(deal_ids)).order_by(deal_contacts.c.contact_id):
        out[deal_id]["contacts"].append({"contact_id": contact_id, "role": role})
    for field, table, key, _model, _label in LINKS:
        for deal_id, value in db.query(table.c.deal_id, table.c[key]).filter(table.c.deal_id.in_(deal_ids))\
                .order_by(table.c[key]):
            out[deal_id][field].append(value)
    for deal_id, import_id, number in db.query(deal_vendor_evidence).filter(deal_vendor_evidence.c.deal_id.in_(deal_ids)):
        out[deal_id]["vendor_evidence"].append({"import_id": import_id, "opportunity_number": number})
    return out


def _wire(deal, stage, links):
    return {
        "id": deal.id, "customer_id": deal.customer_id, "name": deal.name,
        "owner_user_id": deal.owner_user_id, "owner_name": deal.owner_name,
        "stage": stage_wire(stage), "stage_id": stage.id,
        # The stage default is only ever a suggestion.
        "probability": deal.probability, "suggested_probability": stage.default_probability,
        "close_date": deal.close_date.isoformat() if deal.close_date else None,
        "amount": _money(deal.amount_minor, deal.currency), "amount_minor": deal.amount_minor,
        "currency": deal.currency, "amount_basis": deal.amount_basis, "deal_type": deal.deal_type,
        "next_step": deal.next_step,
        "next_step_date": deal.next_step_date.isoformat() if deal.next_step_date else None,
        "closed_reason": deal.closed_reason,
        "closed_at": deal.closed_at.isoformat() if deal.closed_at else None,
        "source_type": deal.source_type, "source_id": deal.source_id, "source_key": deal.source_key,
        "created_by": deal.created_by,
        "created_at": deal.created_at.isoformat() if deal.created_at else None,
        "updated_at": deal.updated_at.isoformat() if deal.updated_at else None,
        "version": deal.version, **links,
    }


def list_deals(db, customer_id, *, deal_id=None, include_closed=True):
    query = db.query(Deal, PipelineStage).join(PipelineStage, PipelineStage.id == Deal.stage_id)\
        .filter(Deal.customer_id == customer_id)
    if deal_id is not None:
        query = query.filter(Deal.id == deal_id)
    if not include_closed:
        query = query.filter(PipelineStage.stage_class == "open")
    rows = query.order_by(PipelineStage.stage_class != "open", Deal.close_date.is_(None), Deal.close_date,
                          Deal.id).all()
    links = _links_for(db, [d.id for d, _ in rows])
    return [_wire(d, s, links[d.id]) for d, s in rows]


def history(db, deal_id):
    stages = {s.id: s for s in db.query(PipelineStage)}
    rows = db.query(DealStageHistory).filter_by(deal_id=deal_id).order_by(DealStageHistory.at, DealStageHistory.id)
    return [{
        "from_stage": stages[r.from_stage_id].label if r.from_stage_id in stages else None,
        "to_stage": stages[r.to_stage_id].label if r.to_stage_id in stages else None,
        "actor": r.actor, "at": r.at.isoformat(), "amount": _money(r.amount_minor, r.currency),
        "amount_basis": r.amount_basis, "close_date": r.close_date.isoformat() if r.close_date else None,
        "note": r.note,
    } for r in rows]


def _record_history(db, deal, from_stage_id, to_stage_id, actor, note=None):
    db.add(DealStageHistory(deal_id=deal.id, from_stage_id=from_stage_id, to_stage_id=to_stage_id, actor=actor,
                            at=_now(), amount_minor=deal.amount_minor, currency=deal.currency,
                            amount_basis=deal.amount_basis, close_date=deal.close_date, note=note))


def _vendor_match(db, number):
    # Match the read model's whitespace-normalized opportunity identity.
    if db.get_bind().dialect.name == "postgresql":
        return strip_expression(db, PartnerPipeline.opportunity_number) == number
    db.connection().connection.driver_connection.create_function(
        "sail_strip", 1, lambda value: (value or "").strip(), deterministic=True)
    return func.sail_strip(PartnerPipeline.opportunity_number) == number


def _validate(db, customer_id, payload, current=None):
    data = {k: v for k, v in payload.items() if k in EDITABLE}
    if current is None or "name" in data:
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise HTTPException(422, "name is required")
        data["name"] = data["name"].strip()
    if "currency" in data:
        if data["currency"] is None or not re.fullmatch(r"[A-Za-z]{3}", data["currency"]):
            raise HTTPException(422, "currency must be a 3-letter ISO code")
        data["currency"] = data["currency"].upper()
    if data.get("amount_basis") is not None and data["amount_basis"] not in AMOUNT_BASES:
        raise HTTPException(422, "Unknown amount basis")
    amount = data.get("amount_minor", getattr(current, "amount_minor", None))
    basis = data.get("amount_basis", getattr(current, "amount_basis", None))
    if amount is not None and basis is None:
        raise HTTPException(422, "An amount needs a basis (one_time, acv, tcv or mrr)")
    if data.get("deal_type") is not None and data["deal_type"] not in DEAL_TYPES:
        raise HTTPException(422, "Unknown deal type")
    if "owner_user_id" in data:
        if data["owner_user_id"] is None:
            data["owner_name"] = None
        else:
            owner = db.query(User).filter(User.id == data["owner_user_id"], User.is_active == 1).first()
            if owner is None:
                raise HTTPException(422, "Unknown or inactive owner")
            data["owner_name"] = owner.display_name or owner.username
    contacts = payload.get("contacts")
    links = []
    if contacts is not None:
        ids = sorted({c["contact_id"] for c in contacts})
        if len(ids) != len(contacts):
            raise HTTPException(422, "A contact may appear only once on a deal")
        for c in contacts:
            if c.get("role") is not None and c["role"] not in CONTACT_ROLES:
                raise HTTPException(422, "Unknown contact role")
        found = {r[0] for r in db.query(CustomerContact.id).filter(
            CustomerContact.id.in_(ids), CustomerContact.customer_id == customer_id)} if ids else set()
        for contact_id in ids:
            if contact_id not in found:
                raise HTTPException(422, f"Related contact {contact_id} does not belong to this customer")
        links.append((deal_contacts, [{"contact_id": c["contact_id"], "role": c.get("role")} for c in contacts]))
    for field, table, key, model, label in LINKS:
        if payload.get(field) is None:
            continue
        ids = sorted(set(payload[field]))
        found = {r[0] for r in db.query(model.id).filter(model.id.in_(ids), model.customer_id == customer_id)} if ids else set()
        for related in ids:
            if related not in found:
                raise HTTPException(422, f"Related {label} {related} does not belong to this customer")
        links.append((table, [{key: value} for value in ids]))
    if payload.get("vendor_evidence") is not None:
        evidence = []
        retained = set()
        if current is not None:
            retained = {(r.import_id, r.opportunity_number) for r in db.query(deal_vendor_evidence).filter_by(deal_id=current.id)}
        for item in payload["vendor_evidence"]:
            number = item["opportunity_number"].strip()
            if not number:
                raise HTTPException(422, "Vendor opportunity number is required")
            identity = (item["import_id"], number)
            if identity not in retained and not db.query(PartnerPipeline.id).filter(
                PartnerPipeline.customer_id == customer_id, PartnerPipeline.import_id == item["import_id"],
                _vendor_match(db, number)).first():
                raise HTTPException(422, "Vendor evidence does not belong to this customer")
            value = {"import_id": item["import_id"], "opportunity_number": number}
            if value not in evidence:
                evidence.append(value)
        links.append((deal_vendor_evidence, evidence))
    return data, links


def _apply_links(db, deal_id, links):
    for table, rows in links:
        db.execute(delete(table).where(table.c.deal_id == deal_id))
        if rows:
            db.execute(table.insert(), [{"deal_id": deal_id, **row} for row in rows])


def _closing(stage, data, current):
    """Closed-stage rules: lost needs a reason; leaving a closed stage reopens."""
    reason = data.get("closed_reason", getattr(current, "closed_reason", None))
    if stage.stage_class == "lost" and not (reason or "").strip():
        raise HTTPException(422, "A lost deal needs a closed reason")
    if stage.stage_class in ("won", "lost"):
        if current is None or current.closed_at is None:
            data["closed_at"] = _now()
    elif current is not None and current.closed_at is not None:
        data.update(closed_at=None, closed_reason=None)


def create_deal(db, customer_id, payload, username, *, source=None):
    if "owner_user_id" not in payload:
        # A new deal is owned by its creator unless an owner is chosen.
        creator = db.query(User.id).filter(User.username == username, User.is_active == 1).first()
        payload = {**payload, "owner_user_id": creator[0] if creator else None}
    data, links = _validate(db, customer_id, payload)
    if data.get("stage_id") is None:
        first_open = db.query(PipelineStage).filter_by(stage_class="open", active=True)\
            .order_by(PipelineStage.position, PipelineStage.id).first()
        if first_open is None:
            raise HTTPException(422, "No active open pipeline stage is configured")
        data["stage_id"] = first_open.id
    stage = _stage(db, data["stage_id"])
    _closing(stage, data, None)
    deal = Deal(customer_id=customer_id, created_by=username, version=1, **data, **(source or {}))
    try:
        db.add(deal)
        db.flush()
        _record_history(db, deal, None, stage.id, username, note="created")
        _apply_links(db, deal.id, links)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return list_deals(db, customer_id, deal_id=deal.id)[0]


def update_deal(db, deal, payload, username):
    expected = payload.get("expected_version")
    if expected != deal.version:
        raise HTTPException(409, CONFLICT)
    data, links = _validate(db, deal.customer_id, payload, deal)
    stage_changed = "stage_id" in data and data["stage_id"] != deal.stage_id
    stage = _stage(db, data["stage_id"]) if stage_changed else db.get(PipelineStage, deal.stage_id)
    if stage_changed or "closed_reason" in data:
        _closing(stage, data, deal)
    deal_id, customer_id, from_stage = deal.id, deal.customer_id, deal.stage_id
    try:
        # Compare-and-swap in the database handles overlapping requests.
        changed = db.execute(update(Deal).where(Deal.id == deal_id, Deal.version == expected)
                             .values(**data, version=expected + 1, updated_at=_now()),
                             execution_options={"synchronize_session": False}).rowcount
        if not changed:
            db.rollback()
            raise HTTPException(409, CONFLICT)
        db.expire(deal)
        if stage_changed:
            _record_history(db, db.get(Deal, deal_id), from_stage, stage.id, username)
        _apply_links(db, deal_id, links)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return list_deals(db, customer_id, deal_id=deal_id)[0]


def delete_deal(db, deal, expected_version):
    if expected_version != deal.version:
        raise HTTPException(409, CONFLICT)
    deal_id = deal.id
    try:
        changed = db.execute(update(Deal).where(Deal.id == deal_id, Deal.version == expected_version)
                             .values(version=expected_version + 1),
                             execution_options={"synchronize_session": False}).rowcount
        if not changed:
            db.rollback()
            raise HTTPException(409, CONFLICT)
        record_cleanup.deals(db, [deal_id])
        db.execute(delete(Deal).where(Deal.id == deal_id))
        db.commit()
    except Exception:
        db.rollback()
        raise


def open_deal_count(db, stage_id):
    return db.query(func.count(Deal.id)).filter(Deal.stage_id == stage_id).scalar()


def promote(db, customer_id, payload, username):
    """Derive promotion details on the server; retry returns the original deal."""
    from backend.services.customer_intelligence import get_account_workspace
    vendor = payload.get("vendor")
    attention_id = payload.get("attention_id")
    if bool(vendor) == bool(attention_id):
        raise HTTPException(422, "Choose one attention card or vendor opportunity")
    if vendor and not vendor["opportunity_number"].strip():
        raise HTTPException(422, "Vendor opportunity number is required")
    source_key = f"vendor:{vendor['opportunity_number'].strip()}" if vendor else f"attention:{attention_id}"
    existing = db.query(Deal).filter_by(customer_id=customer_id, source_key=source_key).first()
    if existing is None and vendor:
        existing = db.query(Deal).join(deal_vendor_evidence, deal_vendor_evidence.c.deal_id == Deal.id).filter(
            Deal.customer_id == customer_id,
            deal_vendor_evidence.c.opportunity_number == vendor['opportunity_number'].strip()).order_by(Deal.id).first()
    if existing:
        return {"created": False, "deal": list_deals(db, customer_id, deal_id=existing.id)[0]}
    data = {}
    if vendor:
        rows = db.query(PartnerPipeline).filter(PartnerPipeline.customer_id == customer_id,
            PartnerPipeline.import_id == vendor["import_id"],
            _vendor_match(db, vendor["opportunity_number"].strip())).order_by(PartnerPipeline.id).all()
        if not rows:
            raise HTTPException(404, "Vendor opportunity not found")
        data = {"name": next((row.opportunity_name.strip() for row in rows if row.opportunity_name and row.opportunity_name.strip()), vendor['opportunity_number'].strip()),
                "vendor_evidence": [vendor]}
    else:
        card = next((card for card in get_account_workspace(db, customer_id)["opportunities"] if card["id"] == attention_id), None)
        if card is None:
            raise HTTPException(404, "Attention card no longer available")
        data = {"name": card["title"], "next_step": card["detail"]}
        evidence = card["evidence"]
        if evidence["source"] == "technology" and evidence.get("source_id"):
            data["technology_ids"] = [evidence["source_id"]]
        elif evidence["source"] == "sales_note" and evidence.get("source_id"):
            data["note_ids"] = [evidence["source_id"]]
        elif evidence["source"] == "partner_pipeline":
            return promote(db, customer_id, {"vendor": {"import_id": evidence["source_id"], "opportunity_number": evidence["source_name"]}}, username)
    try:
        deal = create_deal(db, customer_id, data, username, source={"source_type": "vendor" if vendor else "attention", "source_key": source_key})
        return {"created": True, "deal": deal}
    except IntegrityError:
        db.rollback()
        existing = db.query(Deal).filter_by(customer_id=customer_id, source_key=source_key).first()
        if not existing:
            raise
        return {"created": False, "deal": list_deals(db, customer_id, deal_id=existing.id)[0]}
