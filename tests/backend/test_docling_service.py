"""DoclingService unit tests — mocked httpx transport (no Docling container).

Covers the conversion contract (PLAN.md part 43 / CHANGELOG 0.1.1
items 1, 5, 6, 13): status-authoritative parsing (HTTP 200 is NOT success),
the failure classes (unavailable / timeouts / unsupported / malformed /
empty / failure / partial_success), API-key header behavior, and the
Markdown short-circuit normalization.
"""

import httpx
import pytest
from backend.services.docling_service import (
    DoclingConversionResult,
    DoclingError,
    DoclingService,
    is_docling_supported,
    is_markdown_upload,
    normalize_markdown_text,
)

SERVER = "http://docling.test:5001"


def _docling_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _success_payload(md: str) -> dict:
    return {
        "document": {
            "filename": "probe.csv",
            "md_content": md,
            "json_content": None,
            "html_content": None,
            "text_content": None,
            "doctags_content": None,
        },
        "status": "success",
        "errors": [],
        "processing_time": 0.05098511604592204,
        "timings": {},
    }


def _service(handler) -> DoclingService:
    return DoclingService(server_url=SERVER, transport=httpx.MockTransport(handler))


# ----------------------------------------------------------------------
# Success paths
# ----------------------------------------------------------------------


def test_csv_conversion_success_returns_markdown():
    # The exact shape observed from the live Docling probe (2026-09-10).
    md = (
        "| software                   |   version | status   |\n"
        "|----------------------------|-----------|----------|\n"
        "| Veeem Placeholder |      12.0 | active   |\n"
    )
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["content_type"] = request.headers.get("content-type", "")
        return _docling_response(_success_payload(md))

    result = _service(handler).convert_to_markdown(
        b"software,version\nVeeam,12.0", "probe.csv", "text/csv"
    )
    assert isinstance(result, DoclingConversionResult)
    assert result.markdown == md
    assert result.status == "success"
    assert result.partial is False
    assert result.processing_time_seconds == pytest.approx(0.05098511604592204)
    assert seen["method"] == "POST"
    assert seen["url"] == f"{SERVER}/v1/convert/file"
    assert seen["content_type"].startswith("multipart/form-data")


def test_no_api_key_sends_no_auth_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return _docling_response(_success_payload("# ok\n"))

    _service(handler).convert_to_markdown(b"x", "a.pdf", "application/pdf")


def test_api_key_sends_bearer_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sekrit"
        return _docling_response(_success_payload("# ok\n"))

    svc = DoclingService(server_url=SERVER, api_key="sekrit", transport=httpx.MockTransport(handler))
    svc.convert_to_markdown(b"x", "a.pdf", "application/pdf")


# ----------------------------------------------------------------------
# Status-authoritative parsing (item 6)
# ----------------------------------------------------------------------


def test_partial_success_retains_output_with_warning():
    payload = _success_payload("| a | b |\n|---|---|\n| 1 | 2 |\n")
    payload["status"] = "partial_success"
    payload["errors"] = [
        {"component_type": "converter", "module_name": "tables", "error_message": "table on page 2 could not be reconstructed"}
    ]
    result = _service(lambda r: _docling_response(payload)).convert_to_markdown(
        b"x", "a.pdf", "application/pdf"
    )
    assert result.partial is True
    assert result.status == "partial_success"
    assert any("page 2" in w for w in result.warnings)
    assert result.markdown  # retained


def test_skipped_is_a_failure_with_docling_message():
    payload = {
        "document": {
            "filename": "pyproject.toml",
            "md_content": None,
            "json_content": None,
            "html_content": None,
            "text_content": None,
            "doctags_content": None,
        },
        "status": "skipped",
        "errors": [
            {
                "component_type": "user_input",
                "module_name": "",
                "error_message": "File format not allowed: pyproject.toml",
            }
        ],
        "processing_time": 0.0,
    }
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: _docling_response(payload)).convert_to_markdown(
            b"x", "pyproject.toml", "text/x-toml"
        )
    assert exc.value.kind == "unsupported_document"
    assert "File format not allowed" in exc.value.message
    assert exc.value.docling_errors


def test_failure_status_is_conversion_failure():
    payload = _success_payload("# x\n")
    payload["status"] = "failure"
    payload["errors"] = [{"component_type": "pipeline", "module_name": "ocr", "error_message": "OCR backend error"}]
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: _docling_response(payload)).convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "conversion_failure"
    assert "OCR backend error" in exc.value.message


def test_unknown_status_is_malformed():
    payload = _success_payload("# x\n")
    payload["status"] = "weird_new_status"
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: _docling_response(payload)).convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "malformed_response"
    assert "weird_new_status" in exc.value.message


def test_empty_markdown_on_success_is_empty_result():
    payload = _success_payload("   \n")
    payload["errors"] = []
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: _docling_response(payload)).convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "empty_result"


def test_null_md_content_is_empty_result():
    payload = _success_payload("ignored")
    payload["document"]["md_content"] = None
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: _docling_response(payload)).convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "empty_result"


# ----------------------------------------------------------------------
# Transport failures (item 13)
# ----------------------------------------------------------------------


