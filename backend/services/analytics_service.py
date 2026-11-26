"""Advanced analytics and predictive scoring service.

Supports customer-scoped queries via optional ``customer_id`` parameter
and user-scoped queries via junction table ``customer_users``.
"""

import math
from datetime import datetime
from typing import Any

from scipy import stats
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.collaboration import ScoreHistory
from backend.models.use_case import UseCase


class AnalyticsService:
    """Advanced analytics for trend prediction and correlations."""

    @staticmethod
    def get_trend_prediction(
        db: Session,
        use_case_id: int,
        customer_id: int | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        """Predict future scores based on historical trend using simple linear regression.

        Args:
            db: Database session
            use_case_id: Use case to predict
            customer_id: Optional customer scope for audit filtering
            days: Forecast horizon in days (default 30). The customer
                analytics stack uses 45 (30–60 days), 135 (3–6 months)
                and 270 (6–12 months).
        """
        use_case = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if use_case is None:
            return {"error": "Use case not found"}
        # Read from structured ScoreHistory table instead of JSON column
        history_entries = db.query(ScoreHistory).filter(
            ScoreHistory.use_case_id == use_case_id
        ).order_by(ScoreHistory.scored_at).all()

        if len(history_entries) < 2:
            return {"error": "Insufficient history for prediction"}

        # Extract scores and timestamps from table entries
        data_points = []
        for entry in history_entries[-10:]:  # Last 10 scores
            if entry.scored_at is not None and entry.score is not None:
                data_points.append((entry.scored_at.isoformat(), entry.score))

        if len(data_points) < 2:
            return {"error": "Insufficient data points for prediction"}

        # Sort by timestamp
        data_points.sort(key=lambda x: x[0])

        # Convert timestamps to ordinal days for regression
        base_date = datetime.fromisoformat(data_points[0][0])
        x = [(datetime.fromisoformat(ts) - base_date).days for ts, _ in data_points]
        y = [score for _, score in data_points]

        # scipy linear regression with confidence intervals
        n = len(x)
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)

        # Predict for the requested horizon
        future_days = days
        predicted_score = slope * future_days + intercept
        predicted_score = max(0, min(100, predicted_score))  # Clamp 0-100

        # Handle edge cases: constant scores → linregress returns nan
        if math.isnan(r_value) or math.isnan(std_err):
            # All scores identical — no predictive variance
            r_squared = 0.0
            p_value = 1.0
            std_err = 0.0
            lower_bound = max(0, y[-1])
            upper_bound = min(100, y[-1])
        else:
            # 95% confidence interval: predicted ± t(0.975, n-2) * std_err
            from scipy import stats as sp_stats
            t_crit = sp_stats.t.ppf(0.975, df=n - 2) if n > 2 else 1.96
            margin = t_crit * std_err
            lower_bound = max(0, predicted_score - margin)
            upper_bound = min(100, predicted_score + margin)
            r_squared = r_value ** 2

        # Confidence score: r-squared weighted by sample size
        sample_confidence = min(1.0, len(x) / 10)
        confidence = round(0.7 * r_squared + 0.3 * sample_confidence, 3)

        # Determine trend direction
        if abs(slope) < 0.1:
            trend = "stable"
        elif slope > 0:
            trend = "improving"
        else:
            trend = "declining"

        return {
            "use_case_id": use_case.id,
            "use_case_title": use_case.title,
            "current_score": y[-1],
            "days": days,
            "predicted_score": round(predicted_score, 1),
            "score_change": round(predicted_score - y[-1], 1),
            # Legacy alias: same value as predicted_score for the requested
            # horizon (kept for existing API clients/tests).
            "predicted_score_30d": round(predicted_score, 1),
            "trend": trend,
            "slope": round(slope, 4),
            "data_points": len(x),
            "confidence": confidence,
            "p_value": round(p_value, 6),
            "std_error": round(std_err, 4),
            "r_squared": round(r_squared, 4),
            "confidence_interval_95": {
                "lower": round(lower_bound, 1),
                "upper": round(upper_bound, 1),
            },
        }

    @staticmethod
    def get_department_trends(
        db: Session,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Get department-level trend analysis.

        Args:
            db: Database session
            customer_id: Optional single-customer scope
            customer_ids: Optional union scope (junction users' accessible
                customers); if neither is given, returns global
        """
        query = (
            db.query(
                UseCase.department,
                func.count(UseCase.id).label("count"),
                func.avg(UseCase.overall_score).label("avg_score"),
                func.sum(func.coalesce(UseCase.estimated_savings, 0) + func.coalesce(UseCase.estimated_revenue, 0)).label("total_impact"),
            )
            .group_by(UseCase.department)
        )

        if customer_id is not None:
            query = query.filter(UseCase.customer_id == customer_id)
        elif customer_ids is not None:
            if not customer_ids:
                return []
            query = query.filter(UseCase.customer_id.in_(customer_ids))
        else:
            query = query.filter(UseCase.customer_id.isnot(None))

        results = query.all()

        return [
            {
                "department": dept or "Unassigned",
                "use_case_count": count,
                "avg_score": round(avg_score, 1) if avg_score else 0,
                "total_impact": round(total_impact, 2),
            }
            for dept, count, avg_score, total_impact in results
        ]

    @staticmethod
    def get_score_impact_correlation(
        db: Session,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> dict[str, Any]:
        """Analyze correlation between business impact and scores.

        Args:
            db: Database session
            customer_id: Optional single-customer scope
            customer_ids: Optional union scope (junction users' accessible
                customers); if neither is given, returns global
        """
        query = db.query(UseCase).filter(UseCase.overall_score.isnot(None))

        if customer_id is not None:
            query = query.filter(UseCase.customer_id == customer_id)
        elif customer_ids is not None:
            if not customer_ids:
                return {"error": "No scored use cases available"}
            query = query.filter(UseCase.customer_id.in_(customer_ids))
        else:
            query = query.filter(UseCase.customer_id.isnot(None))

        scored = query.all()

        if not scored:
            return {"error": "No scored use cases available"}

        # Calculate correlation
        scores = [uc.overall_score for uc in scored]
        impacts = [
            (uc.estimated_savings or 0) + (uc.estimated_revenue or 0)
            for uc in scored
        ]

        # Simple correlation coefficient (Pearson)
        n = len(scores)
        mean_score = sum(scores) / n
        mean_impact = sum(impacts) / n

        cov = sum((s - mean_score) * (i - mean_impact) for s, i in zip(scores, impacts))
        std_score = (sum((s - mean_score) ** 2 for s in scores)) ** 0.5
        std_impact = (sum((i - mean_impact) ** 2 for i in impacts)) ** 0.5

        if std_score == 0 or std_impact == 0:
            correlation = 0.0
        else:
            correlation = cov / (std_score * std_impact)

        # R-squared
        r_squared = correlation ** 2

        return {
            "correlation": round(correlation, 3),
            "r_squared": round(r_squared, 3),
            "sample_size": n,
            "mean_score": round(mean_score, 1),
            "mean_impact": round(mean_impact, 2),
            "interpretation": AnalyticsService._interpret_correlation(correlation),
        }

    @staticmethod
    def _interpret_correlation(correlation: float) -> str:
        """Interpret Pearson correlation coefficient."""
        abs_corr = abs(correlation)
        if abs_corr >= 0.7:
            direction = "positive" if correlation > 0 else "negative"
            return f"Strong {direction} correlation"
        elif abs_corr >= 0.4:
            direction = "positive" if correlation > 0 else "negative"
            return f"Moderate {direction} correlation"
        else:
            direction = "positive" if correlation > 0 else "negative"
            return f"Weak {direction} correlation"
