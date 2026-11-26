"""Shared bounded upload reader for persisted documents."""

from fastapi import HTTPException

from backend.config import get_settings

# A-8 re-recon 2026-11-01: read through Settings (import time — the
# per-process env is stable).
MAX_UPLOAD_BYTES = get_settings().max_upload_bytes


async def read_upload_bytes(upload) -> bytes:
    """Read an async upload in bounded chunks and enforce the shared ceiling."""
    chunks = []
    total = 0
    while chunk := await upload.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Upload exceeds the maximum size of "
                    f"{MAX_UPLOAD_BYTES // 1024 // 1024} MiB"
                ),
            )
        chunks.append(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail="Upload is empty")
    return b"".join(chunks)
