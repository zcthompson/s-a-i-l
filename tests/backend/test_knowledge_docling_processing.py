"""Customer Knowledge Docling processing flow — K2 backend tests.

Covers CHANGELOG 0.1.1 item 17 (backend):
PDF conversion success, CSV conversion success, Markdown direct
normalization (no Docling round-trip), Docling unavailable, timeout,
Docling ``failure``, ``partial_success`` (retain + warning), empty
Markdown, reprocessing a failed document, customer authorization
boundaries, deletion, and retention of originals after conversion.

Docling is mocked for all automated runs (the conftest default mock;
per-test failure classes re-patch ``cks.DoclingService``). The test
suite runs normalization INLINE (SAIL_KNOWLEDGE_ASYNC=0, same
code path as the production worker minus the thread hop); one test
exercises the real worker-thread path explicitly. One optional live
integration test (env-flag gated, skipped by default) targets the
configured Docling host.
"""

import os
import time

import pytest
from backend.models.customer_knowledge import CustomerKnowledge as CKModel

from tests.backend.test_customer_knowledge import (
    _admin_headers,
    _non_admin_headers,
    _seed_customer_with_junction,
)


def _csv_bytes(n: int = 1) -> bytes:
    rows = ["software,version,status"]
    for i in range(n):
        rows.append(f"Software{i},1.{i},active")
    return ("\n".join(rows) + "\n").encode()


def _upload(client, db_session, filename: str, data: bytes, customer_id: int = 1, headers: dict | None = None):
    return client.post(
        "/api/customer-knowledge/",
        files={"file": (filename, data, "application/octet-stream")},
        data={"customer_id": str(customer_id)},
        headers=headers or _admin_headers(db_session),
    )


def _record(db_session, knowledge_id: int) -> CKModel:
    return db_session.query(CKModel).filter(CKModel.id == knowledge_id).first()


def _detail(client, headers, knowledge_id: int):
    return client.get(f"/api/customer-knowledge/{knowledge_id}", headers=headers)


# ----------------------------------------------------------------------
# Upload → processing → READY (mocked Docling success)
# ----------------------------------------------------------------------


