"""Persisted, model-generated organization-wide readiness insights."""

import asyncio
import hashlib
import json
import logging
import re
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.clients.ai_client import AIClient
from backend.models.use_case import Customer, ReadinessInsight, UseCase, get_session
from backend.services.config_service import effective_inference_settings
from backend.services.scoring import ScoringService

logger = logging.getLogger(__name__)
_in_flight: dict[int, bool] = {}
_in_flight_lock = threading.Lock()


class InsightService:
    """Business logic for readiness-insight caching and generation."""

    @staticmethod
    def _use_cases(db: Session, customer_id: int):
        return (
            db.query(UseCase)
            .filter(UseCase.customer_id == customer_id)
            .order_by(UseCase.id.asc())
            .all()
        )

    @staticmethod
    def data_fingerprint(db: Session, customer_id: int) -> str:
        data = [
            {
                "id": uc.id,
                "status": uc.status,
                "overall_score": uc.overall_score,
                "department": uc.department,
            }
            for uc in sorted(InsightService._use_cases(db, customer_id), key=lambda item: item.id)
        ]
        encoded = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def scope_state(db: Session, customer_id: int) -> dict:
        use_cases = InsightService._use_cases(db, customer_id)
        total = len(use_cases)
        included = sum(
            uc.overall_score is not None and uc.status == "completed" for uc in use_cases
        )
        unscored = sum(uc.overall_score is None for uc in use_cases)
        not_completed = sum(uc.status != "completed" for uc in use_cases)
        missing_count = sum(
            uc.overall_score is None or uc.status != "completed" for uc in use_cases
        )
        return {
            "total": total,
            "included": included,
            "unscored": unscored,
            "not_completed": not_completed,
            "missing_count": missing_count,
            "ready": included >= 1,
            "all_scored": total > 0 and unscored == 0,
            "all_completed": total > 0 and not_completed == 0,
        }

    @staticmethod
    def build_context(db: Session, customer_id: int) -> dict:
        use_cases = InsightService._use_cases(db, customer_id)
        included = [
            uc for uc in use_cases
            if uc.overall_score is not None and uc.status == "completed"
        ]
        missing = [
            uc for uc in use_cases
            if uc.overall_score is None or uc.status != "completed"
        ]

        dimension_values: dict[str, list] = {}
        for uc in included:
            for name, value in ScoringService.extract_dimension_scores(uc.scores).items():
                dimension_values.setdefault(name, []).append(float(value))
        dimension_averages = [
            {"name": name, "average": round(sum(values) / len(values), 1)}
            for name, values in dimension_values.items()
        ]
        weakest = min(dimension_averages, key=lambda item: item["average"], default=None)
        strongest = max(dimension_averages, key=lambda item: item["average"], default=None)

        departments: dict[str, dict[str, float]] = {}
        for uc in included:
            name = uc.department or "Unassigned"
            item = departments.setdefault(name, {"count": 0, "score": 0.0, "impact": 0.0})
            item["count"] += 1
            item["score"] += float(uc.overall_score)
            item["impact"] += float(uc.estimated_savings or 0) + float(uc.estimated_revenue or 0)
        department_rows = [
            {
                "name": name,
                "use_case_count": int(values["count"]),
                "avg_score": round(values["score"] / values["count"], 1),
                "total_impact": round(values["impact"], 2),
            }
            for name, values in departments.items()
        ]
        department_rows.sort(key=lambda item: (-item["avg_score"], item["name"]))

        def summary(uc: UseCase) -> dict:
            return {
                "title": uc.title,
                "score": uc.overall_score,
                "department": uc.department or "Unassigned",
            }

        by_highest = sorted(included, key=lambda uc: (-float(uc.overall_score), uc.id))
        by_lowest = sorted(included, key=lambda uc: (float(uc.overall_score), uc.id))
        scores = [float(uc.overall_score) for uc in included]
        return {
            "total_use_cases": len(use_cases),
            "included_count": len(included),
            "missing_count": len(missing),
            "missing_reasons": {
                "unscored": sum(uc.overall_score is None for uc in use_cases),
                "not_completed": sum(uc.status != "completed" for uc in use_cases),
            },
            "missing_titles": [uc.title for uc in missing],
            "average_score": round(sum(scores) / len(scores), 1) if scores else None,
            "weakest_dimension": weakest,
            "strongest_dimension": strongest,
            "departments": department_rows,
            "top_use_cases": [summary(uc) for uc in by_highest[:5]],
            "lowest_use_cases": [summary(uc) for uc in by_lowest[:5]],
            "total_impact": round(sum(
                float(uc.estimated_savings or 0) + float(uc.estimated_revenue or 0)
                for uc in included
            ), 2),
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @staticmethod
    def get_cached(db: Session, customer_id: int) -> dict | None:
        row = db.query(ReadinessInsight).filter(
            ReadinessInsight.customer_id == customer_id
        ).first()
        if row is None:
            return None
        result = row.to_dict()
        result["stale"] = row.data_fingerprint != InsightService.data_fingerprint(db, customer_id)
        result["state"] = InsightService.scope_state(db, customer_id)
        return result

    @staticmethod
    def _parse_response(text: str) -> dict:
        try:
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("Model response did not contain a JSON object")
            obj = json.loads(cleaned[start:end + 1])
            summary = obj.get("summary")
            if not isinstance(summary, str) or not summary.strip():
                raise ValueError("Model response missing non-empty 'summary'")

            output = {"summary": summary.strip()[:600]}
            for field, maximum in (("strengths", 4), ("weaknesses", 4), ("priorities", 5)):
                values = obj.get(field)
                if not isinstance(values, list) or not 1 <= len(values) <= maximum:
                    raise ValueError(f"Model response '{field}' must contain 1-{maximum} items")
                if any(not isinstance(value, str) or not value.strip() for value in values):
                    raise ValueError(f"Model response '{field}' contains an invalid item")
                output[field] = [value.strip()[:300] for value in values]
            return output
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(str(exc)) from exc

    @staticmethod
    async def generate(db: Session, customer_id: int, generated_by: str = "system") -> dict:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer is None:
            raise ValueError(f"Customer {customer_id} not found")
        state = InsightService.scope_state(db, customer_id)
        if not state["ready"]:
            raise ValueError(
                f"No completed, scored use cases for customer {customer_id} — complete scoring first"
            )

        context = InsightService.build_context(db, customer_id)
        missing_count = context["missing_count"]
        total = context["total_use_cases"]
        titles = context["missing_titles"]
        if missing_count:
            missing_sentence = (
                f"IMPORTANT: {missing_count} of {total} use cases are unscored or not completed "
                f"and are EXCLUDED from this analysis: {', '.join(titles)}. Reflect that exclusion "
                "in the summary (state how many use cases remain unscored or incomplete) and base "
                "the insight only on the included use cases."
            )
        else:
            missing_sentence = "All use cases in the portfolio are scored and completed."

        system_prompt = (
            "You are an AI adoption analyst for enterprise organizations. You synthesize "
            "organization-wide AI readiness from scored use case data. Respond with ONLY valid "
            "JSON — no commentary, no markdown fences."
        )
        user_prompt = (
            f"Customer/organization: {customer.name}\n\nAnalyze the following AI readiness data "
            f"for this ENTIRE organization (all departments and use cases). Data:\n"
            f"{json.dumps(context, indent=2)}\n\n{missing_sentence}\n\n"
            "Produce an organization-wide readiness insight reflecting the whole organization and "
            "its use case portfolio. Base every claim only on the data provided — do not invent use "
            "cases, departments, scores, or figures.\nRespond with ONLY valid JSON in this format: "
            '{"summary": "<2-3 sentences about the organization\'s overall AI readiness>", '
            '"strengths": ["<1-4 concrete strengths grounded in the data>"], '
            '"weaknesses": ["<1-4 concrete weaknesses; name the weakest dimension and its gap vs '
            'the 70 target when present>"], "priorities": ["<3-5 specific, actionable '
            'organization-level priorities>"]}'
        )
        settings = effective_inference_settings(db)
        try:
            text = await AIClient(settings).complete(system_prompt, user_prompt, max_tokens=900)
            model_fields = InsightService._parse_response(text)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        payload = {
            **model_fields,
            "context": context,
            "missing_note": (
                f"{missing_count} of {total} use cases (unscored or not completed) are excluded "
                f"from this analysis: {', '.join(titles)}."
                if missing_count else None
            ),
            "model_used": True,
        }
        fingerprint = InsightService.data_fingerprint(db, customer_id)
        row = db.query(ReadinessInsight).filter(
            ReadinessInsight.customer_id == customer_id
        ).first()
        if row is None:
            row = ReadinessInsight(customer_id=customer_id, customer_name=customer.name)
            db.add(row)
        row.customer_name = customer.name
        row.insight_data = payload
        row.data_fingerprint = fingerprint
        row.model = settings.get("ai_model")
        row.generated_by = generated_by
        row.status = "completed"
        row.generated_at = datetime.utcnow()
        db.commit()
        db.refresh(row)
        result = row.to_dict()
        result.update(stale=False, state=InsightService.scope_state(db, customer_id))
        return result

    @staticmethod
    def generate_if_ready(
        db: Session,
        customer_id: int,
        condition: str,
        generated_by: str = "system",
    ) -> dict | None:
        state = InsightService.scope_state(db, customer_id)
        should_run = (
            state["all_scored"] and state["all_completed"] and state["ready"]
            if condition == "full" else state["ready"] if condition == "bulk" else False
        )
        if not should_run:
            return None
        fingerprint = InsightService.data_fingerprint(db, customer_id)
        row = db.query(ReadinessInsight).filter(
            ReadinessInsight.customer_id == customer_id
        ).first()
        if row and row.status == "completed" and row.data_fingerprint == fingerprint:
            return None
        return asyncio.run(InsightService.generate(db, customer_id, generated_by))

    @staticmethod
    def trigger_async(customer_id: int, condition: str, generated_by: str = "system") -> None:
        with _in_flight_lock:
            if _in_flight.get(customer_id):
                return
            _in_flight[customer_id] = True

        def worker() -> None:
            session = None
            try:
                session = get_session()
                InsightService.generate_if_ready(
                    session, customer_id, condition, generated_by=generated_by
                )
            except Exception as exc:
                logger.warning(
                    "Readiness insight auto-generation failed for customer_id=%s: %s",
                    customer_id,
                    exc,
                )
            finally:
                if session is not None:
                    session.close()
                with _in_flight_lock:
                    _in_flight.pop(customer_id, None)

        threading.Thread(target=worker, daemon=True).start()
