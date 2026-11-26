"""Provider-neutral document conversion — Azure Document Intelligence.

Covers the ``DocumentConverter`` seam (backend/services/document_provider.py):
Docling adapter parity, the Azure analyze + poll contract (mocked httpx
transport — no Azure resource), failure classification, endpoint/key
redaction, runtime provider selection on the worker's own session, the
admin ``/api/admin/config/documents`` surface, and the Customer Knowledge
upload flow under the Azure provider (original preserved, customer
isolation, Markdown short-circuit).
"""

import os

os.environ.setdefault("SAIL_JWT_SECRET", "test-secret-for-unit-tests-only-00000000")

import json
from unittest.mock import patch

import httpx
import pytest
from backend.services.docling_service import DoclingService
from backend.services.document_provider import (
    AZURE_DI_API_VERSION,
    PROVIDER_AZURE,
    AzureDocumentIntelligenceConverter,
    ConversionResult,
    ProviderError,
    build_converter,
)

from tests.backend.test_customer_knowledge import _seed_customer_with_junction

ENDPOINT = "https://sail-di-test.cognitiveservices.azure.com"
HOST = "sail-di-test.cognitiveservices.azure.com"
KEY = "test-azure-key-0000"
OP_URL = (
    f"{ENDPOINT}/documentintelligence/documentModels/prebuilt-layout/analyzeResults/"
    f"res-123?api-version={AZURE_DI_API_VERSION}"
)
TABLE_MD = (
    "# Inventory\n\n<table>\n<tr><th>software</th><th>version</th></tr>\n"
    "<tr><td>Veeem Placeholder</td><td>12.0</td></tr>\n</table>\n"
)
_FAKE_BCRYPT_HASH = "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"


def _accepted() -> httpx.Response:
    return httpx.Response(202, headers={"Operation-Location": OP_URL})


def _succeeded(md: str | None = TABLE_MD) -> httpx.Response:
    document: dict = {}
    if md is not None:
        document["markdown"] = {"content": md}
    return httpx.Response(200, json={"status": "succeeded", "analyzeResult": {"document": document}})


def _running() -> httpx.Response:
    return httpx.Response(200, json={"status": "running"})


class _Azure:
    """Scripted Azure DI mock: one analyze response, then a poll sequence."""

    def __init__(self, analyze=None, polls=None):
        self.analyze = analyze or _accepted()
        self.polls = list(polls or [_succeeded()])
        self.requests: list[httpx.Request] = []

    @property
    def poll_requests(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == "GET"]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            return self.analyze
        if len(self.polls) > 1:
            return self.polls.pop(0)
        return self.polls[0]


def _converter(mock: _Azure, **kwargs) -> AzureDocumentIntelligenceConverter:
    kwargs.setdefault("endpoint", ENDPOINT)
    kwargs.setdefault("api_key", KEY)
    kwargs.setdefault("poll_interval_seconds", 0.0)
    return AzureDocumentIntelligenceConverter(transport=httpx.MockTransport(mock), **kwargs)


def _errors_kind(fn) -> ProviderError:
    with pytest.raises(ProviderError) as ei:
        fn()
    return ei.value


# ----------------------------------------------------------------------
# 1. Docling adapter parity
# ----------------------------------------------------------------------


def test_docling_adapter_convert_returns_conversion_result():
    payload = {
        "document": {"md_content": "| a |\n|---|\n| 1 |\n", "processor_version": "docling-2.0"},
        "status": "success",
        "errors": [],
        "processing_time": 0.05,
    }

    def handler(request):
        return httpx.Response(200, json=payload)

    svc = DoclingService(server_url="http://docling.test:5001", transport=httpx.MockTransport(handler))
    assert svc.name == "docling"
    assert ".csv" in svc.supported_extensions()
    res = svc.convert(b"a\n1\n", "t.csv", "text/csv")
    assert isinstance(res, ConversionResult)
    assert res.processor == "docling"
    assert res.processor_version == "docling-2.0"
    assert res.markdown == payload["document"]["md_content"]
    # Legacy entry point still works (processor left at the default).
    legacy = svc.convert_to_markdown(b"a\n1\n", "t.csv", "text/csv")
    assert legacy.markdown == res.markdown


# ----------------------------------------------------------------------
# 2-10. Azure analyze + poll contract
# ----------------------------------------------------------------------


