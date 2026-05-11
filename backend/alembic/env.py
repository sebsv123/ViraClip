"""
Alembic env.py — sync-only with psycopg2.

Converts asyncpg URL to psycopg2 URL automatically.
No asyncio, no async_engine_from_config.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import models for autogenerate ──────────────────────────────────────────
import sys
sys.path.insert(0, ".")

from src.database import Base
from src import models  # noqa: F401 — registers models on Base.metadata

target_metadata = Base.metadata


def get_sync_url() -> str:
    """Convert asyncpg URL to psycopg2 URL for Alembic."""
    url = config.get_main_option("sqlalchemy.url")
    return url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")


def run_migrations_offline() -> None:
    context.configure(
        url=get_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(get_sync_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
