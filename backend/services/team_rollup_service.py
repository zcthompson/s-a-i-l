"""Manager team summaries over currently readable, report-owned accounts."""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import aliased

from backend.models.customer_contact import ContactBuyingRole, CustomerContact
from backend.models.customer_engagement import CustomerActivity, CustomerTask
from backend.models.deal import Deal, PipelineStage
from backend.models.sales_access import SalesReporting
from backend.models.sales_note import SalesNote
from backend.models.use_case import Customer, CustomerUser, User
from backend.services import pipeline_read_model, sales_access


def _amounts(ids, summaries, key):
    amounts = [summaries[cid]["amounts"][key] for cid in ids]
    totals = [Decimal(str(a["total"])) for a in amounts if a["total"] is not None]
    excluded = sum(a["lines_excluded"] for a in amounts)
    no_data = sum(a["coverage"] == "no_data" for a in amounts)
    included = sum(a["lines_included"] for a in amounts)
    coverage = ("no_data" if not ids or no_data == len(ids) else "all_unknown" if not totals else
                "partial" if excluded or no_data else "recorded_zero" if sum(totals) == 0 else "quantified")
    return {"total": float(sum(totals)) if totals else None, "coverage": coverage,
            "lines_included": included, "lines_excluded": excluded, "accounts_no_data": no_data}


