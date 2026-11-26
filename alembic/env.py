"""Alembic environment configuration."""

import importlib
import os
import pkgutil
import sys
from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool


# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()  # Pick up .env (SAIL_DATABASE_URL etc.) without overriding real env vars

# Import EVERY model module (not a hand-maintained list) so every table is
# registered in Base.metadata for autogenerate/check. A hand-maintained list
# silently drops tables when new model files are added — the same failure
# mode tests/backend/conftest.py documents and guards against with pkgutil.
import backend.models  # noqa: E402
from backend.models.use_case import Base  # noqa: E402, F401

for _module in pkgutil.iter_modules(backend.models.__path__):
    importlib.import_module(f"backend.models.{_module.name}")

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Update sqlalchemy.url from environment if present. Honour the app's
# SAIL_DATABASE_URL (from .env) so alembic and the app always
# operate on the same database; DATABASE_URL is kept as a plain alias.
from backend.alembic_compare import include_legacy_unique  # noqa: E402
from backend.config import get_settings  # noqa: E402
from backend.database import normalized_url  # noqa: E402

db_url = normalized_url(get_settings().database_url, get_settings().db_sslmode)
if db_url:
    config.set_main_option("sqlalchemy.url", db_url.replace("%", "%%"))

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        inspector = sa.inspect(connection)

        def include_object(obj, name, type_, reflected, compare_to):
            return include_legacy_unique(inspector, connection.dialect.name,
                                         obj, type_, reflected, compare_to)

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
