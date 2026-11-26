"""LLM knowledge enrichment service (CHANGELOG 0.1.2).

Two-stage pipeline over a READY knowledge document:

    Original File → Docling → Normalized Markdown          (stage 1, done)
                  → Application LLM → Structured Items     (stage 2, here)
                  → Applied to domain objects via services (stage 3, here)

Design constraints honored:

- The LLM is called through the existing configured inference
  abstraction (``AIClient.complete`` with the effective inference
  settings) — no hard-coded model/provider (item 17).
- The LLM must return STRUCTURED JSON (``KnowledgeEnrichmentResponse``);
  arbitrary prose is never parsed by application logic (item 13).
- Every extracted item is persisted as a ``CustomerKnowledgeItem``
  (durable evidence with provenance/confidence/evidence/source ref —
  item 6). High-value items are then APPLIED through the existing
  service layer (item 5): Technology Inventory, Technology Dependency,
  Sales Notes, Use Cases.
- Dedupe: before creating, the extraction is compared against existing
  customer knowledge; existing rows are strengthened/linked rather than
  duplicated (item 7). Reprocessing a document first removes its own
  previous items (item 15).
- Provenance mapping (items 6, 8): explicit → verified, derived →
  inferred, suggested → unverified. Suggested items are NOT auto-created
  as authoritative domain objects — they are stored as Proposed evidence
  (the knowledge item + a sales note of matching category).
- Failure isolation (item 16): enrichment failure marks
  ``enrichment_status=FAILED`` but NEVER touches the Docling
  ``processing_status`` — the normalized content stays available and
  enrichment can be retried without rerunning Docling.
- Customer isolation (charter §4): the enrichment job only reads the
  single knowledge record's customer; the route layer enforces
  CustomerUser authorization BEFORE dispatching (the worker only ever
  receives a record id from an already-authorized route).
"""

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.clients.ai_client import AIClient
from backend.models.customer_knowledge import (
    ENRICHMENT_ENRICHED,
    ENRICHMENT_ENRICHING,
    ENRICHMENT_SKIPPED,
    KNOWLEDGE_CATEGORIES,
    CustomerKnowledgeItem,
)
from backend.models.customer_knowledge import (
    CustomerKnowledge as CKModel,
)
from backend.schemas.knowledge_enrichment import (
    KnowledgeEnrichmentResponse,
    TechnologyDependencyItem,
    TechnologyItem,
    UseCaseItem,
    normalize_enrichment_payload,
)
from backend.services import (
    sales_note_service,
    technology_dependency_service,
    technology_inventory_service,
)
from backend.services.config_service import effective_inference_settings

logger = logging.getLogger(__name__)

# Provenance → domain verification state (item 6/8: suggested never
# becomes authoritative data; it is Proposed evidence).
_PROVENANCE_TO_VERIFICATION = {
    "explicit": "verified",
    "derived": "inferred",
    "suggested": "unverified",
}

# Enrichment prompt content cap — documents larger than this are
# truncated to the first N characters (head is the most knowledge-dense
# region for sales documents); the cap is generous and deterministic.
_CONTENT_MAX_CHARS = 60_000

# Category → extraction emphasis (item 9). The category guides the
# analysis without preventing other-category extraction.
_CATEGORY_FOCUS = {
    "technology_infrastructure": (
        "Prioritize: technologies, versions, vendors, architecture, "
        "infrastructure dependencies, lifecycle/EOL concerns, and "
        "modernization opportunities."
    ),
    "business_strategy_goals": (
        "Prioritize: business objectives, strategic priorities, KPIs, "
        "timelines, business challenges, and opportunities."
    ),
    "meeting_notes_customer_communications": (
        "Prioritize: decisions, stakeholders and their roles, "
        "commitments, pain points, stated requirements, next steps, and "
        "opportunities."
    ),
    "use_cases": (
        "Prioritize: business problem, current process, desired outcome, "
        "technical requirements, automation possibilities, dependencies, "
        "and business value."
    ),
    "assessments_discovery": (
        "Prioritize: findings, gaps, maturity observations, requirements, "
        "risks, recommendations, and potential use cases."
    ),
    "security_compliance": (
        "Prioritize: security requirements, compliance obligations, risk "
        "posture, and security-related opportunities."
    ),
    "business_challenges_pain_points": (
        "Prioritize: pain points, operational challenges, constraints, and "
        "the opportunities they create."
    ),
}

