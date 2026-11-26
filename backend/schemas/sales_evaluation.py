"""Sales evaluation Pydantic schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SalesEvaluationBase(BaseModel):
    """Base schema shared by all variants."""
    evaluation_name: str
    status: str = "draft"


class SalesEvaluationCreate(SalesEvaluationBase):
    """Schema for creating a sales evaluation.

``persona`` selects the audience context for persona-tailored
    sections (see backend/services/sales_personas.py — the centralized
    registry; GET /api/sales-evaluations/personas/ lists valid values).
    Omit for a generic (legacy) evaluation.
    """
    persona: str | None = None


class SalesEvaluationUpdate(BaseModel):
    """Schema for updating a sales evaluation."""
    evaluation_name: str | None = None
    status: str | None = None


class ReadinessDimensions(BaseModel):
    """Dimension scores from the scoring engine."""
    strategic_fit: float | None = None
    technical_feasibility: float | None = None
    financial_viability: float | None = None
    operational_readiness: float | None = None
    risk_tolerance: float | None = None
    resource_availability: float | None = None


class EnvironmentFactors(BaseModel):
    """Environment analysis factors."""
    software_completeness: float | None = None
    hardware_currency: float | None = None
    process_documentation: float | None = None
    vendor_diversity: float | None = None
    details: dict[str, Any] = {}


class GapItem(BaseModel):
    """A single gap in the gap analysis."""
    category: str
    severity: str  # high/medium/low
    description: str
    readiness_dimension: str | None = None
    environment_factor: str | None = None


class SalesEvaluationResponse(SalesEvaluationBase):
    """Full response schema for a sales evaluation."""
    id: int
    customer_id: int
    readiness_overall: float | None = None
    readiness_dimensions: dict[str, Any] | None = None
    environment_score: float | None = None
    environment_factors: dict[str, Any] | None = None
    growth_opportunities: list[dict[str, Any]] | None = None
    risk_factors: list[dict[str, Any]] | None = None
    sales_approach: dict[str, Any] | None = None
    gaps: list[dict[str, Any]] | None = None
    # persona-driven evaluations (nullable: legacy rows have None)
    persona: str | None = None
    source_context: dict[str, Any] | None = None
    persona_sections: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SalesPersona(BaseModel):
    """One entry of the centralized sales persona registry.

    The registry (backend/services/sales_personas.py) is the single source
    of truth; this schema is the API contract for the
    GET /api/sales-evaluations/personas/ endpoint.
    """
    id: str
    label: str
    description: str
    technical_depth: str
    business_framing: str
    risk_framing: str
    focus_dimensions: list[str]
    concerns: list[str]
    question_base: list[str]
    priority_angles: list[str]
    next_action_angles: list[str]


class SalesEvaluationPreviewRequest(BaseModel):
    """Pre-generation view request."""
    customer_id: int
    persona: str | None = None
