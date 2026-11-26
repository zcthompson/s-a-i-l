"""Provider-neutral document conversion seam for Customer Knowledge.

Customer Knowledge normalization no longer assumes Docling. The
worker asks ``build_converter(db)`` for the configured ``DocumentConverter``
(Docling Serve or Azure Document Intelligence) at JOB RUNTIME, so an admin
provider switch is effective for the next job without a restart. A provider
switch never reprocesses existing records; only an explicit Reprocess reruns
the pipeline with whatever provider is configured then.

Every provider:
- takes file bytes + filename (+ content type) and returns canonical
  Markdown as a ``ConversionResult``;
- raises ``ProviderError`` (binding ``kind`` vocabulary below) on every
  failure class — the worker stores ``kind``/``message`` on the record and
  keeps the original file;
- never puts an endpoint URL or a credential into a message or result.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from backend.config import get_settings
from backend.services.ssl_trust import resolve_verify

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

AZURE_DI_API_VERSION = "2024-11-30"
PROVIDER_DOCLING = "docling"
PROVIDER_AZURE = "azure_document_intelligence"

# prebuilt-layout input formats (api-version 2024-11-30). Narrower than
# Docling: no CSV/TSV/TXT, legacy binary Office, OpenDocument, GIF or WEBP.
AZURE_DI_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".heif",
})

# Error codes Azure uses for an input it cannot analyze.
_AZURE_UNSUPPORTED_CODES = {"DocumentContentUnsupported", "ContentNotSupported"}
# Poll responses retried within the timeout budget.
_AZURE_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


class ProviderError(Exception):
    """A document conversion failure, classified for storage and the UI.

    ``kind`` is one of: provider_unavailable, connection_timeout,
    conversion_timeout, authentication_failure, unsupported_document,
    malformed_response, conversion_failure, empty_result, invalid_endpoint,
    invalid_configuration (stored by the worker when the converter cannot be
    constructed from the effective settings).
    """

    def __init__(self, kind: str, message: str, provider_errors: list[str] | None = None):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.provider_errors = provider_errors or []


class DoclingError(ProviderError):
    """Docling-specific conversion problem (legacy name, same contract).

    Docling additionally reports ``docling_unavailable`` for connection
    failures (kept byte-identical for existing records and tests).
    """

    def __init__(self, kind: str, message: str, docling_errors: list[str] | None = None):
        super().__init__(kind, message, docling_errors)
        self.docling_errors = self.provider_errors


@dataclass
class ConversionResult:
    """Parsed outcome of one conversion.

    ``partial`` is True for ``partial_success``: the Markdown is retained
    but the warning is recorded.
    """

    markdown: str
    status: str  # "success" | "partial_success"
    partial: bool
    processor: str = ""
    processor_version: str | None = None
    processing_time_seconds: float | None = None
    warnings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict, repr=False)


@dataclass
class DoclingConversionResult(ConversionResult):
    """Legacy name for a Docling conversion result (no extra fields)."""


class DocumentConverter(Protocol):
    name: str

    def supported_extensions(self) -> frozenset[str]: ...

    def convert(
        self, file_bytes: bytes, filename: str, content_type: str = "application/octet-stream"
    ) -> ConversionResult: ...

    def health(self) -> dict[str, Any]: ...


def file_extension(filename: str) -> str:
    """Lower-cased extension including the dot ('' when there is none)."""
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


# ----------------------------------------------------------------------
# Azure Document Intelligence (prebuilt-layout, Markdown output)
# ----------------------------------------------------------------------


class AzureDocumentIntelligenceConverter:
    """Client for the Azure Document Intelligence v4.0 analyze API.

    Submits the document as ``base64Source`` to ``prebuilt-layout`` with
    ``outputContentFormat=markdown``, then polls the Operation-Location
    until the analysis finishes or the ``timeout_seconds`` budget runs out.
    Tables come back as HTML ``<table>`` markup inside the Markdown and are
    passed through verbatim (the UI sanitizes rendered content).

    The API key is env/Secret-only (``SAIL_AZURE_DI_API_KEY``). Instantiated
    per job; no shared mutable state.
    """

    name = PROVIDER_AZURE

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        ssl_verify: str | None = None,
        ssl_ca_bundle: str | None = None,
        transport: httpx.BaseTransport | None = None,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        settings = get_settings()
        self.endpoint = (endpoint if endpoint is not None else settings.azure_di_endpoint or "").rstrip("/")
        if self.endpoint and not self.endpoint.startswith("https://"):
            raise ValueError("azure_endpoint must be an HTTPS endpoint (https://)")
        self.api_key = api_key if api_key is not None else settings.azure_di_api_key
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else 600.0
        self.poll_interval_seconds = poll_interval_seconds
        self._verify = resolve_verify(ssl_verify or "full", ssl_ca_bundle or "")
        # Optional custom transport — the test seam (httpx.MockTransport in
        # tests/backend/test_document_provider.py). Never set in production.
        self._transport = transport

    def supported_extensions(self) -> frozenset[str]:
        return AZURE_DI_SUPPORTED_EXTENSIONS

    def _analyze_url(self) -> str:
        return f"{self.endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze"

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(
            timeout=timeout,
            headers={"Ocp-Apim-Subscription-Key": self.api_key or ""},
            transport=self._transport,
            verify=self._verify,
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Any HTTP response from the analyze URL means the service is reachable."""
        if not self.endpoint:
            raise ProviderError("provider_unavailable", "Azure Document Intelligence endpoint is not configured")
        try:
            with self._client(10.0) as client:
                client.get(self._analyze_url(), params={"api-version": AZURE_DI_API_VERSION})
        except httpx.HTTPError as exc:
            raise ProviderError("provider_unavailable", "Azure Document Intelligence unreachable") from exc
        return {"status": "ok", "provider": self.name}

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def convert(
        self, file_bytes: bytes, filename: str, content_type: str = "application/octet-stream"
    ) -> ConversionResult:
        """Convert one document to Markdown (analyze + poll).

        ``content_type`` is accepted for the uniform converter signature;
        the ``base64Source`` request carries no content type.
        """
        if not self.endpoint:
            raise ProviderError("provider_unavailable", "Azure Document Intelligence endpoint is not configured")
        if not self.api_key:
            raise ProviderError(
                "authentication_failure",
                "Azure Document Intelligence API key is not configured (SAIL_AZURE_DI_API_KEY)",
            )
        if file_extension(filename) not in AZURE_DI_SUPPORTED_EXTENSIONS:
            raise ProviderError(
                "unsupported_document",
                f"Document type '{filename}' is not supported by Azure Document Intelligence. "
                f"Supported: {', '.join(sorted(AZURE_DI_SUPPORTED_EXTENSIONS))}. "
                "Reupload the document in a supported format (or Markdown).",
            )

        start = time.monotonic()
        deadline = start + self.timeout_seconds
        with self._client(self.timeout_seconds) as client:
            response = self._request(
                client, "POST", self._analyze_url(),
                params={
                    "api-version": AZURE_DI_API_VERSION,
                    "_overload": "analyzeDocument",
                    "outputContentFormat": "markdown",
                },
                json={"base64Source": base64.b64encode(file_bytes).decode("ascii")},
            )
            if response.status_code >= 400:
                raise self._error_from_response(response)
            operation_url = response.headers.get("Operation-Location")
            if not operation_url:
                raise ProviderError(
                    "malformed_response",
                    "Azure Document Intelligence did not return an Operation-Location header",
                )
            payload = self._poll(client, operation_url, filename, deadline)

        analyze_result = payload.get("analyzeResult")
        document = analyze_result.get("document") if isinstance(analyze_result, dict) else None
        md_block = document.get("markdown") if isinstance(document, dict) else None
        markdown = md_block.get("content") if isinstance(md_block, dict) else None
        if not isinstance(markdown, str) or not markdown.strip():
            raise ProviderError(
                "empty_result",
                f"Azure Document Intelligence produced no Markdown content for '{filename}'",
            )
        return ConversionResult(
            markdown=markdown,
            status="success",
            partial=False,
            processor=PROVIDER_AZURE,
            processor_version=f"prebuilt-layout/{AZURE_DI_API_VERSION}",
            processing_time_seconds=time.monotonic() - start,
            warnings=[],
            raw={"status": "succeeded"},
        )

    def _poll(self, client: httpx.Client, operation_url: str, filename: str, deadline: float) -> dict:
        """Poll the analyze operation until succeeded/failed or the budget ends."""
        while True:
            response = self._request(client, "GET", operation_url)
            if response.status_code in _AZURE_TRANSIENT_STATUSES:
                self._sleep_or_timeout(response, filename, deadline)
                continue
            if response.status_code >= 400:
                raise self._error_from_response(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(
                    "malformed_response",
                    f"Azure Document Intelligence returned non-JSON (HTTP {response.status_code})",
                ) from exc
            if not isinstance(payload, dict):
                raise ProviderError("malformed_response", "Azure Document Intelligence response is not a JSON object")
            status = str(payload.get("status", ""))
            if status in ("notStarted", "running"):
                self._sleep_or_timeout(response, filename, deadline)
                continue
            if status == "succeeded":
                return payload
            if status == "failed":
                raise self._failed_analysis(payload)
            raise ProviderError(
                "malformed_response",
                f"Azure Document Intelligence returned unrecognized status {status!r} for {filename!r}",
            )

    def _sleep_or_timeout(self, response: httpx.Response, filename: str, deadline: float) -> None:
        delay = self.poll_interval_seconds
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                delay = max(1.0, float(retry_after))
            except ValueError:
                pass
        if time.monotonic() + delay >= deadline:
            raise ProviderError(
                "conversion_timeout",
                f"Azure Document Intelligence analysis of '{filename}' did not complete "
                f"within {self.timeout_seconds:.0f}s",
            )
        time.sleep(delay)

    def _request(self, client: httpx.Client, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """One HTTP call with transport errors mapped (no URL in any message)."""
        try:
            return client.request(method, url, **kwargs)
        except httpx.ConnectError as exc:
            raise ProviderError("provider_unavailable", "Azure Document Intelligence unreachable") from exc
        except httpx.ConnectTimeout as exc:
            raise ProviderError(
                "connection_timeout", "Connection to Azure Document Intelligence timed out"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "conversion_timeout",
                f"Azure Document Intelligence timed out after {self.timeout_seconds:.0f}s",
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("provider_unavailable", "Azure Document Intelligence request failed") from exc

    @staticmethod
    def _error_from_response(response: httpx.Response) -> ProviderError:
        if response.status_code in (401, 403):
            return ProviderError("authentication_failure", "Azure Document Intelligence rejected the credentials")
        try:
            body = response.json()
            error = body["error"]
            if not isinstance(error, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError):
            return ProviderError(
                "malformed_response",
                f"Azure Document Intelligence returned an unreadable error (HTTP {response.status_code})",
            )
        code = str(error.get("code") or "")
        message = str(error.get("message") or "")
        detail = f"{code}: {message}" if code else message
        kind = "unsupported_document" if code in _AZURE_UNSUPPORTED_CODES else "conversion_failure"
        return ProviderError(kind, f"Azure Document Intelligence error: {detail}", [detail])

    @staticmethod
    def _failed_analysis(payload: dict) -> ProviderError:
        analyze_result = payload.get("analyzeResult")
        raw_errors = analyze_result.get("errors") if isinstance(analyze_result, dict) else None
        details: list[str] = []
        codes: set[str] = set()
        for err in raw_errors if isinstance(raw_errors, list) else []:
            if isinstance(err, dict):
                code = str(err.get("code") or "")
                message = str(err.get("message") or "")
                codes.add(code)
                details.append(f"{code}: {message}" if code and message else code or message)
            else:
                details.append(str(err))
        joined = "; ".join(d for d in details if d) or "Azure Document Intelligence reported status 'failed'"
        kind = "unsupported_document" if codes & _AZURE_UNSUPPORTED_CODES else "conversion_failure"
        return ProviderError(kind, f"Document conversion failed: {joined}", details)


# ----------------------------------------------------------------------
# Factory — the single provider dispatch point
# ----------------------------------------------------------------------


def build_converter(db: Session | None) -> DocumentConverter:
    """The configured converter, built from the runtime-effective settings."""
    from backend.services.config_service import (
        effective_docling_settings,
        effective_document_settings,
    )
    from backend.services.docling_service import DoclingService

    eff = effective_document_settings(db)
    provider = eff.get("provider") or PROVIDER_DOCLING
    if provider == PROVIDER_AZURE:
        return AzureDocumentIntelligenceConverter(
            endpoint=eff.get("azure_endpoint") or None,
            timeout_seconds=eff.get("azure_timeout_seconds") or None,
            ssl_verify=eff.get("azure_ssl_verify") or None,
            ssl_ca_bundle=eff.get("azure_ssl_ca_bundle") or None,
        )
    if provider == PROVIDER_DOCLING:
        return DoclingService(
            **{
                k: v
                for k, v in effective_docling_settings(db).items()
                if k in ("server_url", "timeout_seconds", "ssl_verify", "ssl_ca_bundle")
                and v not in (None, "")
            }
        )
    raise ValueError(f"Unknown document provider: {provider!r}")