SYSTEM_PROMPT = (
    "You are a sales-intelligence analyst for S-A-I-L Solutions (S-A-I-L). "
    "You read ONE customer document and extract structured intelligence "
    "about that customer. You NEVER invent facts: if the document does not "
    "state or imply something, leave it out. Every item you return must "
    "carry a provenance type: 'explicit' (directly stated), 'derived' "
    "(reasonably inferred), or 'suggested' (a recommendation worth "
    "considering, not yet validated). Respond with ONLY valid JSON — no "
    "markdown fences, no commentary."
)


# ----------------------------------------------------------------------
# Prompt construction
# ----------------------------------------------------------------------


def _category_catalog() -> str:
    return "\n".join(f"- {c}" for c in KNOWLEDGE_CATEGORIES)


def build_enrichment_prompt(
    filename: str,
    normalized_content: str,
    knowledge_category: str | None,
) -> str:
    """User prompt for the enrichment call (category-aware, item 9)."""
    content = normalized_content or ""
    truncated = len(content) > _CONTENT_MAX_CHARS
    if truncated:
        content = content[:_CONTENT_MAX_CHARS] + "\n\n[content truncated for analysis]"
    focus = _CATEGORY_FOCUS.get(knowledge_category or "", "")
    category_line = (
        f"The document was classified into the knowledge category "
        f"'{knowledge_category}'. "
        if knowledge_category
        else "No knowledge category was selected — also suggest one (see document_category).\n"
    )
    return f"""Document: {filename}
{category_line}
{focus or 'Extract all of the customer intelligence below, at whatever depth the document supports.'}

Extract the customer intelligence described in this document. Return ONLY a JSON object with EXACTLY these keys (empty arrays when nothing applies):

{{
  "document_category": {{"category": "<one of the catalog below or null>", "reasoning": "<one line>"}},
  "customer_facts": [ITEM],
  "technologies": [TECH],
  "technology_dependencies": [TECH_DEP],
  "business_objectives": [ITEM],
  "business_challenges": [ITEM],
  "projects": [ITEM],
  "stakeholders": [ITEM],
  "requirements": [ITEM],
  "use_cases": [USE_CASE],
  "opportunities": [ITEM],
  "risks": [ITEM],
  "decisions": [ITEM],
  "follow_up_items": [ITEM]
}}

ITEM = {{"name": "<short name>", "description": "<what the document says>",
  "provenance": "explicit|derived|suggested", "confidence": 0.0-1.0,
  "evidence": "<short supporting quote from the document>",
  "source_reference": "<section/heading/page if identifiable, else null>"}}

TECH = ITEM plus any of: "vendor", "category" (one of: software, hardware, infrastructure, cloud_platform, virtualization, networking, storage, security, data_platform, ai_technology, operating_system, management_tool, automation_tool, other), "version_edition", "deployment_model" (on_premise|private_cloud|public_cloud|hybrid|saas|virtual_machine|container|bare_metal|unknown), "lifecycle_state" (current|previous_generation|eol_announced|eol|unknown), "support_state" (under_support|support_expiring|no_support|unknown), "business_criticality" (critical|high|medium|low), "footprint", "purpose". Only include fields the document actually states; omit the rest.

TECH_DEP = {{"name": "<Source> <relationship> <Target>", "source_technology": "<Source>", "target_technology": "<Target>", "relationship_type": "<runs_on|hosts|manages|consumes_storage|provides_storage|consumes_compute|provides_compute|integrates_with|automates|protects|depends_on|associated_with>", "provenance": "...", "confidence": 0.0-1.0, "evidence": "..."}}

USE_CASE = ITEM plus any of: "goals" (array of short strings), "business_value", "current_process", "desired_outcome".

Rules:
- provenance MUST match the evidence: a technology the document states the customer runs is "explicit"; a modernization candidate you inferred from that technology is "derived"; a recommendation to evaluate a product is "suggested".
- Do not return duplicates within a document; each technology appears once.
- opportunities: sales/infrastructure/modernization/AI opportunities, marked "derived" or "suggested" (never "explicit" unless the customer itself states an intent).
- Category catalog:
{_category_catalog()}

Document content:
{content}"""