def test_azure_success_markdown_verbatim_and_redacted():
    mock = _Azure(polls=[_running(), _succeeded()])
    res = _converter(mock).convert(b"%PDF-1.4 x", "inventory.pdf", "application/pdf")
    assert res.markdown == TABLE_MD
    assert res.processor == "azure_document_intelligence"
    assert res.processor_version == "prebuilt-layout/2024-11-30"
    assert res.partial is False
    assert res.status == "success"
    assert ENDPOINT not in str(res) and HOST not in str(res)
    assert HOST not in json.dumps(res.raw)
    # Request shape per the official v4.0 contract.
    post = mock.requests[0]
    assert post.url.path == "/documentintelligence/documentModels/prebuilt-layout:analyze"
    assert post.url.params["api-version"] == AZURE_DI_API_VERSION
    assert post.url.params["_overload"] == "analyzeDocument"
    assert post.url.params["outputContentFormat"] == "markdown"
    assert post.headers["Ocp-Apim-Subscription-Key"] == KEY
    assert "base64Source" in json.loads(post.content)
    assert all(r.headers["Ocp-Apim-Subscription-Key"] == KEY for r in mock.poll_requests)
    assert len(mock.poll_requests) == 2


def test_azure_unsupported_extension_makes_no_requests():
    mock = _Azure()
    err = _errors_kind(lambda: _converter(mock).convert(b"x", "sheet.csv"))
    assert err.kind == "unsupported_document"
    assert "sheet.csv" in err.message
    assert mock.requests == []


def test_azure_auth_401_is_authentication_failure_without_host():
    mock = _Azure(analyze=httpx.Response(401, json={"error": {"code": "401", "message": "denied"}}))
    err = _errors_kind(lambda: _converter(mock).convert(b"%PDF", "a.pdf"))
    assert err.kind == "authentication_failure"
    assert err.message == "Azure Document Intelligence rejected the credentials"
    assert HOST not in err.message and KEY not in err.message


def test_azure_analyze_content_unsupported_is_unsupported_document():
    body = {"error": {"code": "DocumentContentUnsupported", "message": "corrupt or unsupported"}}
    mock = _Azure(analyze=httpx.Response(422, json=body))
    err = _errors_kind(lambda: _converter(mock).convert(b"%PDF", "a.pdf"))
    assert err.kind == "unsupported_document"
    assert err.message == (
        "Azure Document Intelligence error: DocumentContentUnsupported: corrupt or unsupported"
    )


def test_azure_poll_non_json_is_malformed_response():
    mock = _Azure(polls=[httpx.Response(200, content=b"<html>gateway</html>")])
    err = _errors_kind(lambda: _converter(mock).convert(b"%PDF", "a.pdf"))
    assert err.kind == "malformed_response"


def test_azure_poll_failed_is_conversion_failure():
    failed = httpx.Response(200, json={
        "status": "failed",
        "analyzeResult": {"errors": [{"code": "DocumentAnalysisFailed", "message": "boom"}]},
    })
    mock = _Azure(polls=[failed])
    err = _errors_kind(lambda: _converter(mock).convert(b"%PDF", "a.pdf"))
    assert err.kind == "conversion_failure"
    assert "boom" in err.message
    assert err.message.startswith("Document conversion failed: ")


@pytest.mark.parametrize("md", [None, "", "   \n"])
def test_azure_empty_markdown_is_empty_result(md):
    mock = _Azure(polls=[_succeeded(md)])
    err = _errors_kind(lambda: _converter(mock).convert(b"%PDF", "a.pdf"))
    assert err.kind == "empty_result"
    assert err.message == "Azure Document Intelligence produced no Markdown content for 'a.pdf'"


def test_azure_poll_budget_exhausted_is_conversion_timeout():
    mock = _Azure(polls=[_running()])
    conv = _converter(mock, timeout_seconds=0.2, poll_interval_seconds=0.05)
    err = _errors_kind(lambda: conv.convert(b"%PDF", "a.pdf"))
    assert err.kind == "conversion_timeout"
    assert "did not complete within" in err.message
    assert HOST not in err.message


def test_azure_poll_429_is_retried_within_budget():
    mock = _Azure(polls=[httpx.Response(429), _succeeded()])
    res = _converter(mock).convert(b"%PDF", "a.pdf")
    assert res.markdown == TABLE_MD
    assert len(mock.poll_requests) == 2


# ----------------------------------------------------------------------
# 11. Endpoint validation
# ----------------------------------------------------------------------


def test_azure_http_endpoint_is_value_error():
    with pytest.raises(ValueError) as ei:
        AzureDocumentIntelligenceConverter(endpoint="http://x")
    assert str(ei.value) == "azure_endpoint must be an HTTPS endpoint (https://)"


