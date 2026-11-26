"""E10 — QBR cadence: next-QBR-due derived from the last recorded QBR activity.

Read-only and deterministic: all date math uses the injected ``now`` (the H6
A2 pattern); the wall clock is read only when the caller passes none.
No schedule table — the cadence is a single system_config value.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from backend.models.customer_engagement import CustomerActivity
from backend.services import config_service

QBR_DEFAULT_CADENCE = 90
QBR_MIN_CADENCE = 30
QBR_MAX_CADENCE = 365
QBR_DUE_SOON_DAYS = 14
QBR_BASIS = "activity type qbr + system_config engagement.qbr_cadence_days (default 90)"


def _utc(value):
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC)


def cadence_days(db) -> int:
    """Configured cadence; unparseable or out of 30..365 → the default."""
    raw = config_service.get_engagement_overrides(db).get("qbr_cadence_days")
    if raw is None or isinstance(raw, bool):
        return QBR_DEFAULT_CADENCE
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return QBR_DEFAULT_CADENCE
    return value if QBR_MIN_CADENCE <= value <= QBR_MAX_CADENCE else QBR_DEFAULT_CADENCE


def last_qbr_date(db, customer_id):
    """Latest recorded QBR activity day (occurred_date, else occurred_at's UTC day)."""
    value = db.query(func.max(func.coalesce(CustomerActivity.occurred_date,
                                          func.date(CustomerActivity.occurred_at)))).filter(
        CustomerActivity.customer_id == customer_id, CustomerActivity.type == "qbr").scalar()
    return datetime.fromisoformat(value).date() if isinstance(value, str) else value


def qbr_state_for(db, customer_id, now=None) -> dict:
    today = _utc(now or datetime.now(UTC)).date()
    cadence = cadence_days(db)
    last = last_qbr_date(db, customer_id)
    return qbr_state_from(last, cadence, today)


def qbr_state_from(last_qbr_date, cadence_days, today) -> dict:
    """Pure cadence arithmetic shared by account and batched worklist reads."""
    last, cadence = last_qbr_date, cadence_days
    if last is None:
        return {"last_qbr_date": None, "cadence_days": cadence, "next_qbr_due": None,
                "state": "not_recorded", "days_until": None}
    due = last + timedelta(days=cadence)
    days_until = (due - today).days
    if days_until < 0:
        state = "overdue"
    elif days_until <= QBR_DUE_SOON_DAYS:
        state = "due_soon"
    else:
        state = "current"
    return {"last_qbr_date": last.isoformat(), "cadence_days": cadence,
            "next_qbr_due": due.isoformat(), "state": state, "days_until": days_until}
