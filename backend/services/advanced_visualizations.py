"""Service layer for advanced visualization data.

Supports customer-scoped queries via optional ``customer_id`` parameter
and user-scoped queries via the ``customer_users`` junction table.
"""


from sqlalchemy.orm import Session

from backend.models.use_case import UseCase
from backend.services.scoring import ScoringService

# Effort mapping from timeline_estimate to numeric effort level
EFFORT_MAP: dict[str, int] = {
    "short": 1,
    "medium": 2,
    "long": 3,
}

EFFORT_LABELS: dict[int, str] = {
    1: "Short",
    2: "Medium",
    3: "Long",
}

# Department colors for the scatter plot
DEPT_COLORS: dict[str, str] = {
    "Operations": "#4CAF50",
    "Customer Success": "#2196F3",
    "Supply Chain": "#FF9800",
    "Legal": "#9C27B0",
    "HR / L&D": "#E91E63",
    "Finance": "#607D8B",
}


class AdvancedVisualizationsService:
    """Business logic for advanced visualization endpoints."""

    # ── Impact Matrix ──────────────────────────────────────────────────────

    @staticmethod
    def get_impact_matrix(
        db: Session,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> dict:
        """Return scored use cases plotted on impact vs effort matrix.

        X-axis: total impact (estimated_savings + estimated_revenue)
        Y-axis: effort (1=short, 2=medium, 3=long)
        Bubble size: overall_score
        Color: department
        """
        query = (
            db.query(UseCase)
            .filter(
                UseCase.overall_score.isnot(None),
                (UseCase.estimated_savings.isnot(None)) |
                (UseCase.estimated_revenue.isnot(None)),
            )
        )
        if customer_id is not None:
            query = query.filter(UseCase.customer_id == customer_id)
        elif customer_ids is not None:
            query = query.filter(UseCase.customer_id.in_(customer_ids))
        use_cases = query.all()

        points = []
        for uc in use_cases:
            savings = uc.estimated_savings or 0
            revenue = uc.estimated_revenue or 0
            total_impact = round(savings + revenue, 2)
            timeline = (uc.timeline_estimate or "").lower()
            effort = EFFORT_MAP.get(timeline, 2)  # default to medium

            points.append({
                "id": uc.id,
                "title": uc.title,
                "department": uc.department,
                "overall_score": uc.overall_score,
                "total_impact": total_impact,
                "effort_level": effort,
                "effort_label": EFFORT_LABELS.get(effort, "Medium"),
                "impact_category": uc.impact_category,
                "status": uc.status,
            })

        # Calculate quadrants based on median impact and median effort
        if points:
            impacts = [p["total_impact"] for p in points]
            median_impact = sorted(impacts)[len(impacts) // 2]
            efforts = [p["effort_level"] for p in points]
            median_effort = sorted(efforts)[len(efforts) // 2]

            quadrants = {
                "quick_win": [],       # high impact, low effort
                "major_project": [],   # high impact, high effort
                "fill_in": [],         # low impact, low effort
                "thankless_task": [],  # low impact, high effort
            }
            for p in points:
                high_impact = p["total_impact"] >= median_impact
                low_effort = p["effort_level"] <= median_effort
                if high_impact and low_effort:
                    quadrants["quick_win"].append(p["title"])
                elif high_impact:
                    quadrants["major_project"].append(p["title"])
                elif low_effort:
                    quadrants["fill_in"].append(p["title"])
                else:
                    quadrants["thankless_task"].append(p["title"])
        else:
            quadrants = {"quick_win": [], "major_project": [], "fill_in": [], "thankless_task": []}

        return {"points": points, "quadrants": quadrants}

    # ── Department Comparison ──────────────────────────────────────────────

    @staticmethod
    def get_dept_comparison(
        db: Session,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> dict:
        """Return dimension-level comparison across departments.

        For each department, compute average scores across all scored use cases,
        showing both the overall average and per-dimension breakdown.

        Args:
            db: Database session
            customer_id: Optional single-customer scope
            customer_ids: Optional union scope (junction users, unscoped call)
        """
        scored_query = (
            db.query(UseCase)
            .filter(UseCase.overall_score.isnot(None))
        )
        if customer_id is not None:
            scored_query = scored_query.filter(UseCase.customer_id == customer_id)
        elif customer_ids is not None:
            scored_query = scored_query.filter(UseCase.customer_id.in_(customer_ids))
        else:
            scored_query = scored_query.filter(UseCase.customer_id.isnot(None))

        scored = scored_query.all()

        if not scored:
            return {"departments": [], "dimensions": ScoringService.DIMENSIONS_NAME_ORDER}

        # Group by department
        dept_groups: dict[str, list[UseCase]] = {}
        for uc in scored:
            dept = uc.department or "Unassigned"
            dept_groups.setdefault(dept, []).append(uc)

        dimension_names = ScoringService.DIMENSIONS_NAME_ORDER

        departments = []
        for dept, cases in sorted(dept_groups.items()):
            # Accumulate per-dimension scores across the department's use cases.
            # extract_dimension_scores() normalizes both stored payload shapes
            # (dimension_scores list and seeded flat dict) into canonical names.
            per_dimension: dict[str, list[float]] = {
                dim_name: [] for dim_name in dimension_names
            }
            for uc in cases:
                for dim_name, value in ScoringService.extract_dimension_scores(uc.scores).items():
                    if dim_name in per_dimension:
                        per_dimension[dim_name].append(value)

            # Build per-dimension averages
            dimension_avgs = []
            for dim_name in dimension_names:
                scores = per_dimension[dim_name]
                if scores:
                    dimension_avgs.append({
                        "dimension": dim_name,
                        "avg_score": round(sum(scores) / len(scores), 1),
                        "count": len(scores),
                        "min_score": round(min(scores), 1),
                        "max_score": round(max(scores), 1),
                    })
                else:
                    dimension_avgs.append({
                        "dimension": dim_name,
                        "avg_score": 0.0,
                        "count": 0,
                        "min_score": 0.0,
                        "max_score": 0.0,
                    })

            departments.append({
                "department": dept,
                "use_case_count": len(cases),
                "avg_overall": round(
                    sum(uc.overall_score for uc in cases) / len(cases), 1
                ),
                "dimension_avgs": dimension_avgs,
            })

        return {
            "departments": departments,
            "dimensions": dimension_names,
        }

    # ── Score Drill-Down ───────────────────────────────────────────────────

    @staticmethod
    def get_drill_down(
        db: Session,
        use_case_id: int,
        customer_id: int | None = None,
    ) -> dict | None:
        """Return detailed score breakdown for a single use case.

        Includes dimension-level details, score history, reasoning,
        recommendations, and business impact summary.

        Args:
            db: Database session
            use_case_id: Use case to drill into
            customer_id: Optional customer scope for audit filtering
        """
        uc = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if not uc or not uc.scores:
            return None

        # Optional audit: verify customer ownership for auditors
        if customer_id and customer_id != uc.customer_id:
            return {"error": "No access to this use case"}

        scores = uc.scores
        dim_details = []
        dim_list = scores.get("dimension_scores")
        if isinstance(dim_list, list):
            for dim in dim_list:
                score_val = dim.get("score", 0)
                weight = dim.get("weight", 0)
                dim_details.append({
                    "name": dim.get("name", ""),
                    "score": round(score_val, 1),
                    "weight": weight,
                    "weighted_score": round(score_val * weight, 1),
                    "description": dim.get("description", ""),
                })
        elif scores:
            # Seeded / legacy flat-dict payload: reconstruct dimension details
            # with canonical names and weights from the scoring definition.
            weights = {d["name"]: d["weight"] for d in ScoringService.DIMENSIONS}
            flat = ScoringService.extract_dimension_scores(scores)
            for name in ScoringService.DIMENSIONS_NAME_ORDER:
                if name not in flat:
                    continue
                value = flat[name]
                weight = weights[name]
                dim_details.append({
                    "name": name,
                    "score": round(value, 1),
                    "weight": weight,
                    "weighted_score": round(value * weight, 1),
                    "description": "",
                })

        # Build score history for trend visualization
        history = uc.score_history or []
        score_history = [
            {
                "timestamp": entry.get("timestamp") or entry.get("scored_at", ""),
                "overall_score": entry.get("score", 0),
            }
            for entry in history
        ]

        savings = uc.estimated_savings or 0
        revenue = uc.estimated_revenue or 0

        return {
            "id": uc.id,
            "title": uc.title,
            "department": uc.department,
            "status": uc.status,
            "overall_score": uc.overall_score,
            "dimension_details": dim_details,
            "score_history": score_history,
            "reasoning": scores.get("reasoning"),
            "recommendations": scores.get("recommendations"),
            "business_impact": {
                "savings": round(savings, 2),
                "revenue": round(revenue, 2),
                "total": round(savings + revenue, 2),
            },
            "timeline_estimate": uc.timeline_estimate,
            "scored_at": uc.scored_at.isoformat() if uc.scored_at else None,
        }
