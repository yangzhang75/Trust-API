"""Alembic migration environment.

Pulls the database URL from application settings and targets the ORM
metadata so `alembic revision --autogenerate` works in later weeks.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from trust_api.config import get_settings

# Import models so they register on Base.metadata before autogenerate.
from trust_api.db import models  # noqa: F401
from trust_api.db.session import Base

config = context.config

# Configure logging from alembic.ini, EXCEPT when invoked programmatically
# (e.g. from the test suite) — fileConfig would replace the root logger's
# handlers and evict pytest's caplog handler. The CLI path is unaffected.
if config.config_file_name is not None and not os.environ.get("ALEMBIC_SKIP_LOGGING_CONFIG"):
    fileConfig(config.config_file_name)

# Use an explicitly-provided URL if one is set on the config (e.g. tests
# injecting a target DB); otherwise fall back to the application settings.
config.set_main_option(
    "sqlalchemy.url",
    config.get_main_option("sqlalchemy.url") or get_settings().database_url,
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL without a DBAPI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (with a live connection)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
