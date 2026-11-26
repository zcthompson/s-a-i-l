"""Engagement comes exclusively from recorded, dated interaction evidence."""

from datetime import UTC

from backend.models.customer_engagement import CustomerActivity
from backend.models.sales_note import SalesNote


def last_meaningful_interaction_for(db, customer_id):
    activities = db.query(CustomerActivity.occurred_date, CustomerActivity.occurred_at).filter_by(
        customer_id=customer_id).all()
    notes = db.query(SalesNote.note_date).filter(
        SalesNote.customer_id == customer_id, SalesNote.note_date.is_not(None)).all()
    dates = [day or instant.replace(tzinfo=instant.tzinfo or UTC).astimezone(UTC).date()
             for day, instant in activities if day or instant]
    dates.extend(day for (day,) in notes)
    return max(dates) if dates else None
