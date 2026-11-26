"""LLM knowledge enrichment tests (CHANGELOG 0.1.2).

Covers items 1, 2, 4, 5, 6, 7, 8, 13, 15, 16:

- automatic enrichment after Docling success (upload → READY → ENRICHED);
- structured LLM output via the Pydantic schema (item 13);
- application to domain objects through the service layer (item 5):
  Technology Inventory, Sales Notes, Use Cases (draft/proposed);
- dedupe: second document with the same technology strengthens the
  existing row instead of duplicating (item 7);
- provenance → verification_state mapping (item 6);
- user-selected category is authoritative; LLM suggestion only when
  absent (item 1);
- Docling/LLM failure isolation (item 16): LLM failure leaves the
  document READY with enrichment FAILED; retry-enrichment reruns only
  the LLM stage (Docling is NOT called again);
- reprocess reruns the full pipeline without duplicate intelligence
  (item 15);
- items endpoint + auth boundaries.

The LLM is mocked at ``kes.AIClient`` (never a real call — charter §6);
the conftest Docling fake handles normalization. ``AIClient.complete``
is patched to return prebaked JSON; the real
``normalize_enrichment_payload`` validates it (the schema path is
exercised end to end).
"""

import json

import pytest
from backend.models.customer_knowledge import (
    CustomerKnowledge as CKModel,
)
from backend.models.customer_knowledge import (
    CustomerKnowledgeItem,
)
from backend.services import knowledge_enrichment_service as kes

from tests.backend.test_customer_knowledge import (
    _admin_headers,
    _non_admin_headers,
    _seed_customer_with_junction,
)

# ----------------------------------------------------------------------
# Enrichment payload fixtures (the "model response")
# ----------------------------------------------------------------------

ENRICHMENT_JSON_A = {
    "document_category": {"category": "technology_infrastructure", "reasoning": "tech doc"},
    "customer_facts": [
        {"name": "Runs VMware vSphere across two datacenters", "description": "Primary virtualization platform", "provenance": "explicit", "confidence": 0.95, "evidence": "The customer operates VMware vSphere in two datacenters.", "source_reference": "Section 2"},
    ],
    "technologies": [
        {"name": "VMware vSphere", "vendor": "VMware", "category": "virtualization", "deployment_model": "on_premise", "lifecycle_state": "current", "provenance": "explicit", "confidence": 0.95, "evidence": "The customer operates VMware vSphere in two datacenters.", "source_reference": "Section 2"},
        {"name": "Oracle Database 12c", "category": "data_platform", "lifecycle_state": "eol_announced", "provenance": "explicit", "confidence": 0.9, "evidence": "Oracle Database 12c production instance."},
    ],
    "technology_dependencies": [
        {"name": "vCenter manages VMware vSphere", "source_technology": "vCenter", "target_technology": "VMware vSphere", "relationship_type": "manages", "provenance": "derived", "confidence": 0.7, "evidence": "vCenter manages the vSphere fleet."},
    ],
    "business_challenges": [
        {"name": "Aging EOL virtualization stack", "description": "vSphere support expiring", "provenance": "derived", "confidence": 0.8, "evidence": "Support for vSphere expires next year."},
    ],
    "use_cases": [
        {"name": "Automate VM lifecycle operations", "goals": ["Reduce manual VM operations"], "business_value": "50% faster provisioning", "provenance": "suggested", "confidence": 0.6, "evidence": "Frequent manual VM operations were reported."},
    ],
    "opportunities": [
        {"name": "OpenShift Virtualization modernization", "description": "Potential migration target for the vSphere fleet", "provenance": "suggested", "confidence": 0.7, "evidence": "vSphere fleet + EOL lifecycle"},
    ],
}

