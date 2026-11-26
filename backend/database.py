"""Shared backend selection and connection policy; never embeds credentials."""
from functools import lru_cache

import sqlalchemy as sa
from sqlalchemy.engine import make_url

from backend.config import get_settings


def normalized_url(value: str, sslmode: str | None = None) -> str:
    url = make_url(value)
    if url.get_backend_name() in {"postgres", "postgresql"}:
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+psycopg")
        mode = sslmode or url.query.get("sslmode") or "require"
        url = url.update_query_dict({"sslmode": mode})
    return url.render_as_string(hide_password=False)


@lru_cache(maxsize=32)
def _engine(url: str, network_fs: bool, pool_size: int, overflow: int, factory):
    options = {"pool_pre_ping": True}
    dialect = make_url(url).get_backend_name()
    if dialect == "postgresql":
        options.update(pool_recycle=1800, pool_size=pool_size, max_overflow=overflow,
                       pool_timeout=10, connect_args={"connect_timeout": 10})
    engine = factory(url, **options)
    if dialect == "sqlite" and network_fs:
        @sa.event.listens_for(engine, "connect")
        def configure_sqlite(connection, _record):
            cursor = connection.cursor()
            try:
                for statement in ("PRAGMA journal_mode=DELETE", "PRAGMA busy_timeout=10000",
                                  "PRAGMA foreign_keys=ON", "PRAGMA synchronous=FULL"):
                    cursor.execute(statement)
            finally:
                cursor.close()
    return engine


def create_engine(url: str):
    """Reuse pools for runtime callers; retain the test engine-factory seam."""
    settings = get_settings()
    return _engine(normalized_url(url, settings.db_sslmode), settings.sqlite_network_fs,
                   settings.db_pool_size, settings.db_max_overflow, sa.create_engine)