def test_build_converter_azure_without_endpoint_is_provider_unavailable(db_session, monkeypatch):
    from backend.services.config_service import upsert_config_entry

    monkeypatch.delenv("SAIL_AZURE_DI_ENDPOINT", raising=False)
    upsert_config_entry(db_session, "documents", "provider", PROVIDER_AZURE)
    conv = build_converter(db_session)
    assert isinstance(conv, AzureDocumentIntelligenceConverter)
    err = _errors_kind(lambda: conv.convert(b"%PDF", "a.pdf"))
    assert err.kind == "provider_unavailable"
    assert err.message == "Azure Document Intelligence endpoint is not configured"


# ----------------------------------------------------------------------
# 12. Provider selection — runtime-effective on the worker's own session
# ----------------------------------------------------------------------


def test_default_provider_is_docling():
    from backend.services.config_service import effective_document_settings

    assert effective_document_settings(None)["provider"] == "docling"
    assert isinstance(build_converter(None), DoclingService)


def test_worker_session_path_selects_azure_from_db(tmp_path, monkeypatch):
    """The production worker (no session passed in) resolves the provider on
    its OWN session, so a DB-only provider selection is runtime-effective."""
    import backend.services.customer_knowledge_service as cks
    from backend.models.collaboration import SystemConfig
    from backend.models.customer_knowledge import CustomerKnowledge as CKModel
    from backend.models.use_case import Base, Customer
    from backend.services import document_provider
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setenv("SAIL_AZURE_DI_API_KEY", KEY)
    real_engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(real_engine)
    RealSession = sessionmaker(bind=real_engine)
    seed = RealSession()
    seed.add(Customer(id=1, name="Worker Customer"))
    seed.add(SystemConfig(category="documents", key="provider", value_type="string",
                          string_value=PROVIDER_AZURE, is_active=1))
    seed.add(SystemConfig(category="documents", key="azure_endpoint", value_type="string",
                          string_value=ENDPOINT, is_active=1))
    seed.commit()
    kid = cks.create_customer_knowledge(
        seed, customer_id=1, knowledge_type="file", file_name="w.pdf", file_data=b"%PDF w"
    ).id
    seed.close()

    mock = _Azure()
    built: list = []

    def _real_with_transport(db):
        conv = document_provider.build_converter(db)
        built.append((conv, db))
        conv._transport = httpx.MockTransport(mock)
        conv.poll_interval_seconds = 0.0
        return conv

    monkeypatch.setattr(cks, "build_converter", _real_with_transport)
    monkeypatch.setattr(cks, "get_worker_session", RealSession)
    cks.normalize_record(kid)  # db=None → the worker's own session

    assert len(built) == 1
    conv, session_used = built[0]
    assert isinstance(conv, AzureDocumentIntelligenceConverter)
    assert session_used is not None and session_used.get_bind() is real_engine
    probe = RealSession()
    row = probe.query(CKModel).filter(CKModel.id == kid).first()
    assert row.processing_status == "READY"
    assert row.processor == "azure_document_intelligence"
    probe.close()
    real_engine.dispose()


# ----------------------------------------------------------------------
# 16. A construction-time config error lands on the record (worker path)
# ----------------------------------------------------------------------