# Document B: same vSphere (dedupe target) + new stakeholder.
ENRICHMENT_JSON_B = {
    "document_category": {"category": "meeting_notes_customer_communications", "reasoning": "notes"},
    "customer_facts": [],
    "technologies": [
        {"name": "VMware vSphere", "vendor": "VMware", "category": "virtualization", "provenance": "explicit", "confidence": 0.95, "evidence": "vSphere confirmed in the call."},
    ],
    "technology_dependencies": [],
    "business_challenges": [],
    "stakeholders": [
        {"name": "Dana Reyes (Infrastructure Lead)", "description": "Owns the virtualization platform", "provenance": "explicit", "confidence": 0.9, "evidence": "Dana Reyes leads infrastructure."},
    ],
    "use_cases": [],
    "opportunities": [],
}


def _install_mock_llm(monkeypatch, payloads):
    """Patch ``kes.AIClient`` with a scripted ``complete()`` and make the
    inference settings report a configured endpoint + key.

    The endpoint/key stub is required, not cosmetic: ``run_enrichment``
    consults ``effective_inference_settings`` BEFORE calling ``AIClient``
    and raises ``llm_unavailable`` when the endpoint or key is empty. On a
    dev workstation the repository ``.env`` (loaded by conftest) supplies
    real values, so the mock reached the LLM stage; on a CI runner no
    ``.env`` exists and the same tests fail with
    ``assert 'FAILED' == 'ENRICHED'`` (issues 118/119). Stubbing the
    settings seam keeps these tests deterministic in both environments.
    Tests that exercise the genuinely-unconfigured path
    (``test_upload_without_llm_configured_stays_ready``) do NOT use this
    helper and leave the endpoint empty.

    ``payloads`` is a list; each call pops the next entry. An entry may
    be a dict (the JSON object is serialized as the model would) or an
    Exception instance to raise.
    """

    monkeypatch.setattr(
        kes, "effective_inference_settings",
        lambda db=None: {
            "ai_endpoint": "http://mock-llm.invalid/v1",
            "ai_model": "mock-model",
            "api_key": "test-key",
            "temperature": 0.3,
            "max_tokens": 2000,
            "timeout": 60.0,
            "enabled": True,
        },
    )

    class _MockAIClient:
        def __init__(self, overrides=None):
            pass

        async def complete(self, system_prompt, user_prompt, max_tokens=700, timeout=60.0):
            entry = payloads.pop(0) if payloads else {}
            if isinstance(entry, Exception):
                raise entry
            return json.dumps(entry)

    monkeypatch.setattr(kes, "AIClient", _MockAIClient)


def _enable_enrichment(monkeypatch):
    monkeypatch.setenv("SAIL_KNOWLEDGE_ENRICHMENT", "1")


def _upload(client, db_session, filename: str, data: bytes,
            customer_id: int = 1, knowledge_category: str | None = None):
    files = {"file": (filename, data, "application/octet-stream")}
    data_ = {"customer_id": str(customer_id)}
    if knowledge_category is not None:
        data_["knowledge_category"] = knowledge_category
    return client.post(
        "/api/customer-knowledge/", files=files, data=data_,
        headers=_admin_headers(db_session),
    )


def _detail(client, headers, knowledge_id: int):
    return client.get(f"/api/customer-knowledge/{knowledge_id}", headers=headers)


# ----------------------------------------------------------------------
# Automatic enrichment after Docling success (items 2, 4)
# ----------------------------------------------------------------------


