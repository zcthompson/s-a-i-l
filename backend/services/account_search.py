"""Bounded, read-only account search using literal escaped LIKE."""
from datetime import date, datetime, timezone

from sqlalchemy import func, or_

from backend.models.account_strategy import AccountStrategy
from backend.models.customer_contact import CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.customer_knowledge import CustomerKnowledge
from backend.models.customer_technology import CustomerTechnology
from backend.models.deal import Deal
from backend.models.sales_note import SalesNote
from backend.models.use_case import UseCase
from backend.services.customer_access import require_account_read_service

MODULES = (
    ("note", SalesNote, ("title", "content"), "note_date"),
    ("contact", CustomerContact, ("display_name", "title"), "created_at"),
    ("activity", CustomerActivity, ("outcome", "type"), None),
    ("task", CustomerTask, ("title", "detail"), "updated_at"),
    ("technology", CustomerTechnology, ("name", "vendor", "version_edition"), "date_observed"),
    ("strategy", AccountStrategy, ("objectives", "desired_outcomes", "risks", "plays", "discovery_gaps"), "updated_at"),
    ("knowledge", CustomerKnowledge, ("file_name", "extracted_text"), "uploaded_at"),
    ("deal", Deal, ("name", "next_step"), "updated_at"),
    ("use_case", UseCase, ("title", "description"), "updated_at"),
)
LABELS = {"objectives": "Objectives", "desired_outcomes": "Desired outcomes", "risks": "Risks",
          "plays": "Plays", "discovery_gaps": "Discovery gaps"}


def _snippet(text, query):
    if len(text) <= 160:
        return text
    index = text.lower().find(query.lower())
    start = min(max(0, index - (160 - len(query)) // 2), len(text) - 160)
    return text[start:start + 160]


def _instant(value):
    if value is None:
        return 0
    if not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()


def search_account(db, user, customer_id, q, include_archived):
    """Authorize direct callers before searching account content."""
    require_account_read_service(db, user, customer_id)
    q = q.strip()
    term = q.replace("!", "!!").replace("%", "!%").replace("_", "!_")
    results, counts, truncated = [], {}, False
    for module, model, fields, timestamp_field in MODULES:
        # Select columns only: no relationship loading or knowledge binary payloads.
        names = list(dict.fromkeys(("id", *fields, *([timestamp_field] if timestamp_field else
                                      ["occurred_at", "occurred_date"]),
                                   *(["archived"] if module == "contact" else []))))
        timestamp = (func.coalesce(model.occurred_at, model.occurred_date) if module == "activity"
                     else getattr(model, timestamp_field))
        query = db.query(*(getattr(model, name) for name in names)).filter(
            model.customer_id == customer_id,
            or_(*(getattr(model, field).ilike(f"%{term}%", escape="!") for field in fields)))
        if module == "contact" and not include_archived:
            query = query.filter(model.archived.is_(False))
        rows = query.order_by(timestamp.is_(None), timestamp.desc(), model.id.desc()).limit(11).all()
        truncated |= len(rows) > 10
        counts[module] = min(len(rows), 10)
        for record in rows[:10]:
            row = record._mapping
            matched = next(field for field in fields if q.lower() in (row[field] or "").lower())
            value = row[timestamp_field] if timestamp_field else row["occurred_at"] or row["occurred_date"]
            title = row[fields[0]]
            if module == "activity":
                title = "QBR" if row["type"] == "qbr" else row["type"].capitalize()
            elif module == "strategy":
                title = f"Account strategy — {LABELS[matched]}"
            elif module == "contact" and row["archived"]:
                title += " (archived)"
            results.append(dict(module=module, id=row["id"], title=title,
                                snippet=_snippet(row[matched], q),
                                timestamp=value.isoformat() if value else None,
                                date_only=isinstance(value, date) and not isinstance(value, datetime)))
    order = {module: i for i, (module, *_) in enumerate(MODULES)}
    results.sort(key=lambda item: (item["timestamp"] is None,
                 -_instant(datetime.fromisoformat(item["timestamp"])) if item["timestamp"] else 0,
                 order[item["module"]], -item["id"]))
    return dict(customer_id=customer_id, query=q, counts=counts, results=results, truncated=truncated)
