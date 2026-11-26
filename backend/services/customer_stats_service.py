"""Customer statistics and aggregation service.

Provides per-customer and global aggregate statistics leveraging
the new ``customer_users`` junction table for user-scoped filtering.
"""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import case, desc, func
from sqlalchemy.orm import Session

from backend.models.use_case import Customer, CustomerUser, UseCase
from backend.services import sales_access


class CustomerStatsService:
    """Per-customer and global statistics aggregation."""

    @staticmethod
    def get_customer_stats(db: Session, customer: Customer) -> dict:
        """Aggregate stats for a single customer."""
        query = db.query(UseCase).filter(UseCase.customer_id == customer.id)

        use_cases = query.all()
        total = len(use_cases)
        scored = sum(1 for uc in use_cases if uc.overall_score is not None)
        avg_score = (
            sum(uc.overall_score for uc in use_cases if uc.overall_score) / scored
            if scored
            else 0.0
        )

        # Department breakdown
        dept_stats = (
            db.query(
                UseCase.department,
                func.count(UseCase.id).label("count"),
                func.avg(UseCase.overall_score).label("avg_score"),
                func.sum(
                    func.coalesce(UseCase.estimated_savings, 0)
                    + func.coalesce(UseCase.estimated_revenue, 0)
                ).label("total_impact"),
            )
            .filter(UseCase.customer_id == customer.id)
            .group_by(UseCase.department)
            .all()
        )

        # Status breakdown
        status_stats = (
            db.query(UseCase.status, func.count(UseCase.id).label("count"))
            .filter(UseCase.customer_id == customer.id)
            .group_by(UseCase.status)
            .all()
        )

        # Impact summary
        total_savings = db.query(func.sum(UseCase.estimated_savings)).filter(
            UseCase.customer_id == customer.id
        ).scalar() or 0
        total_revenue = db.query(func.sum(UseCase.estimated_revenue)).filter(
            UseCase.customer_id == customer.id
        ).scalar() or 0

        # Recent use cases
        recent = (
            db.query(UseCase)
            .filter(UseCase.customer_id == customer.id)
            .order_by(desc(UseCase.updated_at))
            .limit(5)
            .all()
        )

        return {
            "customer_id": customer.id,
            "customer_name": customer.name,
            "total_use_cases": total,
            "scored_use_cases": scored,
            "unscored_use_cases": total - scored,
            "average_score": round(avg_score, 1),
            "by_department": {
                dept or "Unassigned": {
                    "count": count,
                    "avg_score": round(avg_score_val, 1) if avg_score_val else 0,
                    "total_impact": round(total_impact, 2),
                }
                for dept, count, avg_score_val, total_impact in dept_stats
            },
            "by_status": {
                status: count for status, count in status_stats
            },
            "impact_summary": {
                "total_savings": round(total_savings, 2),
                "total_revenue": round(total_revenue, 2),
                "total_impact": round(total_savings + total_revenue, 2),
            },
            "recent_use_cases": [
                {
                    "id": uc.id,
                    "title": uc.title,
                    "status": uc.status,
                    "overall_score": uc.overall_score,
                    "updated_at": uc.updated_at.isoformat() if uc.updated_at else None,
                }
                for uc in recent
            ],
        }

    @staticmethod
    def get_global_stats(db: Session) -> dict:
        """Aggregate stats across all customers."""
        total_customers = db.query(Customer).count()
        total_use_cases = db.query(UseCase).count()
        scored = db.query(UseCase).filter(UseCase.overall_score.isnot(None)).count()

        avg_score = (
            db.query(func.avg(UseCase.overall_score))
            .filter(UseCase.overall_score.isnot(None))
            .scalar()
        ) or 0.0

        total_savings = db.query(func.sum(UseCase.estimated_savings)).scalar() or 0
        total_revenue = db.query(func.sum(UseCase.estimated_revenue)).scalar() or 0

        # Per-customer summary
        customer_summaries = (
            db.query(
                Customer.id.label("customer_id"),
                Customer.name.label("customer_name"),
                func.count(UseCase.id).label("use_case_count"),
                func.avg(UseCase.overall_score).label("average_score"),
                func.count(UseCase.overall_score).label("total_scored"),
                func.sum(
                    func.coalesce(UseCase.estimated_savings, 0)
                    + func.coalesce(UseCase.estimated_revenue, 0)
                ).label("total_impact"),
            )
            .outerjoin(UseCase, Customer.id == UseCase.customer_id)
            .group_by(Customer.id, Customer.name)
            .all()
        )

        score_bands = db.query(
            func.sum(case((UseCase.overall_score >= 70, 1), else_=0)).label("high"),
            func.sum(
                case(
                    (
                        (UseCase.overall_score >= 35)
                        & (UseCase.overall_score < 70),
                        1,
                    ),
                    else_=0,
                )
            ).label("mid"),
            func.sum(
                case(
                    (
                        UseCase.overall_score.isnot(None)
                        & (UseCase.overall_score < 35),
                        1,
                    ),
                    else_=0,
                )
            ).label("low"),
            func.sum(case((UseCase.overall_score.is_(None), 1), else_=0)).label(
                "unscored"
            ),
        ).one()

        # Junction table user counts
        user_counts = (
            db.query(
                CustomerUser.customer_id,
                func.count(CustomerUser.user_id).label("user_count"),
            )
            .group_by(CustomerUser.customer_id)
            .all()
        )
        user_count_map = {r.customer_id: r.user_count for r in user_counts}

        return {
            "total_customers": total_customers,
            "total_use_cases": total_use_cases,
            "total_scored": scored,
            "average_score": round(avg_score, 1),
            "total_savings": round(total_savings, 2),
            "total_revenue": round(total_revenue, 2),
            "total_impact": round(total_savings + total_revenue, 2),
            "score_bands": {
                "high": int(score_bands.high or 0),
                "mid": int(score_bands.mid or 0),
                "low": int(score_bands.low or 0),
                "unscored": int(score_bands.unscored or 0),
            },
            "customers": [
                {
                    "customer_id": c.customer_id,
                    "customer_name": c.customer_name,
                    "use_case_count": c.use_case_count,
                    "average_score": (
                        round(c.average_score, 1)
                        if c.average_score is not None
                        else None
                    ),
                    "total_scored": c.total_scored,
                    "total_impact": round(c.total_impact, 2),
                    "user_count": user_count_map.get(c.customer_id, 0),
                }
                for c in customer_summaries
            ],
        }

    @staticmethod
    def get_user_stats(db: Session, user_id: int) -> dict:
        """Aggregate stats across a user's EXPLICIT junction assignments.

        Kept junction-based on purpose: it backs the admin ``my_view`` leg of
        GET /customers/stats/ ("my customers" = the admin's own assignments,
        not the reads-all expansion). Non-admin callers use the central-scope
        path in ``build_stats_response``.
        """
        customer_ids = CustomerStatsService.get_user_stats_ids(db, user_id)
        return CustomerStatsService.get_stats_for_customer_ids(db, customer_ids)

    @staticmethod
    def get_user_stats_ids(db: Session, user_id: int) -> list:
        """Customer ids from the user's junction rows (admin my_view basis)."""
        junction_records = (
            db.query(CustomerUser.customer_id)
            .filter(CustomerUser.user_id == user_id)
            .all()
        )
        return [r.customer_id for r in junction_records]

    @staticmethod
    def get_stats_for_customer_ids(db: Session, customer_ids: list) -> dict:
        """Aggregate stats for the supplied authorized customer IDs."""
        if not customer_ids:
            return {
                "total_use_cases": 0,
                "total_scored": 0,
                "average_score": 0,
                "total_savings": 0,
                "total_revenue": 0,
                "customers": [],
            }

        # Aggregate across all accessible customers
        query = db.query(UseCase).filter(UseCase.customer_id.in_(customer_ids))
        use_cases = query.all()

        total = len(use_cases)
        scored = sum(1 for uc in use_cases if uc.overall_score is not None)
        avg_score = (
            sum(uc.overall_score for uc in use_cases if uc.overall_score) / scored
            if scored
            else 0.0
        )

        total_savings = db.query(func.sum(UseCase.estimated_savings)).filter(
            UseCase.customer_id.in_(customer_ids)
        ).scalar() or 0
        total_revenue = db.query(func.sum(UseCase.estimated_revenue)).filter(
            UseCase.customer_id.in_(customer_ids)
        ).scalar() or 0

        # Per-customer breakdown for this user
        customer_stats = (
            db.query(
                Customer.id.label("customer_id"),
                Customer.name.label("customer_name"),
                func.count(UseCase.id).label("use_case_count"),
            )
            .outerjoin(UseCase, UseCase.customer_id == Customer.id)
            .filter(Customer.id.in_(customer_ids))
            .group_by(Customer.id, Customer.name)
            .all()
        )

        return {
            "total_use_cases": total,
            "total_scored": scored,
            "average_score": round(avg_score, 1),
            "total_savings": round(total_savings, 2),
            "total_revenue": round(total_revenue, 2),
            "customers": [
                {
                    "customer_id": c.customer_id,
                    "customer_name": c.customer_name or "Unknown",
                    "use_case_count": c.use_case_count,
                }
                for c in customer_stats
            ],
        }

    @staticmethod
    def empty_stats_response() -> dict:
        """Empty aggregate stats response (caller has no accessible customers)."""
        return {
            "total_customers": 0,
            "total_use_cases": 0,
            "total_scored": 0,
            "average_score": 0.0,
            "total_savings": 0.0,
            "total_revenue": 0.0,
            "total_impact": 0.0,
            "by_customer": [],
        }

    @staticmethod
    def build_stats_response(db: Session, user: dict, my_view: bool = False) -> dict:
        """Build the GET /customers/stats/ response for the caller.

        Admins see all customers, or their central scope in my_view. Other
        callers see their central scope filtered by READ capability.
        """
        if sales_access.is_unrestricted(user) and not my_view:
            return CustomerStatsService.get_global_stats(db)

        # Match the portfolio endpoint: the central scope is a candidate set,
        # and READ is the final authority for each account.
        scope = sales_access.customer_scope(user, db)
        readable = [cid for cid in scope if sales_access.can(user, db, sales_access.CAP_READ, cid)]
        stats = CustomerStatsService.get_stats_for_customer_ids(db, readable)
        return {
            "total_customers": len(stats.get("customers", [])),
            "total_use_cases": stats.get("total_use_cases", 0),
            "total_scored": stats.get("total_scored", 0),
            "average_score": stats.get("average_score", 0.0),
            "total_savings": stats.get("total_savings", 0.0),
            "total_revenue": stats.get("total_revenue", 0.0),
            "total_impact": stats.get("total_savings", 0.0) + stats.get("total_revenue", 0.0),
            "customers": stats.get("customers", []),
        }

    @staticmethod
    def build_customer_stats_response(db: Session, customer: Customer, user: dict) -> dict:
        """Build the GET /customers/{name}/stats/ response for the caller.

        Raises HTTPException 404 when the caller lacks READ access to the
        customer (central policy) — the same 404
        as a missing customer, so a by-name probe cannot reveal existence
. Never a 200 ``{"error":...}`` dict: that could
        masquerade as stats and made the FE render zeros/undefined.
        """
        if not sales_access.can(user, db, sales_access.CAP_READ, customer.id):
            raise HTTPException(status_code=404, detail="Customer not found")

        stats = CustomerStatsService.get_customer_stats(db, customer)

        # Department breakdown with savings and revenue
        by_department = {}
        for dept_name, dept_stats in stats["by_department"].items():
            dept_savings = sum(
                uc.estimated_savings or 0
                for uc in customer.use_cases
                if uc.department == dept_name
            )
            dept_revenue = sum(
                uc.estimated_revenue or 0
                for uc in customer.use_cases
                if uc.department == dept_name
            )
            by_department[dept_name] = {
                "count": dept_stats["count"],
                "avg_score": dept_stats["avg_score"],
                "total_savings": round(dept_savings, 2),
                "total_revenue": round(dept_revenue, 2),
            }

        # Status breakdown from use cases
        status_breakdown = {}
        for uc in customer.use_cases:
            status = uc.status or "unknown"
            status_breakdown[status] = status_breakdown.get(status, 0) + 1

        # Recent activity (last 5 use cases)
        recent = sorted(
            customer.use_cases,
            key=lambda x: x.created_at or datetime(1970, 1, 1, tzinfo=UTC),
            reverse=True,
        )[:5]
        recent_activity = [
            {
                "id": uc.id,
                "title": uc.title,
                "created_at": uc.created_at.isoformat() if uc.created_at else None,
                "status": uc.status,
                "score": uc.overall_score,
            }
            for uc in recent
        ]

        return {
            "customer_name": customer.name,
            "customer_description": customer.description,
            "total_use_cases": stats["total_use_cases"],
            "scored_use_cases": stats["scored_use_cases"],
            "unscored_use_cases": stats["unscored_use_cases"],
            "average_score": stats["average_score"],
            "total_savings": stats["impact_summary"]["total_savings"],
            "total_revenue": stats["impact_summary"]["total_revenue"],
            "total_impact": stats["impact_summary"]["total_impact"],
            "departments": len(customer.departments),
            "by_department": by_department,
            "status_breakdown": status_breakdown,
            "recent_activity": recent_activity,
        }