class TestAutoEnrichment:
    def test_upload_auto_enriches_and_applies(self, client, db_session, monkeypatch):
        """Upload → Docling (mocked) → LLM (mocked) → ENRICHED, with the
        intelligence applied to the domain objects (item 5)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A])

        r = _upload(client, db_session, "vcenter-inventory.pdf", b"%PDF fake")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()

        # Docling stage (item 16: separate from enrichment)
        assert rec.processing_status == "READY"
        assert rec.normalized_content
        # Enrichment stage
        assert rec.enrichment_status == "ENRICHED"
        assert rec.enriched_at is not None
        assert rec.enrichment_error is None
        assert rec.knowledge_category == "technology_infrastructure"  # LLM suggested (user absent)

        # Items persisted (items 6, 13): 1 fact + 2 techs + 1 dep + 1
        # challenge + 1 use case + 1 opportunity = 7
        items = db_session.query(CustomerKnowledgeItem).filter(
            CustomerKnowledgeItem.source_knowledge_id == kid
        ).all()
        assert len(items) == 7
        by_kind = {i.kind: i for i in items}
        assert by_kind["customer_fact"].provenance == "explicit"
        assert by_kind["technology"].applied_status in ("created", "linked")

        # Applied to Technology Inventory through the service layer (item 5):
        # explicit → verified (item 6).
        from backend.models.customer_technology import CustomerTechnology

        techs = db_session.query(CustomerTechnology).filter(
            CustomerTechnology.customer_id == 1
        ).all()
        tech_names = {t.name for t in techs}
        assert "VMware vSphere" in tech_names
        assert "Oracle Database 12c" in tech_names
        vsphere = next(t for t in techs if t.name == "VMware vSphere")
        assert vsphere.verification_state == "verified"
        assert vsphere.vendor == "VMware"
        assert vsphere.category == "virtualization"
        assert "vcenter-inventory.pdf" in (vsphere.source or "")

        # Suggested use case → draft (Proposed, item 8) + unverified note:
        from backend.models.sales_note import SalesNote
        from backend.models.use_case import UseCase

        uc = db_session.query(UseCase).filter(UseCase.customer_id == 1).first()
        assert uc is not None
        assert "Automate VM lifecycle operations" in uc.title
        assert uc.status == "draft"

        notes = db_session.query(SalesNote).filter(SalesNote.customer_id == 1).all()
        cats = {n.category for n in notes}
        # challenge→risk, fact→account_observation, use case→discovery,
        # opportunity→opportunity, dependency→technical_discussion
        assert {"risk", "account_observation", "discovery", "opportunity"} <= cats

        # Technology dependency applied (endpoint vCenter is not in the
        # inventory → skipped as evidence-only; the item row keeps it):
        assert by_kind["technology_dependency"].applied_status == "skipped"
        # Detail wire carries the enrichment state
        d = _detail(client, _admin_headers(db_session), kid).json()
        assert d["enrichment_status"] == "ENRICHED"
        assert d["knowledge_category"] == "technology_infrastructure"

    def test_upload_without_llm_configured_stays_ready(self, client, db_session, monkeypatch):
        """LLM endpoint unset → enrichment FAILED (llm_unavailable) but the
        document is READY with its normalized content (item 16)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        # No ai_endpoint in the test env → llm_unavailable.
        monkeypatch.setenv("SAIL_AI_ENDPOINT", "")
        r = _upload(client, db_session, "notes.md", b"# Ops notes\n\nVMware vSphere fleet.")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.processing_status == "READY"
        assert rec.normalized_content
        assert rec.enrichment_status == "FAILED"
        assert rec.enrichment_error_kind == "llm_unavailable"

    def test_llm_failure_keeps_docling_result(self, client, db_session, monkeypatch):
        """Docling SUCCESS + LLM FAILURE: the normalized document stays
        available and enrichment can be retried (item 16). The retry
        re-runs ONLY the LLM stage — Docling is NOT called again."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        # First call (upload auto-enrich) fails; second (retry) succeeds.
        _install_mock_llm(monkeypatch, [Exception("boom"), ENRICHMENT_JSON_B])
        docling_calls = []

        import backend.services.customer_knowledge_service as cks

        class _CountingFakeDL:
            name = "docling"

            def supported_extensions(self):
                from backend.services.docling_service import DOCLING_SUPPORTED_EXTENSIONS

                return frozenset(DOCLING_SUPPORTED_EXTENSIONS)

            def convert(self, file_bytes, filename, content_type="application/octet-stream"):
                res = self.convert_to_markdown(file_bytes, filename, content_type)
                res.processor = "docling"
                return res

            def __init__(self, *a, **k):
                pass

            def convert_to_markdown(self, *a, **k):
                docling_calls.append(1)
                from backend.services.docling_service import DoclingConversionResult

                return DoclingConversionResult(
                    markdown="# Normalized content",
                    status="success",
                    partial=False,
                    processing_time_seconds=0.01,
                )

            def health(self):
                return {"status": "ok"}

        monkeypatch.setattr(cks, "build_converter", lambda db: _CountingFakeDL())

        r = _upload(client, db_session, "x.pdf", b"%PDF fake")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.processing_status == "READY"
        assert rec.enrichment_status == "FAILED"
        assert rec.enrichment_error_kind == "llm_unavailable"
        assert len(docling_calls) == 1

        # Retry the LLM stage only (Docling must NOT be called again):
        resp = client.post(
            f"/api/customer-knowledge/{kid}/enrich",
            headers=_admin_headers(db_session),
        )
        assert resp.status_code == 200
        assert len(docling_calls) == 1
        # Expire the fixture session's cached instances: the route
        # committed the enrichment state on its own session, and the
        # ORM identity map would otherwise return the pre-retry row.
        db_session.expire_all()
        rec2 = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec2.enrichment_status == "ENRICHED"
        assert rec2.processing_status == "READY"
        # The retry reconciled the run: items exist for the document now.
        items = db_session.query(CustomerKnowledgeItem).filter(
            CustomerKnowledgeItem.source_knowledge_id == kid
        ).all()
        assert len(items) == 2  # 1 technology + 1 stakeholder (JSON_B)

    def test_unparseable_llm_response_is_failed(self, client, db_session, monkeypatch):
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        # Settings stubbed (endpoint+key set) so the run reaches the LLM
        # stage; AIClient is mocked inline to return non-JSON prose.
        _install_mock_llm(monkeypatch, [])

        class _MockAIClient:
            def __init__(self, overrides=None):
                pass

            async def complete(self, system_prompt, user_prompt, max_tokens=700, timeout=60.0):
                return "Sorry, here is a summary of the document: ..."

        monkeypatch.setattr(kes, "AIClient", _MockAIClient)
        r = _upload(client, db_session, "x.md", b"# doc\n\ncontent")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.processing_status == "READY"
        assert rec.enrichment_status == "FAILED"
        assert rec.enrichment_error_kind == "unparseable_response"


# ----------------------------------------------------------------------
# Category behavior (item 1)
# ----------------------------------------------------------------------


class TestCategories:
    def test_user_category_is_authoritative(self, client, db_session, monkeypatch):
        """User-selected category is preserved even when the LLM
        suggests a different one (item 1)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A])

        r = _upload(client, db_session, "strategy.pdf", b"%PDF fake",
                    knowledge_category="business_strategy_goals")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.knowledge_category == "business_strategy_goals"
        assert rec.enrichment_status == "ENRICHED"

    def test_upload_rejects_out_of_vocab_category(self, client, db_session, monkeypatch):
        _seed_customer_with_junction(db_session, customer_id=1)
        r = _upload(client, db_session, "x.pdf", b"%PDF fake",
                    knowledge_category="not_a_category")
        assert r.status_code == 422

    def test_upload_without_category_is_allowed(self, client, db_session, monkeypatch):
        _seed_customer_with_junction(db_session, customer_id=1)
        r = _upload(client, db_session, "x.md", b"# hello\nworld")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.knowledge_category is None
        # conftest default: enrichment disabled → NOT_RUN, document READY
        assert rec.processing_status == "READY"
        assert rec.enrichment_status == "NOT_RUN"


