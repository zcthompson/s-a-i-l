"""Docling Serve integration — document normalization for Customer Knowledge.

Docling (docling-serve) is the common conversion abstraction between
uploaded customer documents (PDF, CSV, DOCX, PPTX, HTML, ODF, images, ...)
and the canonical Markdown representation that Customer Knowledge features,
search, AI context, and report generation consume

Invariants honored here:
- The browser never talks to Docling; this service is the only Docling-aware
  code, and routes/services above it never construct Docling HTTP calls.
- The Docling host is environment-configured (``docling_server_url``),
  never hardcoded: the backend container reaches Docling on the host LAN IP
  (same path as ``AI_ENDPOINT``), never on 127.0.0.1.
- HTTP 200 is NOT success. Docling reports per-document conversion status
  (success / partial_success / skipped / failure) in the response body; the
  status field is authoritative. A ``skipped`` conversion (e.g. "File
  format not allowed") is a conversion failure with Docling's message.
- Docling is a deterministic conversion service, not the application's LLM:
  its output is document-derived content, not generated inference, and is
  stored as the document's normalized derivative (the original is retained).

The service is deliberately endpoint-shaped (``convert_to_markdown`` takes
file bytes + metadata) so a later switch to Docling's native async API
(``/v1/convert/file/async``) can replace the body without changing callers.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

import httpx

from backend.config import get_settings
from backend.services.document_provider import (
    ConversionResult,
    DoclingConversionResult,
    DoclingError,
)
from backend.services.ssl_trust import resolve_verify

logger = logging.getLogger(__name__)
_STARTED_AT = time.monotonic()

# Conversion statuses Docling reports (plan item 6). Only these values are
# recognized; anything else is treated as a malformed response.
SUCCESS_STATUSES = {"success", "partial_success"}
FAILED_STATUSES = {"skipped", "failure"}

# Supported upload extensions routed through Docling (plan item 5: Docling
# supports PDF, DOC/DOCX, PPT/PPTX, HTML, images, Markdown, CSV, XLS/XLSX,
# OpenDocument and related formats). Markdown is NOT in this set: .md files
# are already the canonical format and are normalized in-process by the
# caller (short-circuit, plan item 8).
DOCLING_SUPPORTED_EXTENSIONS = {
    ".pdf", ".csv", ".tsv", ".txt",
    ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".html", ".htm",
    ".odt", ".ods", ".odp",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
}

# Markdown uploads are canonical by definition.
MARKDOWN_EXTENSIONS = {".md", ".markdown", ".mdown", ".mkd"}

# Conversion parameters (plan item 5 + user-supplied pipeline set, 2026-09-10):
# accuracy over speed — OCR enabled but not forced (digitally generated PDFs
# use their existing text), accurate table extraction, images as placeholders
# so the normalized Markdown stays compact. The user's pasted pipeline JSON
# (do_ocr / pdf_backend / table_mode / pipeline / ocr_engine / ocr_lang) is
# applied as multipart form fields.
_CONVERSION_PARAMETERS: dict[str, str] = {
    "to_formats": "md",
    "do_ocr": "true",
    "force_ocr": "false",
    "pdf_backend": "dlparse_v4",
    "table_mode": "accurate",
    "pipeline": "standard",
    "ocr_engine": "tesseract",
    "ocr_lang": "eng",
    "image_export_mode": "placeholder",
    "abort_on_error": "false",
}


class DoclingService:
    """Reusable client for the Docling Serve conversion API.

    Centralizes endpoint construction, timeout handling, request parameters,
    error interpretation, logging, and response parsing (plan item 4).
    Instantiated per use; no shared mutable state.

    Implements the provider-neutral ``DocumentConverter`` protocol
    (``backend.services.document_provider``) via ``name`` /
    ``supported_extensions`` / ``convert``.
    """

    name = "docling"

    def __init__(
        self,
        server_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: float | None = None,
        ssl_verify: str | None = None,
        ssl_ca_bundle: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self.server_url = (server_url if server_url is not None else settings.docling_server_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.docling_api_key
        self.timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings.docling_timeout_seconds
        )
        # Connection trust model (P0b): resolve the httpx `verify=` value from
        # the explicit args (typically effective_docling_settings) falling back
        # to the env-based Settings. `full` (default) = native verification.
        mode = ssl_verify or settings.docling_ssl_verify or "full"
        bundle = (ssl_ca_bundle or "") or settings.docling_ssl_ca_bundle or ""
        self._verify = resolve_verify(mode, bundle)
        # Optional custom transport — the test seam (httpx.MockTransport in
        # tests/backend/test_docling_service.py). Never set in production.
        self._transport = transport

    def supported_extensions(self) -> frozenset[str]:
        return frozenset(DOCLING_SUPPORTED_EXTENSIONS)

    def convert(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> ConversionResult:
        """Provider-neutral entry point (``DocumentConverter`` protocol)."""
        res = self.convert_to_markdown(file_bytes, filename, content_type)
        res.processor = "docling"
        return res

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health(self, timeout_seconds: float = 10.0) -> dict[str, Any]:
        """GET {server}/health → {"status": "ok"} when Docling is up.

        Raises ``DoclingError(kind="docling_unavailable")`` when it is not.
        """
        try:
            with httpx.Client(
                timeout=timeout_seconds, transport=self._transport, verify=self._verify
            ) as client:
                response = client.get(f"{self.server_url}/health")
                response.raise_for_status()
                return response.json()
        except httpx.ConnectError as exc:
            raise DoclingError("docling_unavailable", f"Docling unreachable at {self.server_url}: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise DoclingError("docling_unavailable", f"Docling health check timed out at {self.server_url}: {exc}") from exc
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise DoclingError("malformed_response", f"Docling health check failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    def convert_to_markdown(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> DoclingConversionResult:
        """Convert one document to Markdown via POST /v1/convert/file.

        Synchronous (multipart) call; run from the background processing
        worker, never inside the upload request's HTTP transaction
        (plan item 9). Raises ``DoclingError`` on every failure class;
        returns a ``DoclingConversionResult`` only for success /
        partial_success with non-empty Markdown.
        """
        if not self.server_url:
            raise DoclingError(
                "docling_unavailable",
                "Docling server URL is not configured (SAIL_DOCLING_SERVER_URL)",
            )

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        start = time.monotonic()
        try:
            deadline = start + self.timeout_seconds
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise httpx.ReadTimeout("Docling conversion deadline exceeded")
                try:
                    with httpx.Client(
                        timeout=remaining, headers=headers,
                        transport=self._transport, verify=self._verify,
                    ) as client:
                        response = client.post(
                            f"{self.server_url}/v1/convert/file",
                            files=[("files", (filename, file_bytes, content_type))],
                            data=_CONVERSION_PARAMETERS,
                        )
                    if response.status_code < 500 or attempt == 2:
                        break
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if attempt == 2:
                        raise
                delay = min(0.1 * 2 ** attempt + random.uniform(0, 0.05), max(0, deadline - time.monotonic()))
                if delay:
                    time.sleep(delay)
        except httpx.ConnectError as exc:
            raise DoclingError(
                "docling_unavailable",
                ("Document processing is starting up; retry shortly. " if time.monotonic() - _STARTED_AT < get_settings().docling_startup_grace_seconds else "") + f"Docling unreachable at {self.server_url}: {exc}",
            ) from exc
        except httpx.ConnectTimeout as exc:
            raise DoclingError(
                "connection_timeout",
                f"Connection to Docling at {self.server_url} timed out",
            ) from exc
        except httpx.ReadTimeout as exc:
            raise DoclingError(
                "conversion_timeout",
                f"Docling conversion of '{filename}' timed out after {self.timeout_seconds:.0f}s",
            ) from exc
        except httpx.TimeoutException as exc:
            raise DoclingError("conversion_timeout", f"Docling timed out while converting '{filename}': {exc}") from exc
        except httpx.HTTPError as exc:
            raise DoclingError("docling_unavailable", f"Docling request failed: {exc}") from exc

        elapsed = time.monotonic() - start

        # HTTP-level failures: a transport-level 200 is what the API returns
        # even for skipped/failed conversions, so the body's ``status`` is
        # the authority (plan item 6).
        try:
            payload = response.json()
        except ValueError as exc:
            raise DoclingError(
                "malformed_response",
                f"Docling returned non-JSON (HTTP {response.status_code})",
            ) from exc

        if not isinstance(payload, dict):
            raise DoclingError("malformed_response", "Docling response is not a JSON object")

        status = str(payload.get("status", "")).lower()
        docling_errors: list[str] = []
        raw_errors = payload.get("errors") or []
        if isinstance(raw_errors, list):
            for err in raw_errors:
                if isinstance(err, dict):
                    docling_errors.append(str(err.get("error_message") or err))
                else:
                    docling_errors.append(str(err))

        if status in FAILED_STATUSES:
            detail = "; ".join(docling_errors) or f"Docling reported status '{status}'"
            kind = "unsupported_document" if "not allowed" in detail.lower() or "unsupported" in detail.lower() else "conversion_failure"
            logger.warning(
                "Docling conversion %s (status=%s) for %r: %s",
                kind, status, filename, detail,
            )
            raise DoclingError(kind, f"Document conversion failed: {detail}", docling_errors)

        if status not in SUCCESS_STATUSES:
            raise DoclingError(
                "malformed_response",
                f"Docling returned unrecognized status {status!r} for {filename!r}",
            )

        document = payload.get("document") or {}
        markdown = document.get("md_content")
        if not isinstance(markdown, str) or not markdown.strip():
            logger.warning(
                "Docling returned empty Markdown (status=%s) for %r: %s",
                status, filename, "; ".join(docling_errors) or "no error detail",
            )
            raise DoclingError(
                "empty_result",
                f"Docling produced no Markdown content for '{filename}': "
                f"{'; '.join(docling_errors) or 'conversion produced an empty document'}",
                docling_errors,
            )

        warnings: list[str] = []
        if status == "partial_success":
            warnings.append("; ".join(docling_errors) or "Docling reported partial_success")

        processor_version: str | None = None
        if isinstance(document.get("processor_version"), str):
            processor_version = document["processor_version"]

        return DoclingConversionResult(
            markdown=markdown,
            status=status,
            partial=status == "partial_success",
            processing_time_seconds=float(payload["processing_time"])
            if isinstance(payload.get("processing_time"), (int, float))
            else elapsed,
            processor_version=processor_version,
            warnings=warnings,
            raw=payload,
        )


# ----------------------------------------------------------------------
# Markdown short-circuit (plan item 8)
# ----------------------------------------------------------------------


def is_markdown_upload(filename: str) -> bool:
    """True when the upload is already the canonical format."""
    ext = _extension_of(filename)
    return ext in MARKDOWN_EXTENSIONS


def is_docling_supported(filename: str) -> bool:
    """True when the upload should be routed through Docling."""
    ext = _extension_of(filename)
    return ext in DOCLING_SUPPORTED_EXTENSIONS


def _extension_of(filename: str) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def normalize_markdown_text(raw: bytes) -> str:
    """Normalize an uploaded Markdown file in-process (no Docling round-trip).

    - decode tolerant of common encodings (utf-8 first, then latin-1);
    - normalize line endings (CRLF / CR → LF);
    - collapse a trailing newline run to a single trailing newline.

    Raises ``DoclingError(kind="empty_result")`` when the file decodes to no
    readable text.
    """
    text: str | None = None
    for encoding in ("utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    if text is None:
        raise DoclingError("empty_result", "Markdown file could not be decoded as text")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n") + ("\n" if text.strip() else "")
    if not text.strip():
        raise DoclingError("empty_result", "Markdown file contains no readable text")
    return text