# ----------------------------------------------------------------------
# LLM call + structured parse
# ----------------------------------------------------------------------


class EnrichmentError(Exception):
    """Enrichment-stage failure (isolated from Docling failures, item 16)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def extract_json_object(content: str) -> dict[str, Any]:
    """Pull the first balanced JSON object out of a model response.

    Tolerates code fences and leading/trailing prose. Raises
    EnrichmentError('unparseable_response') when no valid object is found.
    """
    text = (content or "").strip()
    if not text:
        raise EnrichmentError("unparseable_response", "Model returned no content")
    candidates: list[str] = []
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        candidates.append(fence.group(1).strip())
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])
    candidates.append(text)
    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue
    raise EnrichmentError(
        "unparseable_response",
        "Model response did not contain a valid JSON object — retry enrichment.",
    )


async def run_enrichment(
    db: Session,
    record: CKModel,
    model_name: str,
) -> KnowledgeEnrichmentResponse:
    """Call the configured LLM and return the validated structured result.

    Raises EnrichmentError on any failure class (item 16 kinds:
    llm_unavailable, unparseable_response, invalid_schema).
    """
    settings = effective_inference_settings(db)
    endpoint = (settings.get("ai_endpoint") or "").strip()
    api_key = (settings.get("api_key") or "").strip()
    if not endpoint or not api_key:
        raise EnrichmentError(
            "llm_unavailable",
            "The configured application LLM endpoint is not set — enrichment "
            "cannot run. Configure the inference settings and re-run "
            "enrichment.",
        )
    prompt = build_enrichment_prompt(
        filename=record.file_name,
        normalized_content=record.knowledge_text or "",
        knowledge_category=record.knowledge_category,
    )
    try:
        content = await AIClient(overrides=settings).complete(
            SYSTEM_PROMPT, prompt, max_tokens=4096, timeout=180.0
        )
    except EnrichmentError:
        raise
    except ValueError as exc:  # endpoint misconfigured / empty content
        raise EnrichmentError("llm_unavailable", str(exc))
    except Exception as exc:  # httpx transport/HTTP errors
        raise EnrichmentError("llm_unavailable", f"LLM call failed: {exc}")
    payload = extract_json_object(content)
    try:
        return normalize_enrichment_payload(payload)
    except Exception as exc:
        raise EnrichmentError("invalid_schema", f"Enrichment JSON failed schema validation: {exc}")


# ----------------------------------------------------------------------
# Item persistence + application (items 5, 6, 7, 15)
# ----------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _tech_name_key(name: str) -> str:
    """Deterministic case/space-insensitive technology identity (item 7)."""
    return re.sub(r"[\s\-_/]+", "", (name or "").lower())


def _existing_techs(db: Session, customer_id: int) -> list[dict[str, Any]]:
    from backend.models.customer_technology import CustomerTechnology

    rows = (
        db.query(CustomerTechnology)
        .filter(CustomerTechnology.customer_id == customer_id)
        .all()
    )
    return [t.to_dict() for t in rows]


def _existing_use_cases(db: Session, customer_id: int) -> list[dict[str, Any]]:
    from backend.models.use_case import UseCase

    rows = (
        db.query(UseCase).filter(UseCase.customer_id == customer_id).all()
    )
    return [u.to_dict() for u in rows]


def _match_tech(name: str, techs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find an existing technology whose identity matches (item 7)."""
    key = _tech_name_key(name)
    if not key:
        return None
    for t in techs:
        if _tech_name_key(t.get("name")) == key:
            return t
    # Substring fallback (e.g. "VMware vSphere 7" vs "vSphere")
    for t in techs:
        tkey = _tech_name_key(t.get("name"))
        if tkey and len(tkey) >= 4 and (tkey in key or key in tkey):
            return t
    return None


def _match_use_case(title: str, use_cases: list[dict[str, Any]]) -> dict[str, Any] | None:
    from backend.models.use_case import UseCase  # noqa: F401  (clarity)

    key = _tech_name_key(title)
    if not key:
        return None
    for u in use_cases:
        if _tech_name_key(u.get("title")) == key:
            return u
    return None


def _note_source(doc: CKModel, item) -> str:
    return f"Knowledge document: {doc.file_name} (knowledge id {doc.id})"


