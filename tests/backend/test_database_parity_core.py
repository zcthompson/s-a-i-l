"""Explicit dialect parity for JSON, case matching and UTC conversion."""
from datetime import UTC, datetime

from backend.models.customer_engagement import CustomerActivity
from backend.models.use_case import Customer
from backend.services.customer_engagement_service import utc
from sqlalchemy import func


def test_json_unicode_case_and_utc_roundtrip(db_session):
    customer = Customer(name='Synthetic MiXeD Account', tech_profile={'nested': ['α', 2], 'enabled': True})
    db_session.add(customer)
    db_session.commit()
    customer_id = customer.id
    db_session.expire_all()
    result = db_session.query(Customer).filter(func.lower(Customer.name) == 'synthetic mixed account').one()
    assert result.id == customer_id
    assert result.tech_profile == {'nested': ['α', 2], 'enabled': True}
    instant = utc(datetime.fromisoformat('2026-04-05T13:30:00+02:00')).replace(tzinfo=None)
    activity = CustomerActivity(customer_id=customer_id, type='call', occurred_at=instant, actor='admin', created_by='admin')
    db_session.add(activity)
    db_session.commit()
    activity_id = activity.id
    db_session.expire_all()
    loaded = db_session.get(CustomerActivity, activity_id)
    assert utc(loaded.occurred_at) == datetime(2026, 4, 5, 11, 30, tzinfo=UTC)
