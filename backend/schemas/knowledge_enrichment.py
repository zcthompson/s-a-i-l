"""Pydantic schemas for LLM knowledge enrichment.

Item 13: the LLM must return STRUCTURED intelligence, never prose that
application logic parses. ``KnowledgeEnrichmentResponse`` is the typed
contract; every item schema carries the provenance fields and
validation rejects out-of-vocabulary values instead of silently
accepting them. Items the LLM did not populate stay NULL/empty —
unknown information remains unknown.
"""


from pydantic import BaseModel, Field, field_validator

from backend.models.customer_knowledge import (
    ITEM_KINDS,
    KNOWLEDGE_CATEGORIES,
    PROVENANCE_TYPES,
)
from backend.models.customer_technology import (
    BUSINESS_CRITICALITIES,
    DEPLOYMENT_MODELS,
    LIFECYCLE_STATES,
    SUPPORT_STATES,
)
from backend.models.customer_technology import (
    CATEGORIES as TECH_CATEGORIES,
)
from backend.models.technology_dependency import DEPENDENCY_TYPES


class EnrichedItem(BaseModel):
    """Common fields of one extracted intelligence item (plan item 13)."""

    name: str = Field(..., max_length=500, description="Short identifier name")
    description: str | None = None
    provenance: str = Field(default="derived", description="explicit|derived|suggested")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: str | None = None  # supporting quote/text from the document
    source_reference: str | None = Field(default=None, max_length=500)  # section/page ref

    @field_validator("provenance")
    @classmethod
    def _valid_provenance(cls, v: str) -> str:
        if v not in PROVENANCE_TYPES:
            raise ValueError(f"provenance must be one of {PROVENANCE_TYPES}, got {v!r}")
        return v

    @field_validator("name")
    @classmethod
    def _name_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name is required")
        return v


class TechnologyItem(EnrichedItem):
    """A technology the customer runs (applied to the Technology Inventory)."""

    vendor: str | None = None
    category: str | None = None  # one of the technology inventory categories
    version_edition: str | None = None
    deployment_model: str | None = None
    lifecycle_state: str | None = None
    support_state: str | None = None
    business_criticality: str | None = None
    footprint: str | None = None
    purpose: str | None = None

    @field_validator("category")
    @classmethod
    def _valid_tech_category(cls, v):
        return v if v in TECH_CATEGORIES else None

    @field_validator("deployment_model")
    @classmethod
    def _valid_deployment(cls, v):
        return v if v in DEPLOYMENT_MODELS else None

    @field_validator("lifecycle_state")
    @classmethod
    def _valid_lifecycle(cls, v):
        return v if v in LIFECYCLE_STATES else None

    @field_validator("support_state")
    @classmethod
    def _valid_support(cls, v):
        return v if v in SUPPORT_STATES else None

    @field_validator("business_criticality")
    @classmethod
    def _valid_criticality(cls, v):
        return v if v in BUSINESS_CRITICALITIES else None


class TechnologyDependencyItem(EnrichedItem):
    """A directional technology relationship (applied to Technology Dependency).

    ``name`` is "<source> <relationship> <target>" for traceability.
    """

    source_technology: str = Field(..., max_length=255)
    target_technology: str = Field(..., max_length=255)
    relationship_type: str = Field(..., description="one of the dependency types")

    @field_validator("relationship_type")
    @classmethod
    def _valid_dependency_type(cls, v: str) -> str:
        if v not in DEPENDENCY_TYPES:
            raise ValueError(
                f"relationship_type must be one of {DEPENDENCY_TYPES}, got {v!r}"
            )
        return v


class UseCaseItem(EnrichedItem):
    """A use case the document describes or implies (applied to Use Cases)."""

    goals: list[str] = Field(default_factory=list)
    business_value: str | None = None
    current_process: str | None = None
    desired_outcome: str | None = None


class DocumentCategorySuggestion(BaseModel):
    """LLM category suggestion (item 1): used ONLY when the user did not
    select a category — the user's choice is always authoritative."""

    category: str | None = None
    reasoning: str | None = None

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v):
        return v if v in KNOWLEDGE_CATEGORIES else None


class KnowledgeEnrichmentResponse(BaseModel):
    """Full structured enrichment result (plan item 13 shape)."""

    document_category: DocumentCategorySuggestion = Field(
        default_factory=DocumentCategorySuggestion
    )
    customer_facts: list[EnrichedItem] = Field(default_factory=list)
    technologies: list[TechnologyItem] = Field(default_factory=list)
    technology_dependencies: list[TechnologyDependencyItem] = Field(
        default_factory=list
    )
    business_objectives: list[EnrichedItem] = Field(default_factory=list)
    business_challenges: list[EnrichedItem] = Field(default_factory=list)
    projects: list[EnrichedItem] = Field(default_factory=list)
    stakeholders: list[EnrichedItem] = Field(default_factory=list)
    requirements: list[EnrichedItem] = Field(default_factory=list)
    use_cases: list[UseCaseItem] = Field(default_factory=list)
    opportunities: list[EnrichedItem] = Field(default_factory=list)
    risks: list[EnrichedItem] = Field(default_factory=list)
    decisions: list[EnrichedItem] = Field(default_factory=list)
    follow_up_items: list[EnrichedItem] = Field(default_factory=list)

    # ── Normalization helpers (used by the enrichment service) ───────

    def all_items(self) -> list[tuple]:
        """(kind, item) pairs in a deterministic order — the service
        persists one CustomerKnowledgeItem row per pair."""
        pairs: list[tuple] = []
        for kind in ITEM_KINDS:
            for item in getattr(self, _field_for_kind(kind), []) or []:
                pairs.append((kind, item))
        return pairs


def _field_for_kind(kind: str) -> str:
    """Map an ITEM_KINDS value to its response field name."""
    return {
        "customer_fact": "customer_facts",
        "business_objective": "business_objectives",
        "business_challenge": "business_challenges",
        "project": "projects",
        "stakeholder": "stakeholders",
        "requirement": "requirements",
        "decision": "decisions",
        "follow_up_item": "follow_up_items",
        "risk": "risks",
        "technology": "technologies",
        "technology_dependency": "technology_dependencies",
        "use_case": "use_cases",
        "opportunity": "opportunities",
    }[kind]


def normalize_enrichment_payload(payload: dict) -> "KnowledgeEnrichmentResponse":
    """Validate a raw model-JSON dict into the typed response.

    Tolerates (and drops) unknown top-level keys and per-item fields the
    model invented; raises ValueError on structurally invalid payloads so
    the enrichment service can mark the run FAILED (item 16) rather than
    silently storing unvalidated data.
    """
    if not isinstance(payload, dict):
        raise ValueError("enrichment payload must be a JSON object")
    known = set(KnowledgeEnrichmentResponse.model_fields)
    clean = {k: v for k, v in payload.items() if k in known}
    # Per-item cleanup: strip None-valued unknown extras is done by the
    # per-field validators; here we normalize item lists to lists of dicts.
    for key in known - {"document_category"}:
        if key in clean and isinstance(clean[key], list):
            clean[key] = [i for i in clean[key] if isinstance(i, dict)]
    if "document_category" in clean and clean["document_category"] is not None \
            and not isinstance(clean["document_category"], dict):
        clean.pop("document_category")
    return KnowledgeEnrichmentResponse(**clean)