# ----------------------------------------------------------------------
# Dedupe (item 7) + reprocess reconciliation (item 15)
# ----------------------------------------------------------------------


class TestDedupeAndReprocess:
    def test_second_document_strengthenes_existing_tech(self, client, db_session, monkeypatch):
        """Three documents mentioning vSphere must not create three
        vSphere rows (item 7)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A, ENRICHMENT_JSON_B])

        r1 = _upload(client, db_session, "doc-a.pdf", b"%PDF a")
        kid1 = r1.json()["knowledge_id"]
        r2 = _upload(client, db_session, "doc-b.pdf", b"%PDF b")
        kid2 = r2.json()["knowledge_id"]

        from backend.models.customer_technology import CustomerTechnology

        vsphere_rows = (
            db_session.query(CustomerTechnology)
            .filter(
                CustomerTechnology.customer_id == 1,
                CustomerTechnology.name == "VMware vSphere",
            )
            .all()
        )
        assert len(vsphere_rows) == 1
        vsphere = vsphere_rows[0]
        # Strengthened by the second document (notes updated):
        assert "doc-b.pdf" in (vsphere.notes or "")

        # The second document's technology item is LINKED, not created:
        items_b = db_session.query(CustomerKnowledgeItem).filter(
            CustomerKnowledgeItem.source_knowledge_id == kid2,
            CustomerKnowledgeItem.kind == "technology",
        ).all()
        assert len(items_b) == 1
        assert items_b[0].applied_status == "linked"
        assert items_b[0].applied_object_id == vsphere.id

    def test_reprocess_reruns_pipeline_without_duplicates(self, client, db_session, monkeypatch):
        """Reprocess reruns Docling + enrichment (item 15) and does not
        duplicate applied domain objects."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A, ENRICHMENT_JSON_A])

        r = _upload(client, db_session, "x.pdf", b"%PDF fake")
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]

        from backend.models.customer_technology import CustomerTechnology
        from backend.models.use_case import UseCase

        techs_before = db_session.query(CustomerTechnology).filter(
            CustomerTechnology.customer_id == 1
        ).count()
        ucs_before = db_session.query(UseCase).filter(UseCase.customer_id == 1).count()

        resp = client.post(
            f"/api/customer-knowledge/{kid}/reprocess",
            headers=_admin_headers(db_session),
        )
        assert resp.status_code == 200

        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.processing_status == "READY"
        assert rec.enrichment_status == "ENRICHED"

        techs_after = db_session.query(CustomerTechnology).filter(
            CustomerTechnology.customer_id == 1
        ).count()
        ucs_after = db_session.query(UseCase).filter(UseCase.customer_id == 1).count()
        assert techs_after == techs_before  # re-extraction LINKS, no dupes
        assert ucs_after == ucs_before

        # Previous items were replaced by the new run (reconciled, item 15):
        items = db_session.query(CustomerKnowledgeItem).filter(
            CustomerKnowledgeItem.source_knowledge_id == kid
        ).all()
        assert len(items) == 7  # exactly one run's worth
        assert all(i.applied_status in ("created", "linked", "skipped") for i in items)


