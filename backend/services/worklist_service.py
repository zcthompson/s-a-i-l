"""Bounded personal worklist, evaluated against the current read policy."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Numeric, String, and_, cast, func, tuple_

from backend.models.customer_engagement import CustomerActivity
from backend.models.deal import Deal, PipelineStage
from backend.models.intelligence_import import PartnerPipeline
from backend.models.use_case import Customer, User
from backend.services import (
    account_qbr,
    customer_engagement_service,
    sales_access,
)
from backend.services.sql_text import strip_expression

SECTION_LIMIT = 20


def _renewal_candidates(db, user, today):
    """Select the earliest dated opportunity per readable account in SQL."""
    scoped = (db.query(PartnerPipeline.customer_id.label("cid"),
                       func.max(PartnerPipeline.import_id).label("batch"))
              .join(User, User.username == user["username"])
              .filter(User.is_active == 1,
                      sales_access.account_read_predicate(User, PartnerPipeline.customer_id))
              .group_by(PartnerPipeline.customer_id).subquery())
    number = strip_expression(db, PartnerPipeline.opportunity_number)
    grouped = (db.query(PartnerPipeline.customer_id.label("cid"),
                        PartnerPipeline.import_id.label("batch"), number.label("number"),
                        func.min(PartnerPipeline.current_contract_end_date).label("end_date"))
               .join(scoped, and_(scoped.c.cid == PartnerPipeline.customer_id,
                                  scoped.c.batch == PartnerPipeline.import_id))
               .filter(number != "")
               .group_by(PartnerPipeline.customer_id, PartnerPipeline.import_id, number).subquery())
    ranked = (db.query(grouped, func.row_number().over(
        partition_by=grouped.c.cid,
        order_by=(grouped.c.end_date, grouped.c.number)).label("rank"))
        .filter(grouped.c.end_date.is_not(None),
                grouped.c.end_date <= today + timedelta(days=180)).subquery())
    return (db.query(ranked.c.cid, ranked.c.batch, ranked.c.number, Customer.name, ranked.c.end_date)
            .join(Customer, Customer.id == ranked.c.cid).filter(ranked.c.rank == 1)
            .order_by(ranked.c.end_date, Customer.name, Customer.id)
            .limit(SECTION_LIMIT + 1).all())


class _DecimalTotal:
    """Match pipeline_read_model._amount without returning source rows to Python."""

    def __init__(self):
        self.total = Decimal(0)
        self.count = 0

    def step(self, value):
        if value is not None:
            self.total += Decimal(str(value))
            self.count += 1

    def finalize(self):
        return str(self.total.quantize(Decimal("0.01"))) if self.count else None


def _renewal_totals(db, candidates):
    if not candidates:
        return {}
    postgres = db.get_bind().dialect.name == "postgresql"
    if not postgres:
        connection = db.connection().connection.driver_connection
        connection.create_aggregate("sail_decimal_total", 1, _DecimalTotal)
    number = strip_expression(db, PartnerPipeline.opportunity_number)
    name = PartnerPipeline.opportunity_name
    # The established read model takes the first nonblank name in source-row
    # order, with null source rows last and the ID as the final tie-breaker.
    first_name = func.first_value(name).over(
        partition_by=(PartnerPipeline.customer_id, PartnerPipeline.import_id, number),
        order_by=(func.length(strip_expression(db, name)) == 0,
                  PartnerPipeline.source_row.is_(None), PartnerPipeline.source_row,
                  PartnerPipeline.id))
    keys = [(cid, batch, opportunity) for cid, batch, opportunity, _, _ in candidates]
    rows = (db.query(PartnerPipeline.customer_id.label("cid"), number.label("number"),
                     first_name.label("name"), PartnerPipeline.est_acv_usd.label("acv"),
                     PartnerPipeline.est_tcv_usd.label("tcv"))
            .filter(tuple_(PartnerPipeline.customer_id, PartnerPipeline.import_id, number).in_(keys))
            .subquery())
    def total(column):
        return func.sum(cast(cast(column, String), Numeric)) if postgres else func.sail_decimal_total(column)
    totals = (db.query(rows.c.cid, func.max(rows.c.name), total(rows.c.acv), total(rows.c.tcv))
              .group_by(rows.c.cid, rows.c.number).all())
    return {cid: (name if name and name.strip() else None,
                  float(Decimal(str(acv)).quantize(Decimal("0.01"))) if acv is not None else None,
                  float(Decimal(str(tcv)).quantize(Decimal("0.01"))) if tcv is not None else None)
            for cid, name, acv, tcv in totals}


def worklist_for(db, user, now=None):
    now = account_qbr._utc(now or datetime.now(UTC))
    today = now.date()
    if db.get_bind().dialect.name == "sqlite":
        db.connection().connection.driver_connection.create_function(
            "sail_strip", 1, lambda value: (value or "").strip(), deterministic=True)
    tasks = customer_engagement_service.my_tasks(db, user, limit=SECTION_LIMIT + 1, now=now)
    candidates = _renewal_candidates(db, user, today)
    totals = _renewal_totals(db, candidates[:SECTION_LIMIT])
    cadence = account_qbr.cadence_days(db)
    day_expr = func.coalesce(CustomerActivity.occurred_date, func.date(CustomerActivity.occurred_at))
    latest = (db.query(CustomerActivity.customer_id.label("customer_id"),
                       func.max(day_expr).label("last_day"))
              .join(User, User.username == user["username"])
              .filter(User.is_active == 1,
                      sales_access.account_read_predicate(User, CustomerActivity.customer_id),
                      CustomerActivity.type == "qbr")
              .group_by(CustomerActivity.customer_id).subquery())
    cutoff = today + timedelta(days=account_qbr.QBR_DUE_SOON_DAYS - cadence)
    if db.get_bind().dialect.name == "sqlite":
        cutoff = cutoff.isoformat()
    latest_rows = (db.query(latest.c.customer_id, latest.c.last_day, Customer.name)
                   .join(Customer, Customer.id == latest.c.customer_id)
                   .filter(latest.c.last_day <= cutoff)
                   .order_by(latest.c.last_day, Customer.name, Customer.id)
                   .limit(SECTION_LIMIT + 1).all())
    qbr = []
    for cid, day, name in latest_rows:
        day = date.fromisoformat(day) if isinstance(day, str) else day
        state = account_qbr.qbr_state_from(day, cadence, today)
        if state["state"] in ("due_soon", "overdue"):
            qbr.append({"customer_id": cid, "customer_name": name, **{key: state[key] for key in (
                "state", "next_qbr_due", "days_until")}})
    renewals = []
    for cid, _, _, name, end_date in candidates[:SECTION_LIMIT]:
        days = (end_date - today).days
        bucket = ("overdue" if days < 0 else "within_30" if days <= 30 else
                  "within_60" if days <= 60 else "within_90" if days <= 90 else "within_180")
        opportunity, acv, tcv = totals[cid]
        renewals.append({"customer_id": cid, "customer_name": name,
                         "opportunity_name": opportunity, "end_date": end_date.isoformat(),
                         "bucket": bucket, "acv_usd": acv, "tcv_usd": tcv})
    closing = db.query(Deal, Customer.name).join(Customer, Customer.id == Deal.customer_id).join(
        PipelineStage, PipelineStage.id == Deal.stage_id).join(User, User.id == Deal.owner_user_id).filter(
        User.username == user["username"], User.is_active == 1, PipelineStage.stage_class == "open",
        Deal.close_date.is_not(None), Deal.close_date <= today + timedelta(days=90),
        sales_access.account_read_predicate(User, Deal.customer_id)).order_by(Deal.close_date, Deal.id).limit(SECTION_LIMIT + 1).all()
    closing_deals = [{"id": deal.id, "customer_id": deal.customer_id, "customer_name": name, "name": deal.name,
                      "close_date": deal.close_date.isoformat(), "amount": None if deal.amount_minor is None else
                      {"minor": deal.amount_minor, "currency": deal.currency}, "amount_basis": deal.amount_basis}
                     for deal, name in closing[:SECTION_LIMIT]]
    return {"generated_at": now.isoformat(), "tasks": tasks[:SECTION_LIMIT], "closing_deals": closing_deals,
            "renewals": renewals, "qbr": qbr[:SECTION_LIMIT],
            "truncated": {"closing_deals": len(closing) > SECTION_LIMIT, "tasks": len(tasks) > SECTION_LIMIT,
                          "renewals": len(candidates) > SECTION_LIMIT,
                          "qbr": len(qbr) > SECTION_LIMIT}}