def _note_category_for(kind: str) -> str:
    return {
        "customer_fact": "account_observation",
        "business_objective": "initiative",
        "business_challenge": "risk",
        "project": "initiative",
        "stakeholder": "account_observation",
        "requirement": "discovery",
        "decision": "meeting",
        "follow_up_item": "follow_up",
        "risk": "risk",
        "technology": "technical_discussion",
        "technology_dependency": "technical_discussion",
        "use_case": "discovery",
        "opportunity": "opportunity",
    }.get(kind, "account_observation")


def _apply_tech_item(
    db: Session, customer_id: int, item: TechnologyItem, doc: CKModel,
    techs: list[dict[str, Any]],
) -> tuple[str, int | None, dict[str, Any] | None]:
    """Apply a technology item: link existing or create new (item 7).

    Returns (applied_status, applied_object_id, matched_existing).
    Raises HTTPException from the service layer on 409/422 classes, which
    the caller converts to a per-item failure (never aborts the run).
    """
    existing = _match_tech(item.name, techs)
    if existing is not None:
        # Strengthen: keep the human-verified record; only fill empty
        # fields the document states, never overwrite existing values.
        payload = {}
        for field in ("vendor", "version_edition", "deployment_model",
                      "lifecycle_state", "support_state",
                      "business_criticality", "footprint", "purpose"):
            if item.model_dump().get(field) and not existing.get(field):
                payload[field] = item.model_dump()[field]
        note = f"Also observed in: {doc.file_name} (knowledge id {doc.id})"
        if item.evidence:
            note += f" — “{item.evidence}”"
        if not existing.get("notes"):
            payload["notes"] = note
        elif doc.file_name not in (existing.get("notes") or ""):
            payload["notes"] = (existing.get("notes") or "") + " | " + note
        if payload:
            technology_inventory_service.update_technology(
                db, existing["id"], payload
            )
        return "linked", existing["id"], existing
    payload = {
        "name": item.name,
        "category": item.category or "other",
        "vendor": item.vendor,
        "version_edition": item.version_edition,
        "deployment_model": item.deployment_model,
        "lifecycle_state": item.lifecycle_state,
        "support_state": item.support_state,
        "business_criticality": item.business_criticality,
        "footprint": item.footprint,
        "purpose": item.purpose,
        "source": _note_source(doc, item),
        "date_observed": _utcnow().date(),
        "verification_state": _PROVENANCE_TO_VERIFICATION.get(
            item.provenance, "unverified"
        ),
        "confidence": item.confidence,
        "notes": item.evidence or None,
    }
    record = technology_inventory_service.create_technology(db, customer_id, payload)
    techs.append(record.to_dict())  # subsequent deps in the same run resolve it
    return "created", record.id, None


def _apply_dependency_item(
    db: Session, customer_id: int, item: TechnologyDependencyItem, doc: CKModel,
    techs: list[dict[str, Any]],
) -> tuple[str, int | None, dict[str, Any] | None]:
    """Apply a technology dependency item (item 5): create or link.

    Endpoints must exist in the customer's Technology Inventory — an
    endpoint the document names that the run just created is resolved
    from the local cache; endpoints not found are NOT created here
    (dependencies reference inventory records, they don't seed them).
    """
    source_tech = _match_tech(item.source_technology, techs)
    target_tech = _match_tech(item.target_technology, techs)
    if source_tech is None or target_tech is None:
        # No inventory endpoint to reference — keep it as evidence only.
        return "skipped", None, None
    record = technology_dependency_service.create_dependency(
        db,
        customer_id,
        {
            "source_id": source_tech["id"],
            "target_id": target_tech["id"],
            "relationship_type": item.relationship_type,
            "verification_state": _PROVENANCE_TO_VERIFICATION.get(
                item.provenance, "unverified"
            ),
            "confidence": item.confidence,
            "source_provenance": _note_source(doc, item),
            "notes": item.evidence or None,
        },
    )
    return "created", record.id, None


