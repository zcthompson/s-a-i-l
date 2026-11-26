"""Read-only account-impact routes (gcm-p5).

Thin HTTP layer over ``backend.services.account_impact`` — the single
account-impact source for the global landing, My Dashboard, Global Admin and
the customer overview. Gated by the central sales_access resolver's READ
capability (an auditor may read; ps_admin has no sales capability).

Unauthenticated -> 401; unknown customer or no read capability -> the same
404 (404-first, R4/Q7: a by-name probe cannot reveal existence).
The portfolio roll-up covers ONLY customers the caller may read (an empty
scope is an empty portfolio, never "all").
"""

from fastapi import APIRouter, HTTPException, Request

from backend.auth import get_user_from_request
from backend.models.use_case import Customer, get_session
from backend.services import pipeline_read_model, sales_access
from backend.services.account_impact import (
    _compute_account_impact,
    compute_account_impact,
    compute_portfolio_impact,
    primary_reps_for,
)

router = APIRouter(tags=["account-impact"])


def _require_user(request: Request) -> dict:
    user = get_user_from_request(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.get("/api/customers/{customer_name}/account-impact/")
def get_customer_account_impact(customer_name: str, request: Request):
    """Explainable account-impact summary for one customer (read-only)."""
    user = _require_user(request)
    db = get_session()
    try:
        customer = db.query(Customer).filter(Customer.name == customer_name).first()
        if customer is None or not sales_access.can(user, db, sales_access.CAP_READ, customer.id):
            raise HTTPException(status_code=404, detail="Customer not found")
        return compute_account_impact(db, customer.id)
    finally:
        db.close()


@router.get("/api/account-impact/portfolio/")
def get_portfolio_account_impact(request: Request, my_view: bool = False):
    """Portfolio roll-up over the caller's authorized customers (read-only).

    A system admin sees every customer unless ``my_view`` narrows to their own
    scope; every other caller is always limited to their resolver scope.
    """
    user = _require_user(request)
    db = get_session()
    try:
        if sales_access.is_unrestricted(user) and not my_view:
            candidates = {cid for (cid,) in db.query(Customer.id).all()}
        else:
            candidates = set(sales_access.customer_scope(user, db))
        names = {
            row.id: row
            for row in db.query(
                Customer.id, Customer.name, Customer.vertical, Customer.branch,
                Customer.sales_area, Customer.primary_subsidiary,
            )
            .filter(Customer.id.in_(candidates)).all()
        } if candidates else {}
        readable = sorted(
            cid for cid in names
            if sales_access.can(user, db, sales_access.CAP_READ, cid)
        )
        primary_reps = primary_reps_for(db, readable)
        pipeline_summaries = pipeline_read_model.pipeline_summaries_for(db, readable)
        portfolio = compute_portfolio_impact(db, readable, pipeline_summaries=pipeline_summaries)
        renewals = pipeline_read_model.portfolio_renewal_rollup(db, readable)
        customers = []
        for cid in readable:
            summary = _compute_account_impact(db, cid, pipeline_summaries[cid])
            pipeline = pipeline_summaries[cid]["amounts"]
            customers.append({
                "customer_id": cid,
                "customer_name": names[cid].name,
                "vertical": names[cid].vertical,
                "branch": names[cid].branch,
                "sales_area": names[cid].sales_area,
                "primary_subsidiary": names[cid].primary_subsidiary,
                "primary_rep": primary_reps[cid],
                # These are presentation hints only; mutation routes enforce
                # their own per-account checks again.
                "can_score": sales_access.can(user, db, sales_access.CAP_EDIT, cid),
                "can_manage_customer": bool(
                    user.get("is_admin") == 1
                    or (user.get("junction_roles", {}).get(cid) == "owner"
                        and sales_access.can(user, db, sales_access.CAP_METADATA, cid))
                ),
                "renewals": renewals.account_summaries[cid],
                "coverage": summary["coverage"],
                "total_impact": summary["total_impact"]["value"],
                "pipeline": {
                    "acv": pipeline["acv"]["total"],
                    "tcv": pipeline["tcv"]["total"],
                    "coverage": pipeline["acv"]["coverage"],
                },
            })
        portfolio["renewals"] = renewals
        portfolio["customers"] = customers
        portfolio["scope"] = sales_access.summary(user, db)["scope_label"]
        return portfolio
    finally:
        db.close()
