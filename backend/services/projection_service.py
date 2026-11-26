"""Projection service — data-grounded customer projections.

Projections forecast AI readiness across two axes over a selected timeline:
- Speed (0-100): how quickly the customer can adopt AI/use cases
- Value (0-100): projected business value from current use cases

Design (v2):
- Speed, Value and Confidence are computed DETERMINISTICALLY from the
  customer's use case and business impact data (rule-based, no inference
  required for the numbers).
- The model refines the natural-language recommendations when a configured
  endpoint is reachable; otherwise deterministic fallbacks are used.
- Key factors are always computed from the customer's own data so every
  client gets a client-specific factor list (never empty when data exists).

Timelines (single-select in the UI — one timeline per projection):
- 30-60 days (45d), 3-6 months (135d), 6-12 months (270d)
"""

import json
import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.clients.ai_client import AIClient
from backend.models.use_case import Customer, Projection, UseCase
from backend.services.config_service import effective_inference_settings

# Selectable timelines. Midpoints mirror the analytics trend-prediction
# horizons (45 / 135 / 270 days). Only ONE timeline runs per projection.
PROJECTION_TIMELINES: dict[str, dict[str, Any]] = {
    "30-60d": {"days": 45, "label": "30–60 days"},
    "3-6m": {"days": 135, "label": "3–6 months"},
    "6-12m": {"days": 270, "label": "6–12 months"},
}

DEFAULT_TIMELINE = "30-60d"

# Confidence damping: longer horizons are inherently less certain.
HORIZON_CONFIDENCE_PENALTY: dict[int, float] = {45: 0.0, 135: 0.05, 270: 0.10}


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


