"""Persistent application paths; uploaded knowledge itself remains DB-backed."""
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.config import get_settings


def files_root(settings=None) -> Path:
    settings = settings or get_settings()
    if settings.files_dir:
        return Path(settings.files_dir).expanduser().resolve()
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        return Path(url.database).expanduser().resolve().parent / "files"
    return Path("data/files").resolve()


def persistent_path(relative: str, settings=None) -> Path:
    root = files_root(settings)
    candidate = (root / relative).resolve()
    if Path(relative).is_absolute() or not candidate.is_relative_to(root):
        raise ValueError("Persistent paths must remain inside the application files directory")
    return candidate


def prepare_directories(settings=None) -> Path:
    settings = settings or get_settings()
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
        Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
    root = files_root(settings)
    root.mkdir(parents=True, exist_ok=True)
    return root