def test_connection_refused_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(DoclingError) as exc:
        _service(handler).convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "docling_unavailable"
    assert "docling.test:5001" in exc.value.message


def test_connect_timeout_class():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connect timeout", request=request)

    with pytest.raises(DoclingError) as exc:
        _service(handler).convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "connection_timeout"


def test_read_timeout_is_conversion_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    with pytest.raises(DoclingError) as exc:
        _service(handler).convert_to_markdown(b"x", "big.pdf", "application/pdf")
    assert exc.value.kind == "conversion_timeout"
    assert "big.pdf" in exc.value.message


def test_non_json_response_is_malformed():
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: httpx.Response(200, text="<html>bad gateway</html>")).convert_to_markdown(
            b"x", "a.pdf", "application/pdf"
        )
    assert exc.value.kind == "malformed_response"


def test_response_not_object_is_malformed():
    with pytest.raises(DoclingError) as exc:
        _service(lambda r: httpx.Response(200, json=["list", "not", "object"])).convert_to_markdown(
            b"x", "a.pdf", "application/pdf"
        )
    assert exc.value.kind == "malformed_response"


def test_unconfigured_url_is_unavailable():
    svc = DoclingService(server_url="")
    with pytest.raises(DoclingError) as exc:
        svc.convert_to_markdown(b"x", "a.pdf", "application/pdf")
    assert exc.value.kind == "docling_unavailable"
    assert "DOCLING_SERVER_URL" in exc.value.message


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------


def test_health_ok():
    svc = _service(lambda r: httpx.Response(200, json={"status": "ok"}))
    assert svc.health() == {"status": "ok"}


def test_health_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DoclingError) as exc:
        _service(handler).health()
    assert exc.value.kind == "docling_unavailable"


# ----------------------------------------------------------------------
# Markdown short-circuit (item 8)
# ----------------------------------------------------------------------


def test_markdown_extensions_short_circuit():
    assert is_markdown_upload("genai-pilot-readout.md")
    assert is_markdown_upload("notes.MARKDOWN")
    assert not is_markdown_upload("doc.pdf")
    assert not is_markdown_upload("noext")


def test_docling_supported_extensions():
    assert is_docling_supported("engineering-architecture.pdf")
    assert is_docling_supported("cloud-cost-breakdown.csv")
    assert is_docling_supported("slide deck.pptx")
    assert is_docling_supported("scan.tif")
    assert not is_docling_supported("genai-pilot-readout.md")
    assert not is_docling_supported("archive.zip")


def test_normalize_markdown_crlf_and_latin1():
    assert normalize_markdown_text(b"# Title\r\nline1\r\nline2\n\n\n") == "# Title\nline1\nline2\n"
    assert normalize_markdown_text("café".encode("latin-1")) == "café\n"


def test_normalize_markdown_empty_raises():
    with pytest.raises(DoclingError) as exc:
        normalize_markdown_text(b"   \n  \n")
    assert exc.value.kind == "empty_result"


@pytest.mark.parametrize('failure', ['connect', 'server'])
def test_transient_failure_retries_then_succeeds(monkeypatch, failure):
    calls = []
    monkeypatch.setattr('backend.services.docling_service.time.sleep', lambda _: None)

    def handler(request):
        calls.append(request)
        if len(calls) < 3:
            if failure == 'connect':
                raise httpx.ConnectError('not started', request=request)
            return httpx.Response(503)
        return _docling_response(_success_payload('# recovered'))

    assert _service(handler).convert_to_markdown(b'x', 'a.pdf').markdown == '# recovered'
    assert len(calls) == 3


def test_read_timeout_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('conversion still running', request=request)

    with pytest.raises(DoclingError) as exc:
        _service(handler).convert_to_markdown(b'x', 'a.pdf')
    assert exc.value.kind == 'conversion_timeout'
    assert len(calls) == 1


def test_connect_failure_grace_and_attempt_limit(monkeypatch):
    import backend.services.docling_service as module
    calls = []
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    monkeypatch.setattr(module, '_STARTED_AT', module.time.monotonic())

    def handler(request):
        calls.append(request)
        raise httpx.ConnectError('not started', request=request)

    with pytest.raises(DoclingError) as exc:
        _service(handler).convert_to_markdown(b'x', 'a.pdf')
    assert exc.value.kind == 'docling_unavailable'
    assert 'starting up' in str(exc.value)
    assert len(calls) == 3


def test_retry_budget_includes_backoff(monkeypatch):
    import backend.services.docling_service as module
    clock = [0.0]
    calls = []
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda duration: clock.__setitem__(0, clock[0] + duration))
    monkeypatch.setattr(module.random, 'uniform', lambda *_: 0)

    def handler(request):
        calls.append(request)
        clock[0] += 0.9
        return httpx.Response(503)

    service = DoclingService(server_url=SERVER, timeout_seconds=1, transport=httpx.MockTransport(handler))
    with pytest.raises(DoclingError) as exc:
        service.convert_to_markdown(b'x', 'a.pdf')
    assert exc.value.kind == 'conversion_timeout'
    assert len(calls) == 1 and clock[0] == pytest.approx(1)