class ProjectionService:
    """Business logic for customer projections."""

    @staticmethod
    def assert_delete_access(db: Session, user: dict[str, Any], customer_id: int) -> None:
        """Require global-admin or customer-owner access to delete a projection.

        Customer membership is supplied by ``get_user_from_request`` from the
        authoritative CustomerUser junction table.
        """
        if user.get("is_admin"):
            return

        role = (user.get("junction_roles") or {}).get(customer_id)
        if role != "owner":
            raise ValueError("Global admin or customer owner role required")

    # ── Deterministic core ─────────────────────────────────────────

    @staticmethod
    def evaluate_base(use_cases: list[UseCase], days: int) -> dict[str, Any]:
        """Rule-based evaluation of use case + business impact data.

        Returns speed/value axes, confidence, key factors, fallback
        recommendations and a compact data context for the model prompt.
        """

        def _f(v: Any) -> float:
            """Coerce a (possibly None) DB value to float, 0.0 otherwise."""
            try:
                return 0.0 if v is None else float(v)
            except (TypeError, ValueError):
                return 0.0

        def _s(v: Any) -> str:
            return str(v) if v is not None else ""

        scored = [(uc, _f(uc.overall_score)) for uc in use_cases if uc.overall_score is not None]
        n = len(use_cases)
        scores = [s for _, s in scored]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        total_savings = sum(_f(uc.estimated_savings) for uc in use_cases)
        total_revenue = sum(_f(uc.estimated_revenue) for uc in use_cases)
        total_impact = total_savings + total_revenue
        active = sum(1 for uc in use_cases if _s(uc.status) == "active")
        quick_wins = sorted(
            ((uc, s) for uc, s in scored if s >= 60),
            key=lambda pair: pair[1],
            reverse=True,
        )

        # Speed (adoption velocity): the readiness of the scored portfolio.
        speed_current = avg_score if scores else 20.0

        # Value: combined savings + revenue potential; $1M normalizes to 100.
        if total_impact > 0:
            value_current = min(100.0, total_impact / 10000.0)
        else:
            value_current = 10.0 if n else 0.0

        # Momentum (0..1): blend of active share and quick-win share.
        quick_win_ratio = len(quick_wins) / len(scored) if scored else 0.0
        active_ratio = active / n if n else 0.0
        momentum = 0.4 * quick_win_ratio + 0.6 * active_ratio

        # Horizon scaling: growth scales with sqrt(horizon), capped.
        scale = math.sqrt(days / 45.0)
        rate = min(0.45, (0.06 + 0.14 * momentum) * scale)

        def project_axis(current: float) -> dict[str, Any]:
            projected = _clamp(current + (100.0 - current) * rate)
            delta = projected - current
            trajectory = "improving" if delta > 2 else ("declining" if delta < -2 else "stable")
            return {
                "current": round(_clamp(current), 1),
                "projected": round(projected, 1),
                "trajectory": trajectory,
            }

        # Confidence: data completeness, damped by horizon length.
        scored_ratio = len(scored) / n if n else 0.0
        confidence = (
            0.40
            + 0.35 * scored_ratio
            + min(0.15, n * 0.01)
            + (0.05 if total_impact > 0 else 0.0)
            - HORIZON_CONFIDENCE_PENALTY.get(days, 0.0)
        )
        confidence = round(_clamp(confidence, 0.1, 0.95), 2)

        # Key factors — always populated and specific to this customer.
        factors: list[str] = []
        factors.append(f"{len(scored)} of {n} use cases scored — average readiness {avg_score:.0f}/100")
        if total_impact > 0:
            factors.append(f"Combined savings + revenue potential of ${total_impact:,.0f}")
        else:
            factors.append("No savings or revenue estimates yet — enter impact data to sharpen the value axis")

        dept_scores: dict[str, list[float]] = {}
        for uc, s in scored:
            dept = _s(uc.department)
            if dept:
                dept_scores.setdefault(dept, []).append(s)

        def _dept_avg(d: str) -> float:
            return sum(dept_scores[d]) / len(dept_scores[d])

        low_dept: str | None = None
        if dept_scores:
            top_dept = max(dept_scores, key=_dept_avg)
            factors.append(
                f"Strongest department: {top_dept} (avg {_dept_avg(top_dept):.0f} across {len(dept_scores[top_dept])} scored use cases)"
            )
            low_dept = min(dept_scores, key=_dept_avg)
            if low_dept != top_dept:
                factors.append(f"Weakest department: {low_dept} (avg {_dept_avg(low_dept):.0f})")

        if quick_wins:
            factors.append(f"{len(quick_wins)} high-readiness use case(s) (score ≥ 60) can move first")

        factors = factors[:5]

        # Deterministic fallback recommendations.
        recs: list[str] = []
        if quick_wins:
            top_titles = ", ".join(_s(uc.title) for uc, _ in quick_wins[:3])
            recs.append(f"Start with the highest-readiness use cases: {top_titles}")
        if low_dept and dept_scores.get(low_dept):
            recs.append(
                f"Close the readiness gap in {low_dept} (avg {_dept_avg(low_dept):.0f}) before scaling org-wide"
            )
        if total_impact <= 0:
            recs.append("Add savings/revenue estimates to the use cases so the value axis reflects real impact")
        recs.append("Re-run this projection after the next scoring round to confirm momentum")

        return {
            "speed": project_axis(speed_current),
            "value": project_axis(value_current),
            "confidence": confidence,
            "key_factors": factors,
            "fallback_recommendations": recs,
            "context": {
                "use_case_count": n,
                "scored_count": len(scored),
                "average_score": round(avg_score, 1),
                "total_savings": round(total_savings, 2),
                "total_revenue": round(total_revenue, 2),
                "active_count": active,
                "departments": sorted(dept_scores.keys()),
                "quick_wins": [_s(uc.title) for uc, _ in quick_wins[:5]],
            },
        }

    # ── Model refinement (text only; numbers stay deterministic) ──

    @staticmethod
    async def _model_recommendations(
        db: Session,
        customer_name: str,
        timeline: dict[str, Any],
        context: dict[str, Any],
    ) -> list[str]:
        """Ask the configured model for 3-5 specific, actionable recommendations.

        Raises on any failure (caller falls back to deterministic recs).
        """
        client = AIClient(effective_inference_settings(db))

        user_prompt = (
            f"Customer: {customer_name}\n"
            f"Projection timeline: {timeline['label']} (next {timeline['days']} days)\n"
            f"Data: {json.dumps(context, indent=2)}\n\n"
            "Provide exactly 3 to 5 short, specific, actionable recommendations to improve this "
            "customer's AI adoption over the stated timeline. Be concrete to this customer's data. "
            "Respond with ONLY valid JSON in this format: {\"recommendations\": [\"...\", \"...\"]}"
        )
        system_prompt = (
            "You are an AI adoption analyst for enterprise customers. "
            "Respond with ONLY valid JSON — no commentary, no markdown fences."
        )

        text = (await client.complete(system_prompt, user_prompt, max_tokens=600)).strip()
        # Strip code fences if the model added them anyway.
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Model response did not contain a JSON object")
        obj = json.loads(text[start:end + 1])
        recs = obj.get("recommendations")
        if not isinstance(recs, list):
            raise ValueError("Model response missing 'recommendations' list")
        cleaned = [str(r).strip() for r in recs if str(r).strip()][:5]
        if not cleaned:
            raise ValueError("Model returned an empty recommendation list")
        return cleaned

    # ── Public API ─────────────────────────────────────────────────

    @staticmethod
    async def generate_projection(
        db: Session, customer_name: str, horizon: str = DEFAULT_TIMELINE
    ) -> dict[str, Any]:
        """Generate a data-grounded projection for a customer.

        The Speed/Value/Confidence numbers are computed deterministically
        from the customer's use case and business impact data; the model
        refines the recommendation text when available.

        Raises ValueError if the customer or timeline is invalid.
        """
        if horizon not in PROJECTION_TIMELINES:
            raise ValueError(
                f"Unsupported timeline '{horizon}'. Allowed: {', '.join(PROJECTION_TIMELINES)}"
            )
        timeline = PROJECTION_TIMELINES[horizon]

        customer = db.query(Customer).filter(Customer.name == customer_name).first()
        if not customer:
            raise ValueError(f"Customer {customer_name} not found")

        use_cases = db.query(UseCase).filter(UseCase.customer_id == customer.id).all()

        base_payload = {
            "customer_name": customer_name,
            "generated_at": datetime.now(UTC).isoformat(),
            "horizon": horizon,
            "horizon_label": timeline["label"],
        }

        if not use_cases:
            return {
                **base_payload,
                "speed": {"current": 0.0, "projected": 0.0, "trajectory": "stable"},
                "value": {"current": 0.0, "projected": 0.0, "trajectory": "stable"},
                "key_factors": ["No use cases to analyze"],
                "recommendations": ["Create use cases for this customer to generate a projection"],
                "confidence": 0.0,
                "model_used": False,
            }

        base = ProjectionService.evaluate_base(use_cases, timeline["days"])

        recommendations = base["fallback_recommendations"]
        model_used = False
        try:
            recommendations = await ProjectionService._model_recommendations(
                db, customer_name, timeline, base["context"]
            )
            model_used = True
        except Exception:
            # Deterministic fallback stands — projection still fully usable.
            model_used = False

        return {
            **base_payload,
            "speed": base["speed"],
            "value": base["value"],
            "key_factors": base["key_factors"],
            "recommendations": recommendations,
            "confidence": base["confidence"],
            "model_used": model_used,
        }

    @staticmethod
    def get_projection(db: Session, customer_name: str) -> dict[str, Any] | None:
        """Get the latest projection for a customer.

        Returns the stored payload unwrapped — same shape POST /generate
        returns and the same shape the frontend Projection type expects.
        Returns None if no projection exists.
        """
        projection = db.query(Projection).filter(
            Projection.customer_name == customer_name
        ).order_by(Projection.generated_at.desc()).first()

        if not projection:
            return None

        data: dict[str, Any] = projection.projection_data  # type: ignore[assignment]
        return data

    @staticmethod
    def store_projection(db: Session, projection: dict[str, Any]) -> bool:
        """Store a projection in the database (replaces any existing row)."""
        from backend.models.use_case import Customer

        customer_name = projection.get("customer_name")
        if not customer_name:
            return False

        customer = db.query(Customer).filter(Customer.name == customer_name).first()
        if not customer:
            return False

        existing = db.query(Projection).filter(
            Projection.customer_name == customer_name
        ).first()

        if existing:
            existing.generated_at = datetime.now(UTC)
            existing.projection_data = projection
            existing.status = "completed"
        else:
            db.add(Projection(
                customer_id=customer.id,
                customer_name=customer_name,
                generated_at=datetime.now(UTC),
                projection_data=projection,
                status="completed",
            ))

        db.commit()
        return True

    @staticmethod
    def clear_projection(db: Session, customer_name: str) -> bool:
        """Clear a projection for a customer."""
        from backend.models.use_case import Customer

        customer = db.query(Customer).filter(Customer.name == customer_name).first()
        if not customer:
            return False

        db.query(Projection).filter(
            Projection.customer_name == customer_name
        ).delete()

        db.commit()
        return True