def test_worker_http_env_endpoint_marks_record_invalid_configuration(tmp_path, monkeypatch):
    """A non-https ENV endpoint (never checked by the admin PUT) makes the
    converter constructor raise; the worker records it as FAILED
    invalid_configuration instead of leaving the upload in PROCESSING."""
    from datetime import datetime, timezone

    import backend.services.customer_knowledge_service as cks
    from backend.models.collaboration import SystemConfig
    from backend.models.customer_knowledge import CustomerKnowledge as CKModel
    from backend.models.use_case import Base, Customer
    from backend.services import document_provider
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    monkeypatch.setenv("SAIL_AZURE_DI_ENDPOINT", "http://insecure.example.test")
    monkeypatch.setenv("SAIL_AZURE_DI_API_KEY", KEY)
    real_engine = create_engine(
        f"sqlite:///{tmp_path / 'worker.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(real_engine)
    RealSession = sessionmaker(bind=real_engine)
    seed = RealSession()
    seed.add(Customer(id=1, name="Worker Customer"))
    seed.add(SystemConfig(category="documents", key="provider", value_type="string",
                          string_value=PROVIDER_AZURE, is_active=1))
    # Seeded directly in PROCESSING (as an upload awaiting the worker) so the
    # suite's inline normalization at create time does not pre-empt the job.
    record = CKModel(customer_id=1, knowledge_type="file", file_name="w.pdf",
                     file_data=b"%PDF w", uploaded_at=datetime.now(timezone.utc),
                     processing_status="PROCESSING")
    seed.add(record)
    seed.commit()
    kid = record.id
    seed.close()

    # The real factory (the suite autouse-patches it with a Docling fake).
    monkeypatch.setattr(cks, "build_converter", document_provider.build_converter)
    monkeypatch.setattr(cks, "get_worker_session", RealSession)
    cks.normalize_record(kid)  # db=None → the worker's own session

    probe = RealSession()
    row = probe.query(CKModel).filter(CKModel.id == kid).first()
    assert row.processing_status != "PROCESSING"
    assert row.processing_status == "FAILED"
    assert row.processing_error_kind == "invalid_configuration"
    assert "HTTPS" in row.processing_error
    assert row.file_data == b"%PDF w"
    probe.close()
    real_engine.dispose()


# ----------------------------------------------------------------------
# 13. Admin surface /api/admin/config/documents
# ----------------------------------------------------------------------


@pytest.fixture()
def _auth_lookup(db_session):
    """Point the real JWT user lookup at the shared test session."""
    from backend.models.use_case import User

    from backend import auth as auth_mod

    bind = db_session.get_bind()
    shared_engine = getattr(bind, "engine", bind)

    def _lookup(username):
        user = db_session.query(User).filter(User.username == username).first()
        if not (user and user.is_active):
            return None
        return {"username": user.username, "email": user.email,
                "display_name": user.display_name, "department": user.department,
                "is_admin": user.is_admin, "role": user.role, "user_id": user.id}

    with patch.object(auth_mod, "_get_user_by_username", _lookup), \
         patch.object(auth_mod, "create_engine", lambda *a, **k: shared_engine):
        yield


@pytest.fixture()
def admin_auth(db_session, _auth_lookup):
    from backend.auth import create_access_token

    token = create_access_token({"sub": "admin", "is_admin": True})
    return {"Authorization": f"Bearer {token}"}


class TestDocumentsAdminSurface:
    @pytest.fixture(autouse=True)
    def _cleanup(self, client, admin_auth, monkeypatch):
        monkeypatch.delenv("SAIL_AZURE_DI_API_KEY", raising=False)
        monkeypatch.delenv("SAIL_AZURE_DI_ENDPOINT", raising=False)
        yield
        for key in ("provider", "azure_endpoint", "azure_timeout_seconds",
                    "azure_ssl_verify", "azure_ssl_ca_bundle"):
            client.delete(f"/api/admin/config/category/documents/{key}", headers=admin_auth)

    def test_non_admin_is_403(self, client, db_session):
        from backend.auth import create_access_token
        from backend.models.use_case import User

        db_session.add(User(username="member", email="member@test.local",
                            hashed_password=_FAKE_BCRYPT_HASH, display_name="Member",
                            is_admin=0, approved=1, is_active=1))
        db_session.commit()
        headers = {"Authorization": f"Bearer {create_access_token({'sub': 'member', 'is_admin': False})}"}
        assert client.get("/api/admin/config/documents", headers=headers).status_code == 403
        assert client.put("/api/admin/config/documents", json={},
                          headers=headers).status_code == 403

    def test_admin_get_defaults(self, client, admin_auth):
        r = client.get("/api/admin/config/documents", headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == "docling"
        assert body["api_key_configured"] is False
        assert "api_key" not in body

    def test_put_bogus_provider_is_422(self, client, admin_auth):
        r = client.put("/api/admin/config/documents", json={"provider": "bogus"}, headers=admin_auth)
        assert r.status_code == 422
        assert r.json()["detail"] == "provider must be one of: docling, azure_document_intelligence"

    def test_put_http_endpoint_is_422(self, client, admin_auth):
        r = client.put("/api/admin/config/documents",
                       json={"provider": PROVIDER_AZURE, "azure_endpoint": "http://x"},
                       headers=admin_auth)
        assert r.status_code == 422
        assert r.json()["detail"] == "azure_endpoint must be an HTTPS endpoint (https://)"

    def test_put_timeout_out_of_range_is_422(self, client, admin_auth):
        r = client.put("/api/admin/config/documents",
                       json={"azure_timeout_seconds": 0.5}, headers=admin_auth)
        assert r.status_code == 422
        assert r.json()["detail"] == "azure_timeout_seconds must be between 1 and 3600"

    def test_put_azure_persists_and_never_returns_key(self, client, admin_auth):
        r = client.put("/api/admin/config/documents",
                       json={"provider": PROVIDER_AZURE, "azure_endpoint": ENDPOINT,
                             "azure_timeout_seconds": 120, "api_key_configured": True},
                       headers=admin_auth)
        assert r.status_code == 200
        body = r.json()
        assert body["provider"] == PROVIDER_AZURE
        assert body["azure_endpoint"] == ENDPOINT
        assert body["api_key_configured"] is False  # env-derived, never from the body
        assert "api_key" not in body
        got = client.get("/api/admin/config/documents", headers=admin_auth).json()
        assert got["provider"] == PROVIDER_AZURE
        assert got["azure_endpoint"] == ENDPOINT
        assert got["azure_timeout_seconds"] == 120
        assert "api_key" not in got
        entries = client.get("/api/admin/config/category/documents", headers=admin_auth).json()["entries"]
        assert not any(e["key"] in ("api_key", "api_key_configured") for e in entries)


# ----------------------------------------------------------------------
# 14-15. Upload flow under provider=azure (inline seam)
# ----------------------------------------------------------------------


class TestAzureUploadFlow:
    @pytest.fixture()
    def azure(self, db_session, monkeypatch):
        """provider=azure configured in the DB; the real factory with a mock transport."""
        import backend.services.customer_knowledge_service as cks
        from backend.services import document_provider
        from backend.services.config_service import upsert_config_entry

        monkeypatch.setenv("SAIL_AZURE_DI_API_KEY", KEY)
        upsert_config_entry(db_session, "documents", "provider", PROVIDER_AZURE)
        upsert_config_entry(db_session, "documents", "azure_endpoint", ENDPOINT)
        _seed_customer_with_junction(db_session, customer_id=1)
        _seed_customer_with_junction(db_session, customer_id=2)
        mock = _Azure()

        def _real_with_transport(db):
            conv = document_provider.build_converter(db)
            assert isinstance(conv, AzureDocumentIntelligenceConverter)
            conv._transport = httpx.MockTransport(mock)
            conv.poll_interval_seconds = 0.0
            return conv

        monkeypatch.setattr(cks, "build_converter", _real_with_transport)
        return mock

    @staticmethod
    def _upload(db, customer_id: int, name: str, data: bytes):
        import backend.services.customer_knowledge_service as cks

        rec = cks.create_customer_knowledge(
            db, customer_id=customer_id, knowledge_type="file", file_name=name, file_data=data
        )
        cks.enqueue_normalization(rec.id, db=db)
        db.refresh(rec)
        return rec

    def test_pdf_ready_failure_preserves_original_and_isolates(self, db_session, azure):
        other = self._upload(db_session, 2, "other.pdf", b"%PDF other")
        assert other.processing_status == "READY"
        assert other.processor == "azure_document_intelligence"
        assert other.processor_version == "prebuilt-layout/2024-11-30"
        assert other.normalized_content == TABLE_MD
        other_snapshot = (other.processing_status, other.normalized_content, other.file_data)

        azure.polls = [httpx.Response(200, json={
            "status": "failed",
            "analyzeResult": {"errors": [{"code": "DocumentAnalysisFailed", "message": "boom"}]},
        })]
        failed = self._upload(db_session, 1, "broken.pdf", b"%PDF-1.4 broken")
        assert failed.processing_status == "FAILED"
        assert failed.processing_error_kind == "conversion_failure"
        assert "boom" in failed.processing_error
        assert failed.file_data == b"%PDF-1.4 broken"

        db_session.refresh(other)
        assert (other.processing_status, other.normalized_content, other.file_data) == other_snapshot

    def test_unsupported_for_azure_names_provider(self, db_session, azure):
        rec = self._upload(db_session, 1, "costs.csv", b"a,b\n1,2\n")
        assert rec.processing_status == "FAILED"
        assert rec.processing_error_kind == "unsupported_document"
        assert "azure_document_intelligence does not accept this format" in rec.processing_error
        assert "switch the provider in Application Settings" in rec.processing_error
        assert rec.file_data == b"a,b\n1,2\n"
        assert azure.requests == []

    def test_markdown_upload_skips_azure(self, db_session, azure):
        rec = self._upload(db_session, 1, "notes.md", b"# Notes\r\n\r\nline\r\n")
        assert rec.processing_status == "READY"
        assert rec.processor == "markdown-native"
        assert rec.normalized_content == "# Notes\n\nline\n"
        assert azure.requests == []