def _apply_generic_item(
    db: Session, customer_id: int, kind: str, item, doc: CKModel
) -> tuple[str, int | None, dict[str, Any] | None]:
    """Non-technology items become a sales note (item 5 mapping:
    challenge/stakeholder/project/requirement → note categories).
    Suggested items are Proposed evidence only (item 8)."""
    from backend.schemas.sales_note import SalesNoteCreate

    content = (
        f"{item.description or ''}"
        + (f"\n\nEvidence: {item.evidence}" if item.evidence else "")
    )
    if len(content) < 1:
        content = f"Extracted from {_note_source(doc, item)}."
    note = sales_note_service.create_sales_note(
        db,
        customer_id,
        SalesNoteCreate(
            category=_note_category_for(kind),
            title=f"[{kind.replace('_', ' ')}] {item.name}"[:255],
            content=content,
            source=_note_source(doc, item)[:255],
            verification_state=_PROVENANCE_TO_VERIFICATION.get(
                item.provenance, "unverified"
            ),
        ),
    )
    return "created", note.id, None


def _apply_use_case_item(
    db: Session, customer_id: int, item: UseCaseItem, doc: CKModel,
    use_cases: list[dict[str, Any]],
) -> tuple[str, int | None, dict[str, Any] | None]:
    """Apply a use-case item (item 5): link existing or create draft.

    Suggested use cases are created in 'draft' status (Proposed, item 8)
    — never scored or marked active by the pipeline.
    """
    existing = _match_use_case(item.name, use_cases)
    if existing is not None:
        return "linked", existing["id"], existing
    from backend.models.use_case import UseCase

    uc = UseCase(
        title=item.name[:255],
        description=item.description,
        customer_id=customer_id,
        status="draft",
        goals=item.goals or None,
        impact_description=item.business_value,
        created_by="knowledge-enrichment",
    )
    db.add(uc)
    db.commit()
    db.refresh(uc)
    use_cases.append(uc.to_dict())
    from backend.schemas.sales_note import SalesNoteCreate

    content = (
        f"Use case identified from document (status: draft, pending "
        f"human validation). {item.description or ''}"
        + (f"\n\nEvidence: {item.evidence}" if item.evidence else "")
    )
    sales_note_service.create_sales_note(
        db,
        customer_id,
        SalesNoteCreate(
            category="discovery",
            title=f"[proposed use case] {item.name}"[:255],
            content=content,
            source=_note_source(doc, item)[:255],
            related_use_case_ids=[uc.id],
            verification_state="unverified",
        ),
    )
    return "created", uc.id, None


def _apply_item(
    db: Session,
    customer_id: int,
    kind: str,
    item,
    doc: CKModel,
    techs: list[dict[str, Any]],
    use_cases: list[dict[str, Any]],
) -> tuple[str, int | None]:
    """Apply one extracted item to the domain objects (item 5).

    Returns (applied_status, applied_object_id). Raises HTTPException on
    service-layer 409/422; the caller records per-item failures instead
    of aborting the whole run.
    """
    if kind == "technology":
        status, obj_id, _ = _apply_tech_item(db, customer_id, item, doc, techs)
        return status, obj_id
    if kind == "technology_dependency":
        status, obj_id, _ = _apply_dependency_item(db, customer_id, item, doc, techs)
        return status, obj_id
    if kind == "use_case":
        status, obj_id, _ = _apply_use_case_item(db, customer_id, item, doc, use_cases)
        return status, obj_id
    status, obj_id, _ = _apply_generic_item(db, customer_id, kind, item, doc)
    return status, obj_id


def remove_document_items(db: Session, knowledge_id: int) -> int:
    """Delete this document's previous items (reprocess reconciliation,
    item 15). Applied domain objects are intentionally NOT deleted —
    re-extraction re-links/re-creates them through the same service
    paths (dedupe prevents duplicates)."""
    return (
        db.query(CustomerKnowledgeItem)
        .filter(CustomerKnowledgeItem.source_knowledge_id == knowledge_id)
        .delete(synchronize_session=False)
    )