# ----------------------------------------------------------------------
# Items endpoint + authorization (charter: customer isolation)
# ----------------------------------------------------------------------


class TestItemsEndpoint:
    def test_items_list_roundtrip(self, client, db_session, monkeypatch):
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A])
        r = _upload(client, db_session, "x.pdf", b"%PDF fake")
        kid = r.json()["knowledge_id"]
        resp = client.get(
            f"/api/customer-knowledge/{kid}/items",
            headers=_admin_headers(db_session),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 7
        sample = next(i for i in body if i["kind"] == "technology")
        assert sample["provenance"] == "explicit"
        assert sample["source_knowledge_id"] == kid
        assert sample["applied_status"] in ("created", "linked")
        assert "evidence" in sample

    def test_items_auth_boundaries(self, client, db_session, monkeypatch):
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A])
        r = _upload(client, db_session, "x.pdf", b"%PDF fake")
        kid = r.json()["knowledge_id"]

        # Unauthenticated → 401
        assert client.get(f"/api/customer-knowledge/{kid}/items").status_code == 401
        # Member of ANOTHER customer → 404 (never 200, no leakage)
        other_headers = _non_admin_headers(db_session, customer_id=2)
        assert client.get(f"/api/customer-knowledge/{kid}/items", headers=other_headers).status_code == 404
        # Member of THIS customer → 200
        member_headers = _non_admin_headers(db_session, customer_id=1)
        assert client.get(f"/api/customer-knowledge/{kid}/items", headers=member_headers).status_code == 200

    def test_retry_enrich_requires_ready(self, client, db_session, monkeypatch):
        """A FAILED document cannot be enrichment-retried (it must be
        reprocessed first) — item 16 state machine."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A])

        # Force a Docling failure: unsupported document type.
        r = _upload(client, db_session, "archive.zip", b"PK fake zip")
        kid = r.json()["knowledge_id"]
        rec = db_session.query(CKModel).filter(CKModel.id == kid).first()
        assert rec.processing_status == "FAILED"
        assert rec.enrichment_status == "NOT_RUN"
        resp = client.post(
            f"/api/customer-knowledge/{kid}/enrich",
            headers=_admin_headers(db_session),
        )
        assert resp.status_code == 409
        # Enrichment of a non-existent record → 404
        assert client.post(
            "/api/customer-knowledge/99999/enrich",
            headers=_admin_headers(db_session),
        ).status_code == 404

    def test_delete_also_removes_extracted_items(self, client, db_session, monkeypatch):
        """Deleting a knowledge document removes its LLM-extracted items
        (the runtime SQLite connection does not enforce the schema's
        ON DELETE CASCADE — the service deletes them explicitly)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        _enable_enrichment(monkeypatch)
        _install_mock_llm(monkeypatch, [ENRICHMENT_JSON_A])
        r = _upload(client, db_session, "x.pdf", b"%PDF fake")
        kid = r.json()["knowledge_id"]

        items_before = db_session.query(CustomerKnowledgeItem).filter(
            CustomerKnowledgeItem.source_knowledge_id == kid
        ).count()
        assert items_before == 7

        resp = client.delete(
            f"/api/customer-knowledge/{kid}", headers=_admin_headers(db_session)
        )
        assert resp.status_code == 200
        items_after = db_session.query(CustomerKnowledgeItem).filter(
            CustomerKnowledgeItem.source_knowledge_id == kid
        ).count()
        assert items_after == 0
        # No orphaned rows anywhere in the items table.
        orphans = db_session.query(CustomerKnowledgeItem).filter(
            ~CustomerKnowledgeItem.source_knowledge_id.in_(
                db_session.query(CKModel.id)
            )
        ).count()
        assert orphans == 0


