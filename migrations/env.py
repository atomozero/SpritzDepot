"""Alembic environment for spritz.

Pulls the engine and metadata from the app so migrations always match the
models and the configured database (SQLite in dev, Postgres in prod) without
duplicating the URL here.
"""
from alembic import context
from sqlmodel import SQLModel

from app import models  # noqa: F401  (registers all tables on the metadata)
from app.db import engine

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=str(engine.url),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
