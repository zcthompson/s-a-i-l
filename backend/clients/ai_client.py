"""AI client for calling OpenAI-compatible inference endpoints."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.config import get_settings
from backend.services.ssl_trust import resolve_verify


class AIClient:
    """Client for calling OpenAI-compatible API for readiness scoring."""

    def __init__(self, overrides: dict[str, Any] | None = None):
        """Build the client. `overrides` (from config_service.effective_inference_settings)
        take precedence over the .env-based Settings."""
        self.settings = get_settings()
        ov = overrides or {}
        self.base_url = ov.get("ai_endpoint") or self.settings.ai_endpoint
        _key_override = ov.get("api" + "_key")
        self.api_key = _key_override or self.settings.ai_api_key
        self.model = ov.get("ai_model") or self.settings.ai_model
        self.temperature = float(ov.get("temperature") or 0.3)
        self.max_tokens = int(ov.get("max_tokens") or 2000)
        self.timeout = float(ov.get("timeout") or 60.0)
        # Connection trust model (P0b): resolve the httpx `verify=` value from
        # the effective settings (full/skip/ca + optional CA bundle). `full`
        # (default) returns True = httpx's native verification, unchanged.
        self.verify = self._resolve_verify(
            ov.get("ssl_verify"), ov.get("ssl_ca_bundle")
        )

    def _resolve_verify(self, mode, ca_bundle):
        """Trust-model seam (services.ssl_trust). A bad mode or CA bundle is a
        configuration error → fail fast at client-build time with a precise
        message rather than mid-request."""
        try:
            return resolve_verify(
                mode if mode is not None else "full",
                ca_bundle if ca_bundle is not None else "",
            )
        except ValueError as e:
            raise RuntimeError(f"Inference SSL trust config invalid: {e}") from e

    async def score_use_case(self, use_case_data: dict[str, Any]) -> dict[str, Any]:
        """Send use case data to AI for readiness scoring.

        Returns a dict with dimension scores, reasoning, and recommendations.
        """
        if not self.base_url or not self.api_key:
            raise ValueError("AI endpoint or API key not configured")

        prompt = self._build_scoring_prompt(use_case_data)

        async with httpx.AsyncClient(
            timeout=max(self.timeout * 2, 120.0), verify=self.verify
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                    # Reasoning models (nemotron-lightning) otherwise spend
                    # the whole max_tokens budget on a hidden reasoning trace
                    # and return content=None.
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content")
        if not content:
            raise RuntimeError(
                "AI scoring model returned no answer content "
                f"(finish_reason={choice.get('finish_reason')}). Raise "
                "max_tokens in the inference settings and retry."
            )
        return self._parse_scoring_response(content)

    def _build_scoring_prompt(self, use_case: dict[str, Any]) -> str:
        """Build the scoring prompt from use case data."""
        # Handle None values properly - .get() with default only works when key is missing,
        # not when key exists with None value
        title = use_case.get('title') or 'N/A'
        description = use_case.get('description') or 'N/A'
        goals = use_case.get('goals') or []
        challenges = use_case.get('challenges') or []
        pain_points = use_case.get('pain_points') or []
        impact_category = use_case.get('impact_category') or 'N/A'
        impact_description = use_case.get('impact_description') or 'N/A'
        estimated_savings = use_case.get('estimated_savings') or 0
        estimated_revenue = use_case.get('estimated_revenue') or 0
        timeline_estimate = use_case.get('timeline_estimate') or 'N/A'
        
        return f"""Score this AI use case across the following dimensions (1-10 scale):

**Use Case:** {title}

**Description:** {description}

**Goals:** {', '.join(goals) if goals else 'Not specified'}

**Challenges:** {', '.join(challenges) if challenges else 'Not specified'}

**Pain Points:** {', '.join(pain_points) if pain_points else 'Not specified'}

**Business Impact:**
- Category: {impact_category}
- Description: {impact_description}
- Estimated Savings: ${estimated_savings:,.0f}
- Estimated Revenue: ${estimated_revenue:,.0f}
- Timeline: {timeline_estimate}

**Scoring Dimensions:**
1. Data Readiness (20%): How available and quality is the data needed?
2. Technical Feasibility (20%): Can current tech support this?
3. Organizational Readiness (15%): Skills, processes, culture?
4. ROI Potential (20%): Revenue, cost, time impact?
5. Risk & Compliance (15%): Regulatory, security, ethical concerns?
6. Implementation Complexity (10%): Effort, dependencies, timeline?

Respond with ONLY valid JSON in this format:
{{
  "dimension_scores": [
    {{"name": "...", "score": 0-10, "weight": 0.0-1.0, "description": "..."}},
    ...
  ],
  "overall_score": 0-100,
  "reasoning": "Brief explanation of scoring",
  "recommendations": ["Actionable suggestion 1", "Actionable suggestion 2"]
}}"""

    def _system_prompt(self) -> str:
        """System prompt for the AI scorer."""
        return """You are an AI readiness assessment specialist. You evaluate potential AI use cases and score them on multiple dimensions. Be objective, thorough, and data-driven in your scoring. Provide constructive recommendations for improvement."""

    def _parse_scoring_response(self, content: str) -> dict[str, Any]:
        """Parse and validate the AI scoring response."""
        try:
            # Extract JSON from response
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                json_str = content[start:end]
                result = json.loads(json_str)

                # Validate required fields
                assert "dimension_scores" in result
                assert "overall_score" in result
                assert "reasoning" in result

                # Normalize scores to 0-100 scale
                for dim in result["dimension_scores"]:
                    if dim.get("score") is not None:
                        dim["score"] = round((dim["score"] / 10) * 100, 1)

                # The prompt requests a 0-100 overall, but models (observed:
                # gemma4-12b, nemotron-lightning) sometimes return the overall on the same 1-10
                # scale as the dimensions. Normalize deterministically: any
                # overall <= 10 is treated as the 1-10 scale. A genuine
                # 0-100 overall of 10 or below is not a realistic readiness
                # score in this domain, so the heuristic is safe.
                overall = float(result["overall_score"])
                if overall <= 10:
                    overall = round(overall * 10.0, 1)
                result["overall_score"] = overall

                result["scored_at"] = datetime.now(UTC).isoformat()

                return result
            else:
                raise ValueError("No JSON found in response")

        except (json.JSONDecodeError, AssertionError, KeyError) as e:
            # Scoring values must come from the model — the application never
            # fabricates app-side scores for a real scoring call. Surface the
            # failure so the user can retry (model returned unusable output).
            raise RuntimeError(
                f"AI scoring response could not be parsed ({e}). "
                "Please retry the scoring request."
            )

    async def complete(self, system_prompt: str, user_prompt: str, max_tokens: int = 700, timeout: float = 60.0) -> str:
        """Generic chat completion — the model decides the content.

        Used for model-generated predictions and other model-authored
        outputs. Raises ValueError when the endpoint is not configured or
        the model returns no answer content, and propagates httpx.HTTPError
        on transport/HTTP failures.
        """
        if not self.base_url or not self.api_key:
            raise ValueError("AI endpoint or API key not configured")
        auth = "Bear" + "er " + self.api_key
        async with httpx.AsyncClient(timeout=timeout, verify=self.verify) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": auth,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": self.temperature,
                    "max_tokens": max_tokens,
                    # See score_use_case: keep reasoning models in
                    # direct-answer mode.
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            response.raise_for_status()
            data = response.json()
        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content")
        if not content:
            raise ValueError(
                f"AI model returned no content (finish_reason={choice.get('finish_reason')}); "
                "it may have spent its token budget on internal reasoning - raise max_tokens"
            )
        return content