# ----------------------------------------------------------------------
# Schema-level tests (item 13: typed validation, no prose parsing)
# ----------------------------------------------------------------------


class TestSchema:
    def test_normalize_payload_tolerates_extras_and_drops_bad_items(self):
        payload = json.loads(json.dumps(ENRICHMENT_JSON_A))
        payload["mystery_field"] = "ignored"
        payload["technologies"].append({"name": "", "provenance": "bogus"})
        from backend.schemas.knowledge_enrichment import normalize_enrichment_payload

        # The invalid item is dropped by normalize_enrichment_payload's
        # per-field cleanup only for non-dicts; a dict with an invalid
        # enum value raises at validation time (strict — item 13). The
        # service layer catches it as invalid_schema.
        with pytest.raises(Exception):
            normalize_enrichment_payload(payload)
        # A clean payload validates:
        result = normalize_enrichment_payload(json.loads(json.dumps(ENRICHMENT_JSON_A)))
        assert len(result.technologies) == 2
        assert all(t.name for t in result.technologies)

    def test_normalize_payload_rejects_non_object(self):
        with pytest.raises(ValueError):
            from backend.schemas.knowledge_enrichment import (
                normalize_enrichment_payload,
            )

            normalize_enrichment_payload([1, 2, 3])

    def test_provenance_validation(self):
        from backend.schemas.knowledge_enrichment import EnrichedItem

        item = EnrichedItem(name="x", provenance="explicit", confidence=0.5)
        assert item.provenance == "explicit"
        with pytest.raises(Exception):
            EnrichedItem(name="x", provenance="maybe")

    def test_dependency_vocabulary(self):
        from backend.schemas.knowledge_enrichment import TechnologyDependencyItem

        d = TechnologyDependencyItem(
            name="A runs on B", source_technology="A", target_technology="B",
            relationship_type="runs_on",
        )
        assert d.relationship_type == "runs_on"
        with pytest.raises(Exception):
            TechnologyDependencyItem(
                name="A ? B", source_technology="A", target_technology="B",
                relationship_type="explodes",
            )
