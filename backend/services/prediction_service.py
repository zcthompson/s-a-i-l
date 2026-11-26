"""Model-generated readiness predictions (persisted).

Predictions are produced by the configured OpenAI-compatible model
(SAIL_AI_ENDPOINT / SAIL_AI_MODEL — nemotron-lightning in dev).
The application does not compute predictions itself: it sends the use
case's score history to the model, validates the returned JSON, and
persists the result.
"""
import json
from typing import Any

import httpx
from sqlalchemy.orm import Session

from backend.clients.ai_client import AIClient
from backend.models.collaboration import ScoreHistory
from backend.models.use_case import AIPrediction, UseCase
from backend.services.assessment_service import AssessmentService
from backend.services.config_service import effective_inference_settings


class AIPredictionService:
    """Generate and list model-based readiness predictions."""

    MODEL_TIMEOUT_SECONDS = 60.0
    SYSTEM_PROMPT = (
        "You are an AI readiness forecasting specialist. You are given the "
        "readiness score history of an AI use case and must predict its "
        "overall readiness score (0-100) at a future horizon. Base your "
        "prediction on the trajectory, momentum, and typical adoption curves "
        "for AI initiatives. Respond with ONLY valid JSON."
    )

    @staticmethod
    def assert_delete_access(db: Session, user: dict[str, Any], customer_id: int) -> None:
        """Require global-admin or customer-owner access to delete a prediction.

        Customer membership is supplied by ``get_user_from_request`` from the
        authoritative CustomerUser junction table.
        """
        if user.get("is_admin"):
            return

        role = (user.get("junction_roles") or {}).get(customer_id)
        if role != "owner":
            raise ValueError("Global admin or customer owner role required")

    @staticmethod
    def get_by_id(db: Session, prediction_id: int) -> AIPrediction | None:
        return db.query(AIPrediction).filter(AIPrediction.id == prediction_id).first()

    @staticmethod
    def delete(db: Session, prediction_id: int) -> dict:
        prediction = AIPredictionService.get_by_id(db, prediction_id)
        if not prediction:
            raise ValueError("Prediction not found")
        result = prediction.to_dict()
        db.delete(prediction)
        db.commit()
        return result

    @staticmethod
    def _build_prompt(uc: UseCase, history: list[ScoreHistory], days: int) -> str:
        lines = []
        for h in history[-12:]:
            date_str = h.scored_at.date().isoformat() if h.scored_at else "unknown"
            lines.append(f"- {date_str}: {h.score}/100")
        hist = "\n".join(lines) if lines else "(no prior scores yet)"
        current = uc.overall_score if uc.overall_score is not None else "unscored"
        return (
            f"Use case: {uc.title}\n"
            f"Department: {uc.department or 'N/A'}\n"
            f"Current overall readiness score: {current}\n\n"
            f"Score history (oldest first):\n{hist}\n\n"
            f"Predict the overall readiness score (0-100) approximately {days} days from now.\n"
            "Respond with ONLY valid JSON in this format:\n"
            '{\n'
            '  "predicted_score": <number 0-100>,\n'
            '  "trend": "improving" | "stable" | "declining",\n'
            '  "confidence": <number 0.0-1.0>,\n'
            '  "reasoning": "<2-3 sentence explanation>"\n'
            '}'
        )

    @staticmethod
    async def _call_model(system_prompt: str, user_prompt: str, max_tokens: int = 700,
                          overrides: dict[str, Any] | None = None) -> str:
        client = AIClient(overrides)
        try:
            return await client.complete(
                system_prompt, user_prompt,
                max_tokens=max_tokens, timeout=AIPredictionService.MODEL_TIMEOUT_SECONDS,
            )
        except ValueError:
            raise
        except httpx.HTTPError as e:
            raise RuntimeError(f"AI prediction endpoint request failed: {e}")

    @staticmethod
    def _parse(content: str) -> dict[str, Any]:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start < 0 or end <= start:
            raise ValueError("No JSON found in model response")
        obj = json.loads(content[start:end])
        score = float(obj["predicted_score"])
        if not (0 <= score <= 100):
            raise ValueError(f"predicted_score out of range: {score}")
        trend = str(obj.get("trend", "stable")).strip().lower()
        if trend not in ("improving", "stable", "declining"):
            trend = "stable"
        confidence = obj.get("confidence")
        try:
            confidence = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and not (0 <= confidence <= 1):
            confidence = None
        return {
            "predicted_score": round(score, 1),
            "trend": trend,
            "confidence": round(confidence, 3) if confidence is not None else None,
            "reasoning": str(obj.get("reasoning", "")).strip(),
        }

    @staticmethod
    async def generate(
        db: Session,
        use_case_id: int,
        days: int,
        user: dict | None = None,
    ) -> dict:
        """Ask the model for a prediction, persist it, and return its dict."""
        from backend.config import get_settings

        uc = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if not uc:
            raise ValueError(f"Use case {use_case_id} not found")
        # Part 13 WS5 (R5): predictions are AI-round only — refuse at the
        # creation seam (GenericAssessmentError → 422) so forecast reads on
        # generic rounds stay honest-empty.
        AssessmentService.assert_ai_round(db, uc)

        history = (
            db.query(ScoreHistory)
            .filter(ScoreHistory.use_case_id == use_case_id)
            .order_by(ScoreHistory.scored_at.asc())
            .all()
        )

        effective = effective_inference_settings(db)
        content = await AIPredictionService._call_model(
            AIPredictionService.SYSTEM_PROMPT,
            AIPredictionService._build_prompt(uc, history, days),
            overrides=effective,
        )
        try:
            parsed = AIPredictionService._parse(content)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            raise RuntimeError(f"AI prediction response could not be parsed: {e}")

        current = uc.overall_score
        prediction = AIPrediction(
            use_case_id=uc.id,
            customer_id=uc.customer_id,
            horizon_days=days,
            predicted_score=parsed["predicted_score"],
            score_change=round(parsed["predicted_score"] - current, 1) if current is not None else None,
            trend=parsed["trend"],
            confidence=parsed["confidence"],
            reasoning=parsed["reasoning"],
            # Record the model that actually produced this prediction —
            # the runtime-effective model (DB override when set), not the
            # raw .env default.
            model=effective.get("ai_model") or get_settings().ai_model,
            created_by=user.get("username") if user else None,
        )
        db.add(prediction)
        db.commit()
        db.refresh(prediction)
        return prediction.to_dict()

    @staticmethod
    def list_saved(
        db: Session,
        customer_id: int | None = None,
        customer_ids: list[int] | None = None,
    ) -> list[dict]:
        query = db.query(AIPrediction)
        if customer_id is not None:
            query = query.filter(AIPrediction.customer_id == customer_id)
        elif customer_ids is not None:
            query = query.filter(AIPrediction.customer_id.in_(customer_ids))
        rows = query.order_by(AIPrediction.created_at.desc(), AIPrediction.id.desc()).all()
        return [r.to_dict() for r in rows]
