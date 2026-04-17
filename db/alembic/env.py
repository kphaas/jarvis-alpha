"""
Alembic env.py — jarvis-alpha migrations.
Reads DB DSN from JARVIS_ALPHA_DB_DSN environment variable.
"""

import os
from logging.config import fileConfig
from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def get_dsn() -> str:
    dsn = os.getenv("JARVIS_ALPHA_DB_DSN")
    if not dsn:
        raise RuntimeError("JARVIS_ALPHA_DB_DSN not set — add to ~/jarvis/.secrets")
    if dsn.startswith("postgresql+asyncpg://"):
        dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    return dsn


def run_migrations_online() -> None:
    connectable = create_engine(
        get_dsn(),
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