class TestUploadProcessing:
    def test_pdf_upload_reaches_ready_with_normalized_markdown(self, client, db_session):
        """PDF goes through Docling; upload returns once stored + processing
        initiated; the record reaches READY with persisted Markdown and the
        original PDF intact (items 2, 3, 9, 14)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        pdf_bytes = b"%PDF-1.4 fake engineering architecture pdf"

        r = _upload(client, db_session, "engineering-architecture.pdf", pdf_bytes)
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["processing_status"] == "PROCESSING"
        kid = body["knowledge_id"]

        rec = _record(db_session, kid)
        assert rec is not None
        assert rec.processing_status == "READY"
        assert rec.processor == "docling"
        assert rec.normalized_format == "markdown"
        assert rec.normalized_content and "Normalized" in rec.normalized_content
        assert rec.processed == 1
        assert rec.processed_at is not None
        # Original retained, unchanged (item 14)
        assert rec.file_data == pdf_bytes
        assert rec.file_name == "engineering-architecture.pdf"
        assert rec.original_content_type == "application/pdf"
        assert rec.original_storage_path == f"database:customer_knowledge.file_data:{kid}"
        # Detail endpoint carries the new contract
        d = _detail(client, _admin_headers(db_session), kid).json()
        assert d["processing_status"] == "READY"
        assert d["original_filename"] == "engineering-architecture.pdf"
        assert d["normalized_content_present"] is True
        assert "file_data" not in d
        assert "normalized_content" not in d

    def test_csv_upload_reaches_ready(self, client, db_session):
        """CSV goes through Docling into a common Markdown representation
        (item 8: no special downstream tabular handling)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        r = _upload(client, db_session, "cloud-cost-breakdown.csv", _csv_bytes(3))
        assert r.status_code == 200
        kid = r.json()["knowledge_id"]
        rec = _record(db_session, kid)
        assert rec.processing_status == "READY"
        assert rec.processor == "docling"
        assert rec.normalized_content
        assert rec.file_data == _csv_bytes(3)

    def test_markdown_upload_is_ready_without_docling(self, client, db_session):
        """.md uploads are already canonical: no Docling round-trip
        (item 8). Encoding/line-endings normalized; Ready."""
        _seed_customer_with_junction(db_session, customer_id=1)
        from unittest.mock import patch as _p

        import backend.services.customer_knowledge_service as cks

        calls = []

        class _NoCallDocling:
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
                calls.append(a)
                raise AssertionError("Docling must NOT be called for .md uploads")

        raw = "# GenAI Pilot Readout\r\n\r\nline one\r\nline two\r\n\r\n\r\n"
        with _p.object(cks, "build_converter", lambda db: _NoCallDocling()):
            r = _upload(client, db_session, "genai-pilot-readout.md", raw.encode("utf-8"))
        assert r.status_code == 200
        assert calls == []
        kid = r.json()["knowledge_id"]
        rec = _record(db_session, kid)
        assert rec.processing_status == "READY"
        assert rec.processor == "markdown-native"
        assert rec.normalized_content == "# GenAI Pilot Readout\n\nline one\nline two\n"
        assert rec.file_data == raw.encode("utf-8")  # original preserved

    def test_markdown_upload_latin1_normalized(self, client, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        r = _upload(client, db_session, "notes.md", "café notes".encode("latin-1"))
        assert r.status_code == 200
        rec = _record(db_session, r.json()["knowledge_id"])
        assert rec.processing_status == "READY"
        assert rec.normalized_content == "café notes\n"

    def test_unsupported_extension_fails_without_losing_file(self, client, db_session):
        """A format Docling rejects (observed live: 'File format not
        allowed') → FAILED with the diagnostic; original retained
        (items 13, 14)."""
        _seed_customer_with_junction(db_session, customer_id=1)
        r = _upload(client, db_session, "archive.zip", b"PK fake zip bytes")
        assert r.status_code == 200
        rec = _record(db_session, r.json()["knowledge_id"])
        assert rec.processing_status == "FAILED"
        assert rec.processing_error_kind == "unsupported_document"
        assert "archive.zip" in rec.processing_error
        assert rec.file_data == b"PK fake zip bytes"
        assert rec.processed == 0

    def test_upload_response_excludes_binary(self, client, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        r = _upload(client, db_session, "a.pdf", b"%PDF data")
        body = r.json()
        assert "file_data" not in body
        assert body["knowledge_id"]


# ----------------------------------------------------------------------
# Docling failure classes (item 13) — re-patch cks.DoclingService
# ----------------------------------------------------------------------


def _patch_docling(db, factory):
    """Patch the service-module DoclingService reference for one record."""
    from unittest.mock import patch as _p

    import backend.services.customer_knowledge_service as cks

    class _Doc:
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

        def convert_to_markdown(self, file_bytes, filename, content_type="application/octet-stream"):
            return factory(file_bytes, filename)

        def health(self):
            return {"status": "ok"}

    return _p.object(cks, "build_converter", lambda db: _Doc())


class TestDoclingFailureClasses:
    @pytest.fixture(autouse=True)
    def _seed(self, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        yield

    def _make_uploaded(self, db, filename: str, data: bytes) -> int:
        from backend.services.customer_knowledge_service import (
            create_customer_knowledge,
        )

        rec = create_customer_knowledge(
            db, customer_id=1, knowledge_type="file", file_name=filename, file_data=data
        )
        return rec.id

    @pytest.fixture
    def db(self, db_session):
        return db_session

    def test_docling_unavailable_is_failed_not_lost(self, client, db):
        from backend.services.customer_knowledge_service import normalize_record
        from backend.services.docling_service import DoclingError

        def fail(file_bytes, filename):
            raise DoclingError("docling_unavailable", "Docling unreachable at http://x:5001")

        kid = self._make_uploaded(db, "a.pdf", b"%PDF-1.4 data")
        with _patch_docling(db, fail):
            normalize_record(kid, db=db)
        rec = _record(db, kid)
        assert rec.processing_status == "FAILED"
        assert rec.processing_error_kind == "docling_unavailable"
        assert rec.file_data == b"%PDF-1.4 data"  # store-first: never lost
        assert rec.processed == 0

    def test_conversion_timeout_is_failed(self, client, db):
        from backend.services.customer_knowledge_service import normalize_record
        from backend.services.docling_service import DoclingError

        def fail(file_bytes, filename):
            raise DoclingError("conversion_timeout", f"Docling conversion of '{filename}' timed out after 600s")

        kid = self._make_uploaded(db, "big.pdf", b"%PDF big")
        with _patch_docling(db, fail):
            normalize_record(kid, db=db)
        rec = _record(db, kid)
        assert rec.processing_status == "FAILED"
        assert rec.processing_error_kind == "conversion_timeout"

    def test_connection_timeout_is_failed(self, client, db):
        from backend.services.customer_knowledge_service import normalize_record
        from backend.services.docling_service import DoclingError

        def fail(file_bytes, filename):
            raise DoclingError("connection_timeout", "Connection timed out")

        kid = self._make_uploaded(db, "a.pdf", b"%PDF")
        with _patch_docling(db, fail):
            normalize_record(kid, db=db)
        rec = _record(db, kid)
        assert rec.processing_error_kind == "connection_timeout"

    def test_docling_failure_status_is_failed(self, client, db):
        from backend.services.customer_knowledge_service import normalize_record
        from backend.services.docling_service import DoclingError

        def fail(file_bytes, filename):
            raise DoclingError("conversion_failure", "Document conversion failed: OCR backend error")

        kid = self._make_uploaded(db, "a.pdf", b"%PDF")
        with _patch_docling(db, fail):
            normalize_record(kid, db=db)
        rec = _record(db, kid)
        assert rec.processing_status == "FAILED"
        assert rec.processing_error_kind == "conversion_failure"
        assert "OCR backend error" in rec.processing_error

    def test_empty_markdown_is_failed(self, client, db):
        from backend.services.customer_knowledge_service import normalize_record
        from backend.services.docling_service import DoclingError

        def fail(file_bytes, filename):
            raise DoclingError("empty_result", "Docling produced no Markdown content for 'a.pdf'")

        kid = self._make_uploaded(db, "a.pdf", b"%PDF")
        with _patch_docling(db, fail):
            normalize_record(kid, db=db)
        rec = _record(db, kid)
        assert rec.processing_status == "FAILED"
        assert rec.processing_error_kind == "empty_result"
        assert rec.normalized_content is None

    def test_partial_success_retains_output_with_warning(self, client, db):
        from backend.services.customer_knowledge_service import normalize_record
        from backend.services.docling_service import DoclingConversionResult

        def ok(file_bytes, filename):
            return DoclingConversionResult(
                markdown="# partial\n",
                status="partial_success",
                partial=True,
                processing_time_seconds=0.3,
                warnings=["table on page 2 could not be reconstructed"],
            )

        kid = self._make_uploaded(db, "a.pdf", b"%PDF")
        with _patch_docling(db, ok):
            normalize_record(kid, db=db)
        rec = _record(db, kid)
        assert rec.processing_status == "READY"  # retained, not failed
        assert rec.normalized_content == "# partial\n"
        assert rec.processed == 1
        assert rec.processing_error and "Partial conversion" in rec.processing_error

    def test_reprocess_recovers_after_docling_outage(self, client, db):
        """A FAILED document (Docling outage) recovers via Reprocess once
        Docling is available again (item 13). The original bytes are
        reused; the normalized derivative is replaced; the original is
        untouched (item 11)."""
        from backend.services.customer_knowledge_service import (
            normalize_record,
            reprocess_customer_knowledge,
        )
        from backend.services.docling_service import (
            DoclingConversionResult,
            DoclingError,
        )

        def down(file_bytes, filename):
            raise DoclingError("docling_unavailable", "Docling unreachable")

        def up(file_bytes, filename):
            return DoclingConversionResult(
                markdown=f"# recovered {filename}\n",
                status="success",
                partial=False,
                processing_time_seconds=0.05,
            )

        original = b"%PDF-1.4 outage doc"
        kid = self._make_uploaded(db, "outage.pdf", original)
        with _patch_docling(db, down):
            normalize_record(kid, db=db)
        assert _record(db, kid).processing_status == "FAILED"

        # Reprocess with Docling back up (the `up` factory simulates the
        # recovered service); inline mode completes synchronously.
        with _patch_docling(db, up):
            out = reprocess_customer_knowledge(db, kid, 1)
        assert out is not None
        updated = _record(db, kid)
        assert updated.processing_status == "READY"
        assert updated.processor == "docling"
        assert updated.normalized_content == "# recovered outage.pdf\n"
        assert updated.file_data == original  # original never replaced
        assert updated.processing_error is None

    def test_reprocess_in_flight_returns_record(self, db):
        from backend.services.customer_knowledge_service import (
            reprocess_customer_knowledge,
        )

        kid = self._make_uploaded(db, "a.pdf", b"%PDF")
        rec = _record(db, kid)
        rec.processing_status = "PROCESSING"
        db.commit()
        out = reprocess_customer_knowledge(db, kid, 1)
        assert out is not None
        assert out.processing_status == "PROCESSING"

    def test_normalize_already_ready_is_noop(self, client, db):
        """Duplicate worker jobs must not re-convert a READY document."""
        from unittest.mock import patch as _p

        import backend.services.customer_knowledge_service as cks
        from backend.services.docling_service import DoclingConversionResult

        calls = []

        class _Counting:
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

            def convert_to_markdown(self, file_bytes, filename, content_type="application/octet-stream"):
                calls.append(filename)
                return DoclingConversionResult(
                    markdown="# m\n", status="success", partial=False, processing_time_seconds=0.01
                )

        kid = self._make_uploaded(db, "a.pdf", b"%PDF")
        with _p.object(cks, "build_converter", lambda db: _Counting()):
            cks.normalize_record(kid, db=db)
            cks.normalize_record(kid, db=db)
        assert len(calls) == 1
        assert _record(db, kid).processing_status == "READY"


# ----------------------------------------------------------------------
# Content / reprocess / download endpoints
# ----------------------------------------------------------------------


class TestKnowledgeContentEndpoints:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        yield

    def _ready_record(self, client, db_session, filename="doc.pdf", data=b"%PDF-1.4 x"):
        r = _upload(client, db_session, filename, data)
        assert r.status_code == 200
        return r.json()["knowledge_id"]

    def test_content_ready_returns_markdown(self, client, db_session):
        kid = self._ready_record(client, db_session)
        h = _admin_headers(db_session)
        r = client.get(f"/api/customer-knowledge/{kid}/content", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["normalized_format"] == "markdown"
        assert "Normalized" in body["normalized_content"]
        assert body["processor"] == "docling"

    def test_content_not_ready_409(self, client, db_session):
        from unittest.mock import patch as _p

        import backend.services.customer_knowledge_service as cks
        from backend.services.docling_service import DoclingError

        def down(file_bytes, filename):
            raise DoclingError("docling_unavailable", "down")

        class _Doc:
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

            def convert_to_markdown(self, file_bytes, filename, content_type="application/octet-stream"):
                return down(file_bytes, filename)

            def health(self):
                return {"status": "ok"}

        with _p.object(cks, "build_converter", lambda db: _Doc()):
            r = _upload(client, db_session, "doc.pdf", b"%PDF")
        kid = r.json()["knowledge_id"]
        assert _record(db_session, kid).processing_status == "FAILED"
        got = client.get(f"/api/customer-knowledge/{kid}/content", headers=_admin_headers(db_session))
        assert got.status_code == 409
        assert "FAILED" in got.json()["detail"]

    def test_reprocess_endpoint_roundtrip(self, client, db_session):
        from unittest.mock import patch as _p

        import backend.services.customer_knowledge_service as cks
        from backend.services.docling_service import (
            DoclingError,
        )

        def down(file_bytes, filename):
            raise DoclingError("docling_unavailable", "Docling unreachable")

        class _Down:
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

            def convert_to_markdown(self, file_bytes, filename, content_type="application/octet-stream"):
                return down(file_bytes, filename)

            def health(self):
                return {"status": "ok"}

        h = _admin_headers(db_session)
        with _p.object(cks, "build_converter", lambda db: _Down()):
            r = _upload(client, db_session, "doc.pdf", b"%PDF-1.4 re")
        kid = r.json()["knowledge_id"]
        assert _record(db_session, kid).processing_status == "FAILED"

        # Reprocess while Docling is (default-mock) up → READY.
        # In test (inline) mode the response is already READY; in production
        # (async) mode it is PROCESSING and the UI polls to READY.
        rr = client.post(f"/api/customer-knowledge/{kid}/reprocess", headers=h)
        assert rr.status_code == 200
        assert rr.json()["processing_status"] in ("PROCESSING", "READY")
        rec = _record(db_session, kid)
        assert rec.processing_status == "READY"
        assert rec.normalized_content
        assert rec.file_data == b"%PDF-1.4 re"

    def test_reprocess_404_missing(self, client, db_session):
        h = _admin_headers(db_session)
        rr = client.post("/api/customer-knowledge/9999/reprocess", headers=h)
        assert rr.status_code == 404

    def test_download_returns_original_bytes(self, client, db_session):
        kid = self._ready_record(client, db_session, data=b"%PDF-1.4 download me")
        h = _admin_headers(db_session)
        r = client.get(f"/api/customer-knowledge/{kid}/download", headers=h)
        assert r.status_code == 200
        assert r.content == b"%PDF-1.4 download me"
        assert r.headers["content-type"] == "application/pdf"
        assert 'attachment; filename="doc.pdf"' in r.headers["content-disposition"]

    def test_download_404_missing(self, client, db_session):
        h = _admin_headers(db_session)
        assert client.get("/api/customer-knowledge/9999/download", headers=h).status_code == 404


# ----------------------------------------------------------------------
# Authorization boundaries (charter §3 — CustomerUser + admin bypass)
# ----------------------------------------------------------------------


class TestKnowledgeProcessingAuth:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        _seed_customer_with_junction(db_session, customer_id=2)
        yield

    def test_member_cannot_read_other_customer_content(self, client, db_session):
        h = _non_admin_headers(db_session, customer_id=1)
        r = _upload(client, db_session, "c2.pdf", b"%PDF secret", customer_id=2, headers=_admin_headers(db_session))
        kid = r.json()["knowledge_id"]
        got = client.get(f"/api/customer-knowledge/{kid}/content", headers=h)
        assert got.status_code == 404  # out-of-scope → 404 (not 403 — no leak)

    def test_member_cannot_reprocess_other_customer(self, client, db_session):
        h = _non_admin_headers(db_session, customer_id=1)
        r = _upload(client, db_session, "c2.pdf", b"%PDF secret", customer_id=2, headers=_admin_headers(db_session))
        kid = r.json()["knowledge_id"]
        rr = client.post(f"/api/customer-knowledge/{kid}/reprocess", headers=h)
        assert rr.status_code == 404

    def test_member_cannot_download_other_customer(self, client, db_session):
        h = _non_admin_headers(db_session, customer_id=1)
        r = _upload(client, db_session, "c2.pdf", b"%PDF secret", customer_id=2, headers=_admin_headers(db_session))
        kid = r.json()["knowledge_id"]
        got = client.get(f"/api/customer-knowledge/{kid}/download", headers=h)
        assert got.status_code == 404

    def test_member_can_read_own_customer_content(self, client, db_session):
        h = _non_admin_headers(db_session, customer_id=1)
        r = _upload(client, db_session, "c1.md", b"# mine\n", customer_id=1, headers=h)
        kid = r.json()["knowledge_id"]
        got = client.get(f"/api/customer-knowledge/{kid}/content", headers=h)
        assert got.status_code == 200
        assert got.json()["normalized_content"] == "# mine\n"

    def test_unauthenticated_content_401(self, client, db_session):
        r = _upload(client, db_session, "a.md", b"# x\n")
        kid = r.json()["knowledge_id"]
        got = client.get(f"/api/customer-knowledge/{kid}/content")
        assert got.status_code == 401


# ----------------------------------------------------------------------
# Deletion + original retention after conversion
# ----------------------------------------------------------------------


class TestDeletionAndRetention:
    @pytest.fixture(autouse=True)
    def _setup(self, db_session):
        _seed_customer_with_junction(db_session, customer_id=1)
        yield

    def test_delete_removes_original_and_normalized(self, client, db_session):
        r = _upload(client, db_session, "g.pdf", b"%PDF-1.4 gone")
        kid = r.json()["knowledge_id"]
        assert _record(db_session, kid).processing_status == "READY"
        h = _admin_headers(db_session)
        d = client.delete(f"/api/customer-knowledge/{kid}", headers=h)
        assert d.status_code == 200
        assert _record(db_session, kid) is None
        got = client.get(f"/api/customer-knowledge/{kid}", headers=h)
        assert got.status_code == 404

    def test_ready_document_keeps_original_after_conversion(self, client, db_session):
        data = b"%PDF-1.4 retained"
        r = _upload(client, db_session, "keep.pdf", data)
        rec = _record(db_session, r.json()["knowledge_id"])
        assert rec.processing_status == "READY"
        assert rec.file_data == data  # item 14: never deleted after conversion

    def test_processed_mirror_tracks_readiness(self, client, db_session):
        r = _upload(client, db_session, "m.pdf", b"%PDF")
        rec = _record(db_session, r.json()["knowledge_id"])
        assert rec.processed == 1
        from backend.services.customer_knowledge_service import (
            update_customer_knowledge,
        )

        update_customer_knowledge(db_session, rec.id, 1, {"processed": False})
        assert rec.processed == 0


# ----------------------------------------------------------------------
# Worker-thread path (production dispatch)
# ----------------------------------------------------------------------


class TestWorkerThreadPath:
    def test_worker_thread_normalizes_via_own_session(self, db_session):
        """One test exercises the REAL worker thread + real own-session
        commits (the production dispatch path).

        The conftest forces a single StaticPool shared connection (a test
        artifact for in-fixture consistency); a second session committing on
        it would destroy the fixture savepoint — the documented v0.0.67 flake
        class. Production ``get_session()`` instead builds a real
        multi-connection SQLite engine, so the worker's own-session commits
        are safe. This test isolates the worker from the fixture by patching
        the worker's session factory to a real temp-file engine and seeding
        that engine directly, then enqueuing (async=1) and polling a fresh
        session on the same engine for READY.
        """
        import os as _os
        import tempfile
        import time as _time
        from unittest.mock import patch as _mp

        import backend.services.customer_knowledge_service as cks
        from backend.models.use_case import Base, Customer
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        tmp_db = os.path.join(tempfile.mkdtemp(), "worker_test.db")
        real_engine = create_engine(
            f"sqlite:///{tmp_db}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(real_engine)
        RealSession = sessionmaker(bind=real_engine)

        seed = RealSession()
        if not seed.query(Customer).filter(Customer.id == 1).first():
            seed.add(Customer(id=1, name="Worker Customer"))
            seed.commit()
        seed.close()

        # The worker's own-session factory points at the real engine.
        with _mp.object(cks, "get_worker_session", RealSession):
            # Create an uploaded record on the real engine (via the real
            # service function, which uses its session arg).
            rec = cks.create_customer_knowledge(
                seed_session := RealSession(),
                customer_id=1,
                knowledge_type="file",
                file_name="worker.pdf",
                file_data=b"%PDF-1.4 threaded",
            )
            kid = rec.id  # capture before the session closes (detached)
            seed_session.close()

            old = _os.environ.get("SAIL_KNOWLEDGE_ASYNC")
            _os.environ["SAIL_KNOWLEDGE_ASYNC"] = "1"
            try:
                cks.enqueue_normalization(kid)  # own-session flip + worker
                deadline = _time.monotonic() + 30
                row = None
                row_data = None
                while _time.monotonic() < deadline:
                    probe = RealSession()
                    row = (
                        probe.query(CKModel).filter(CKModel.id == kid).first()
                    )
                    if row is not None and row.processing_status in (
                        "READY", "FAILED"
                    ):
                        # Capture values while the session is open.
                        row_data = (
                            row.processing_status,
                            row.processor,
                            row.file_data,
                            row.normalized_content,
                            row.processing_error,
                        )
                    probe.close()
                    if row_data is not None:
                        break
                    _time.sleep(0.1)
            finally:
                if old is None:
                    _os.environ.pop("SAIL_KNOWLEDGE_ASYNC", None)
                else:
                    _os.environ["SAIL_KNOWLEDGE_ASYNC"] = old

        assert row is not None
        assert row_data is not None
        status, processor, file_data, normalized, proc_error = row_data
        assert status == "READY", f"worker left record at {status}: {proc_error}"
        assert processor == "docling"
        assert file_data == b"%PDF-1.4 threaded"
        assert normalized and "Normalized" in normalized
        real_engine.dispose()


# ----------------------------------------------------------------------
# Optional live integration test (env-flag gated; skipped by default)
# ----------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("SAIL_DOCLING_INTEGRATION") != "1",
    reason="set SAIL_DOCLING_INTEGRATION=1 to run the live Docling integration test",
)
def test_live_docling_csv_conversion(client, db_session):
    """Against the real configured Docling host (dev LAN): CSV upload →
    READY with a Markdown table in the normalized content."""
    _seed_customer_with_junction(db_session, customer_id=1)
    r = _upload(client, db_session, "live-inventory.csv", _csv_bytes(2))
    assert r.status_code == 200
    kid = r.json()["knowledge_id"]
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        rec = _record(db_session, kid)
        if rec is not None and rec.processing_status in ("READY", "FAILED"):
            break
        time.sleep(2)
    rec = _record(db_session, kid)
    assert rec.processing_status == "READY", rec.processing_error
    assert rec.processor == "docling"
    assert "| " in (rec.normalized_content or "")
    assert rec.processing_time_seconds and rec.processing_time_seconds > 0