def enrich_knowledge_record(
    db: Session,
    record: CKModel,
) -> dict[str, Any]:
    """Synchronous enrichment of ONE ready knowledge record.

    (The async wrapper below drives it from the worker thread with
    ``asyncio.run``; inline execution in tests calls this directly.)

    Summary dict: {status, items_total, items_applied, items_failed,
    error, error_kind, applied: {technologies, dependencies, notes,
    use_cases}}.
    """
    if record.processing_status != "READY":
        # No normalized content → enrichment is not possible (item 16:
        # Docling and enrichment failures are separate; this is the
        # enrichment side, and it must not overwrite the Docling state).
        record.enrichment_status = ENRICHMENT_SKIPPED
        record.enrichment_error = "Document is not READY — Docling processing must succeed first"
        record.enrichment_error_kind = "not_ready"
        db.commit()
        return {"status": ENRICHMENT_SKIPPED, "error": record.enrichment_error}

    record.enrichment_status = ENRICHMENT_ENRICHING
    record.enrichment_error = None
    record.enrichment_error_kind = None
    db.commit()

    started = _utcnow()
    # Reconcile: this document's previous items are replaced (item 15).
    remove_document_items(db, record.id)

    model_name = effective_inference_settings(db).get("ai_model") or ""
    result = _run_async(run_enrichment(db, record, model_name))

    # ── Persist items ────────────────────────────────────────────────
    items_total = 0
    items_applied = 0
    items_failed = 0
    applied_counts = {"technologies": 0, "dependencies": 0, "notes": 0, "use_cases": 0}
    techs = _existing_techs(db, record.customer_id)
    use_cases = _existing_use_cases(db, record.customer_id)

    # Category suggestion (item 1): authoritative only when the user
    # did not choose one at upload.
    suggested = (result.document_category or None)
    if suggested is not None and suggested.category and not record.knowledge_category:
        record.knowledge_category = suggested.category

    pairs = result.all_items()
    for kind, item in pairs:
        items_total += 1
        row = CustomerKnowledgeItem(
            customer_id=record.customer_id,
            source_knowledge_id=record.id,
            kind=kind,
            name=(item.name or "")[:500],
            description=item.description,
            provenance=item.provenance or "derived",
            confidence=item.confidence,
            evidence=item.evidence,
            source_reference=item.source_reference,
            enrichment_model=model_name or None,
            extracted_at=started,
        )
        db.add(row)
        # Apply to domain objects (item 5). Per-item failures are
        # recorded, never propagated: one bad item cannot sink the run.
        try:
            status, obj_id = _apply_item(
                db, record.customer_id, kind, item, record, techs, use_cases
            )
            row.applied_status = status
            row.applied_object_type = kind
            row.applied_object_id = obj_id
            if status in ("created", "linked"):
                items_applied += 1
                if kind == "technology" or kind == "technology_dependency":
                    applied_counts["technologies" if kind == "technology" else "dependencies"] += 1
                elif kind == "use_case":
                    applied_counts["use_cases"] += 1
                else:
                    applied_counts["notes"] += 1
            db.commit()
        except HTTPException as exc:
            # 409 (duplicate dependency) / 422 (vocab) — keep the item
            # as evidence, mark the application failed.
            row.applied_status = "failed"
            row.applied_object_type = kind
            row.applied_object_id = None
            items_failed += 1
            db.commit()
            logger.warning(
                "enrichment: apply failed for kind=%s name=%r (%s)",
                kind, item.name, exc.detail,
            )
        except Exception as exc:  # noqa: BLE001 — isolated per item
            row.applied_status = "failed"
            row.applied_object_type = kind
            row.applied_object_id = None
            items_failed += 1
            try:
                db.commit()
            except Exception:
                db.rollback()
            logger.warning("enrichment: apply error for kind=%s name=%r: %s", kind, item.name, exc)

    db.commit()

    record.enrichment_status = ENRICHMENT_ENRICHED
    record.enrichment_error = None
    record.enrichment_error_kind = None
    record.enrichment_model = model_name or None
    record.enrichment_time_seconds = (
        datetime.now(UTC) - started
    ).total_seconds()
    record.enriched_at = datetime.now(UTC)
    db.commit()

    return {
        "status": ENRICHMENT_ENRICHED,
        "items_total": items_total,
        "items_applied": items_applied,
        "items_failed": items_failed,
        "applied": applied_counts,
        "suggested_category": (
            suggested.category if suggested and suggested.category else None
        ),
    }


def _run_async(coro):
    """Drive an async LLM call from a (synchronous) worker context.

    A fresh event loop per call — safe from worker threads and test
    inline execution alike.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside a loop (e.g. a test driving it directly) — nest.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
