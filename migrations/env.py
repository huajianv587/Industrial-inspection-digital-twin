from __future__ import annotations

import os
from alembic import context
from sqlalchemy import create_engine, pool

from inspection_system.platform.db import Base
from inspection_system.platform import entities  # noqa: F401
from inspection_system.platform.settings import Settings


config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    raise RuntimeError("Offline SQL generation is disabled; migrations require the configured Supabase database.")


def run_migrations_online() -> None:
    settings = Settings(
        database_url=os.getenv("SUPABASE_DB_URL", ""),
        environment=os.getenv("APP_ENV", "production").lower(),
        supabase_url=os.getenv("SUPABASE_URL"),
    )
    settings.validate_database()
    settings.validate_supabase_project_binding(required=True)
    database_url = settings.sqlalchemy_database_url()
    connectable = create_engine(database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


run_migrations_online()
