"""Database engine and session management.

SQLite for the prototype; set SPRITZ_DB_URL to a Postgres URL in production
without touching the rest of the code (SQLModel handles both).
"""
import os

from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = os.environ.get("SPRITZ_DB_URL", "sqlite:///./spritz.db")

# check_same_thread=False is only needed for SQLite + FastAPI's threadpool.
_connect_args = ({"check_same_thread": False}
                 if DATABASE_URL.startswith("sqlite") else {})
engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args)


def init_db() -> None:
    """Create tables. Called once at startup.

    Import models first so every table is registered on SQLModel.metadata
    before create_all, regardless of import order at the call site.
    """
    from . import models  # noqa: F401  (registers tables as a side effect)
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a session per request."""
    with Session(engine) as session:
        yield session
