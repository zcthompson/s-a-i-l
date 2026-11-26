"""Scoring service — orchestrates AI scoring and business logic.

Enforces role-based access: auditors cannot score use cases; scoring
requires CAP_EDIT on the use case's customer (central policy).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.clients.ai_client import AIClient
from backend.models.collaboration import DimensionConfig, ScoreHistory
from backend.models.use_case import UseCase
from backend.services import sales_access
from backend.services.assessment_service import AssessmentService
from backend.services.config_service import effective_inference_settings
from backend.services.use_case_service import UNASSIGNED_ADMIN_ONLY, UseCaseService

SCORING_EDIT_REQUIRED = "scoring requires edit access to this customer"


class ScoringService:
    """Business logic for use case scoring."""

    # Dimension definitions with weights
    DIMENSIONS = [
        {"name": "Data Readiness", "weight": 0.20},
        {"name": "Technical Feasibility", "weight": 0.20},
        {"name": "Organizational Readiness", "weight": 0.15},
        {"name": "ROI Potential", "weight": 0.20},
        {"name": "Risk & Compliance", "weight": 0.15},
        {"name": "Implementation Complexity", "weight": 0.10},
    ]

    # Canonical order for display (charts, tables, drill-down)
    DIMENSIONS_NAME_ORDER = [d["name"] for d in DIMENSIONS]

    # Canonical dimension lookup keyed by normalized (lowercase, alphanumeric-only)
    # name. Tolerates display names ("Risk & Compliance"), snake_case keys
    # ("risk_compliance"), and model paraphrases ("risk and compliance").
    _DIMENSION_BY_NORM: dict[str, str] = {
        "".join(ch for ch in d["name"].lower() if ch.isalnum()): d["name"]
        for d in DIMENSIONS
    }

    # snake_case keys used by seeded / legacy flat-dict score payloads
    _FLAT_KEY_BY_NAME: dict[str, str] = {
        d["name"]: d["name"].lower().replace(" & ", "_").replace(" ", "_")
        for d in DIMENSIONS
    }

    @staticmethod
    def extract_dimension_scores(scores) -> dict[str, float]:
        """Normalize a stored ``UseCase.scores`` payload to dimension scores.

        Returns ``{canonical dimension name: score (0-100)}`` for every
        dimension present. Accepts both payload shapes in circulation:

        - ``{"dimension_scores": [{"name"|"dimension"|"key": ..., "score": ...}, ...]}``
          (live AI scoring and approved score-history payloads);
        - ``{"data_readiness": 80, "technical_feasibility": 78, ...}``
          (seeded / legacy payloads keyed by snake_case dimension keys).

        Returns ``{}`` when no usable dimension data is present.
        """
        if not isinstance(scores, dict):
            return {}
        out: dict[str, float] = {}
        dim_list = scores.get("dimension_scores")
        if isinstance(dim_list, list):
            for dim in dim_list:
                if not isinstance(dim, dict) or dim.get("score") is None:
                    continue
                raw = dim.get("name") or dim.get("dimension") or dim.get("key") or ""
                norm = "".join(ch for ch in str(raw).lower() if ch.isalnum())
                canonical = (
                    ScoringService._DIMENSION_BY_NORM.get(norm)
                    or ScoringService._DIMENSION_BY_NORM.get(norm.replace("and", ""))
                )
                if canonical is None:
                    continue
                try:
                    out[canonical] = float(dim["score"])
                except (TypeError, ValueError):
                    continue
        for name, flat_key in ScoringService._FLAT_KEY_BY_NAME.items():
            if name in out:
                continue
            value = scores.get(flat_key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[name] = float(value)
        return out

    @staticmethod
    def assert_scoring_access(db: Session, user: dict | None, use_case: UseCase) -> None:
        """Enforce authentication and customer-scoped access for scoring.

        Scoring overwrites scores and broadcasts notifications, so it is
        treated as a write operation:
        - anonymous callers (user is None) are rejected;
        - global admins (is_admin) may score any use case;
        - auditors (global role, or junction role 'auditor') are rejected;
        - non-admins need CAP_EDIT on the use case's customer (central
          policy). Unassigned (customer-less) use cases can only be scored
          by admins.

        Raises ValueError on any violation.
        """
        if user is None:
            raise ValueError("Authentication required to score use cases")

        if user.get("is_admin"):
            return

        if user.get("role") == "auditor":
            raise ValueError("Auditors cannot score use cases")

        customer_id = use_case.customer_id
        if customer_id is None:
            raise ValueError(UNASSIGNED_ADMIN_ONLY)

        # Central write basis: CAP_EDIT on the customer.
        if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
            raise ValueError(SCORING_EDIT_REQUIRED)

        # Archived assessment rounds are read-only (export only)
        from backend.services.assessment_service import AssessmentService
        AssessmentService.assert_not_archived(db, use_case)

    @staticmethod
    async def score_use_case(
        db: Session,
        use_case_id: int,
        timeout_seconds: float = 60.0,
        user: dict | None = None,
    ) -> dict[str, Any]:
        """Score a use case via AI and persist results.

        Returns the scoring result and updated use case.
        Broadcasts a notification to all users with junction access
        to the use case's customer on success.

        Raises ValueError when the user is unauthenticated, lacks
        junction access, is an auditor, or the use case is unassigned
        to a customer.
        Raises TimeoutError if the AI service takes longer than timeout_seconds.
        """
        import asyncio
        use_case = db.query(UseCase).filter(UseCase.id == use_case_id).first()
        if not use_case:
            raise ValueError(f"Use case {use_case_id} not found")

        # Enforce authentication and junction access (see assert_scoring_access)
        ScoringService.assert_scoring_access(db, user, use_case)

        # AI scoring is AI-round only — generic-round use
        # cases are refused at the shared seam (covers the scoring routes,
        # bulk score-multiple, and any future caller). Legacy use cases with
        # no round resolve to 'ai' and pass.
        AssessmentService.assert_ai_round(db, use_case)

        # Prepare data for AI scoring
        use_case_data = use_case.to_dict()

        # Call AI client with timeout (DB inference overrides take precedence over .env)
        effective = effective_inference_settings(db)
        client = AIClient(effective)
        timeout_seconds = float(effective.get("timeout") or timeout_seconds)
        try:
            scores = await asyncio.wait_for(
                client.score_use_case(use_case_data), timeout=timeout_seconds
            )
        except TimeoutError:
            raise TimeoutError(
                f"AI scoring timed out after {timeout_seconds}s. The AI endpoint may be slow or "
                "unavailable. Try again later or check the SAIL_AI_ENDPOINT "
                "configuration."
            )

        # Persist scores
        use_case.scores = scores
        use_case.overall_score = scores["overall_score"]
        # Convert ISO string to datetime object for SQLite compatibility
        scored_at_str = scores.get("scored_at")
        if scored_at_str:
            from datetime import datetime

            use_case.scored_at = datetime.fromisoformat(
                scored_at_str.replace("Z", "+00:00")
            )

        # Create structured score history entry for audit trail
        history_entry = ScoreHistory(
            use_case_id=use_case_id,
            score=scores["overall_score"],
            scored_at=use_case.scored_at,
            scored_by=user.get("username", "anonymous") if user else "anonymous",
            is_manual=0,
            status="approved",
            dimension_scores=scores.get("dimension_scores", []),
        )
        db.add(history_entry)

        db.commit()
        db.refresh(use_case)

        # Broadcast customer-level notification on successful scoring
        if use_case.customer_id:
            from backend.services.collaboration_service import CollaborationService

            message = (
                f"Use case '{use_case.title}' has been scored with an overall "
                f"readiness score of {scores['overall_score']:.0f}/100."
            )
            CollaborationService.broadcast_to_customer(
                db, use_case.customer_id, "scoring", message
            )

            from backend.services.insight_service import InsightService
            InsightService.trigger_async(
                use_case.customer_id,
                "full",
                generated_by=(user.get("username") or "system") if user else "system",
            )

        return {
            "use_case": use_case.to_dict(),
            "scores": scores,
        }

    @staticmethod
    def score_use_case_sync(db: Session, use_case_id: int, user: dict | None = None) -> dict:
        """Synchronous wrapper for score_use_case that can be called from sync routes."""
        import asyncio
        loop = None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(ScoringService.score_use_case(db, use_case_id, user=user))
        finally:
            if loop and loop is not asyncio.get_event_loop():
                loop.close()

    @staticmethod
    def calculate_weighted_average(dimension_scores: list) -> float:
        """Calculate weighted average score from dimension scores."""
        total_weight = sum(dim["weight"] for dim in dimension_scores)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(dim["score"] * dim["weight"] for dim in dimension_scores)
        return round(weighted_sum / total_weight, 1)

    # ── Dimension config + score-history management (from routes/scoring.py) ──

    @staticmethod
    def get_active_dimension_configs(db: Session, version: str) -> list[dict]:
        """Active dimension config entries for a version, serialized."""
        configs = db.query(DimensionConfig).filter(
            DimensionConfig.version == version,
            DimensionConfig.is_active == 1,
        ).all()
        return [c.to_dict() for c in configs]

    @staticmethod
    def dimension_version_exists(db: Session, version: str) -> bool:
        """True if any dimension config rows exist for the version."""
        return (
            db.query(DimensionConfig)
            .filter(DimensionConfig.version == version)
            .count() > 0
        )

    @staticmethod
    def create_dimension_config(
        db: Session, version: str, name: str, weight: float
    ) -> DimensionConfig:
        db_config = DimensionConfig(
            version=version, name=name, weight=weight, is_active=1
        )
        db.add(db_config)
        db.commit()
        db.refresh(db_config)
        return db_config

    @staticmethod
    def get_score_history(db: Session, use_case_id: int) -> list[dict]:
        """Full score history for a use case, newest first."""
        history = db.query(ScoreHistory).filter(
            ScoreHistory.use_case_id == use_case_id
        ).order_by(ScoreHistory.scored_at.desc()).all()
        return [h.to_dict() for h in history]

    @staticmethod
    def get_score_history_entry(db: Session, history_id: int) -> ScoreHistory | None:
        return db.query(ScoreHistory).filter(ScoreHistory.id == history_id).first()

    @staticmethod
    def approve_history(db: Session, history: ScoreHistory) -> UseCase | None:
        """Approve a draft score and apply it to its use case."""
        history.status = "approved"
        use_case = db.query(UseCase).filter(UseCase.id == history.use_case_id).first()
        if use_case:
            if history.dimension_scores:
                use_case.scores = {"dimension_scores": history.dimension_scores}
            use_case.overall_score = history.score
            use_case.scored_at = history.scored_at
            use_case.scores["overall_score"] = history.score
            use_case.scores["scored_at"] = history.scored_at.isoformat() if history.scored_at else None
            use_case.scores["scored_by"] = history.scored_by
            use_case.scores["reasoning"] = history.reasoning
        db.commit()
        db.refresh(history)
        return use_case

    @staticmethod
    def reject_history(db: Session, history: ScoreHistory) -> None:
        history.status = "rejected"
        db.commit()
        db.refresh(history)

    @staticmethod
    def manual_score(
        db: Session,
        use_case_id: int,
        scores: dict[str, Any],
        overall_score: float,
        user: dict,
    ) -> UseCase | None:
        """Persist a manual score override (bypasses AI).

        Enforces the same access rules as AI scoring (admin, or CAP_EDIT
        on the use case's customer). Returns the updated
        use case, or None when it does not exist; raises ValueError on
        access denial.
        """
        use_case = UseCaseService.get_by_id(db, use_case_id)
        if not use_case:
            return None

        customer_id = use_case.customer_id
        # R2: a customer-less use case is admin-only (ValueError → route 403)
        if customer_id is None and not user.get("is_admin"):
            raise ValueError(UNASSIGNED_ADMIN_ONLY)
        if customer_id is not None and not user.get("is_admin"):
            if not sales_access.can(user, db, sales_access.CAP_EDIT, customer_id):
                raise ValueError("No write access to this customer")

        # Persist manual scores
        use_case.scores = scores
        use_case.overall_score = overall_score
        use_case.scored_at = datetime.now(UTC)

        # Create structured score history entry for audit trail
        history_entry = ScoreHistory(
            use_case_id=use_case_id,
            score=overall_score,
            scored_at=use_case.scored_at or datetime.now(UTC),
            scored_by=user.get("username", "anonymous"),
            is_manual=1,
            status="approved",
            dimension_scores=scores.get("dimension_scores"),
            reasoning=f"Manual override by {user.get('username', 'anonymous')}",
        )
        db.add(history_entry)

        db.commit()
        db.refresh(use_case)
        if use_case.customer_id is not None:
            from backend.services.insight_service import InsightService
            InsightService.trigger_async(
                use_case.customer_id,
                "full",
                generated_by=(user.get("username") or "system") if user else "system",
            )
        return use_case

    @staticmethod
    def validate_scoring_response(scores: dict[str, Any] | None) -> dict[str, Any]:
        """Validate a scoring AI response payload.

        Checks score ranges, dimension completeness, and weight
        consistency. Returns {"is_valid", "errors", "warnings"} with
        None for empty lists (the ScoringValidationResponse contract).
        """
        if not scores:
            return {"is_valid": False, "errors": ["No scores provided"], "warnings": None}

        errors = []
        warnings = []

        # Check overall score
        if "overall_score" not in scores:
            errors.append("Missing 'overall_score' field")
        elif not isinstance(scores["overall_score"], (int, float)):
            errors.append("'overall_score' must be a number")
        elif not (0 <= scores["overall_score"] <= 100):
            errors.append("'overall_score' must be between 0 and 100")

        # Check dimension scores
        if "dimension_scores" not in scores:
            warnings.append("Missing 'dimension_scores' — manual override may be needed")
        else:
            dim_scores = scores["dimension_scores"]
            if not isinstance(dim_scores, list):
                errors.append("'dimension_scores' must be a list")
            else:
                total_weight = 0
                for dim in dim_scores:
                    if not all(k in dim for k in ["name", "score", "weight"]):
                        errors.append("Each dimension must have 'name', 'score', and 'weight'")
                    else:
                        if not (0 <= dim["score"] <= 100):
                            errors.append(f"Dimension '{dim['name']}' score must be between 0 and 100")
                        total_weight += dim.get("weight", 0)

                if abs(total_weight - 1.0) > 0.01:
                    warnings.append(f"Total dimension weight is {total_weight:.2f} (expected 1.0)")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors if errors else None,
            "warnings": warnings if warnings else None,
        }