def team_rollup_for(db, user, now=None):
    if sales_access.effective_role(user) != "sales_manager":
        raise HTTPException(403, "Manager role required")
    manager = db.query(User).filter_by(username=user["username"], is_active=1).first()
    if not manager or sales_access.effective_role({"is_admin": manager.is_admin, "role": manager.role,
                                                   "sales_role": manager.sales_role}) != "sales_manager":
        raise HTTPException(403, "Manager role required")
    now = (now or datetime.now(UTC))
    now = now.replace(tzinfo=now.tzinfo or UTC).astimezone(UTC)
    reports = select(SalesReporting.rep_user_id.label("uid")).where(
        SalesReporting.manager_user_id == manager.id).cte(recursive=True)
    reports = reports.union(select(SalesReporting.rep_user_id).join(
        reports, SalesReporting.manager_user_id == reports.c.uid))
    reps = (db.query(User.id, User.username, User.display_name).join(reports, User.id == reports.c.uid)
            .filter(User.id != manager.id, User.is_active == 1).order_by(User.username, User.id).all())
    rep_ids = [r.id for r in reps]
    owner = aliased(CustomerUser)
    viewer = aliased(User)
    associations = (db.query(owner.user_id, Customer.id).join(Customer, Customer.id == owner.customer_id)
                    .join(viewer, viewer.id == manager.id)
                    .filter(owner.user_id.in_(rep_ids), owner.role == "owner",
                            sales_access.account_read_predicate(viewer, Customer.id)).all()) if rep_ids else []
    by_rep = defaultdict(set)
    for uid, cid in associations:
        by_rep[uid].add(cid)
    ids = sorted({cid for _, cid in associations})
    if ids:
        pipeline = pipeline_read_model.pipeline_summaries_for(db, ids)
        renewals = pipeline_read_model.renewal_attention_summaries_for(db, ids, reference_date=now.date(),
                                                                       as_of=now.isoformat())
        overdue = or_(CustomerTask.due_at < now.replace(tzinfo=None),
                      (CustomerTask.due_at.is_(None)) & (CustomerTask.due_date < now.date()))
        tasks = {cid: (total, late) for cid, total, late in db.query(
            CustomerTask.customer_id, func.count(CustomerTask.id),
            func.sum(case((overdue, 1), else_=0))).filter(
            CustomerTask.customer_id.in_(ids), CustomerTask.status.in_(("open", "in_progress")))
            .group_by(CustomerTask.customer_id).all()}
        activities = {cid for (cid,) in db.query(CustomerActivity.customer_id).filter(
            CustomerActivity.customer_id.in_(ids), or_(CustomerActivity.occurred_date.is_not(None),
                                                       CustomerActivity.occurred_at.is_not(None))).distinct().all()}
        notes = {cid for (cid,) in db.query(SalesNote.customer_id).filter(
            SalesNote.customer_id.in_(ids), SalesNote.note_date.is_not(None)).distinct().all()}
        contacts = {cid for (cid,) in db.query(CustomerContact.customer_id).filter(
            CustomerContact.customer_id.in_(ids), CustomerContact.archived.is_(False)).distinct().all()}
        role_rows = db.query(CustomerContact.customer_id, ContactBuyingRole.role).join(
            ContactBuyingRole, ContactBuyingRole.contact_id == CustomerContact.id).filter(
            CustomerContact.customer_id.in_(ids), CustomerContact.archived.is_(False),
            ContactBuyingRole.role.in_(("economic_buyer", "champion"))).distinct().all()
        roles = defaultdict(set)
        for cid, role in role_rows:
            roles[cid].add(role)
    else:
        pipeline, renewals, tasks, activities, notes, contacts, roles = {}, {}, {}, set(), set(), set(), {}

    deal_rows = db.query(Deal.owner_user_id, Deal.customer_id, PipelineStage.stage_class,
        Deal.currency, Deal.amount_basis, func.count(Deal.id), func.sum(Deal.amount_minor),
        func.count(Deal.amount_minor)).join(PipelineStage, PipelineStage.id == Deal.stage_id).filter(
        Deal.owner_user_id.in_(rep_ids), Deal.customer_id.in_(ids)).group_by(
        Deal.owner_user_id, Deal.customer_id, PipelineStage.stage_class, Deal.currency, Deal.amount_basis).all()

    def deal_summary(rep_id=None):
        selected = [row for row in deal_rows if rep_id is None or row[0] == rep_id]
        amounts = {}
        counts = {"open": 0, "won": 0, "lost": 0}
        for _uid, _cid, stage, currency, basis, count, minor, known in selected:
            counts[stage] += count
            if stage != "open":
                continue
            key = (currency, basis)
            entry = amounts.setdefault(key, {"currency": currency, "basis": basis, "minor": None, "unknown_amounts": 0})
            if minor is not None:
                entry["minor"] = (entry["minor"] or 0) + minor
            entry["unknown_amounts"] += count - known
        return {"counts": counts, "open_amounts": list(amounts.values())}

    def summarize(cids, rep_id=None):
        counts = {key: sum(renewals[cid]["counts"][key] for cid in cids)
                  for key in (*pipeline_read_model.DATED_BUCKETS, "beyond_180", "unknown_date")}
        pipeline_totals = {key: _amounts(cids, pipeline, key) for key in ("acv", "tcv")}
        pipeline_totals["stages"] = {stage: sum(pipeline[cid]["stages"][stage] for cid in cids)
                                     for stage in ("open", "won", "lost", "unknown")}
        return {"rep_deals": deal_summary(rep_id), "accounts": len(cids), "pipeline": pipeline_totals,
                "renewal_counts": counts,
                "open_tasks": sum(tasks.get(cid, (0, 0))[0] for cid in cids),
                "overdue_tasks": sum(tasks.get(cid, (0, 0))[1] for cid in cids),
                "no_recorded_interaction": sum(cid not in activities and cid not in notes for cid in cids),
                "no_contacts_recorded": sum(cid not in contacts for cid in cids),
                "no_economic_buyer_recorded": sum("economic_buyer" not in roles.get(cid, ()) for cid in cids),
                "no_champion_recorded": sum("champion" not in roles.get(cid, ()) for cid in cids)}

    return {"generated_at": now.isoformat(), "team": summarize(ids),
            "reps": [{"user_id": r.id, "username": r.username, "display_name": r.display_name,
                      **summarize(by_rep[r.id], r.id)} for r in reps],
            "basis": "Report-owned readable accounts; team totals deduplicate shared accounts. "
                     "Pipeline amounts sum rounded account totals; source-labelled USD estimates, "
                     "not booked revenue. No recorded evidence does not establish absence."}
