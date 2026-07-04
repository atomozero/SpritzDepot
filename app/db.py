"""Database engine and session management.

SQLite for the prototype; set SPRITZ_DB_URL to a Postgres URL in production
without touching the rest of the code (SQLModel handles both).
"""
import os

from sqlalchemy import event
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = os.environ.get("SPRITZ_DB_URL", "sqlite:///./spritz.db")

# check_same_thread=False is only needed for SQLite + FastAPI's threadpool.
_IS_SQLITE = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _IS_SQLITE else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args)


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        """Make SQLite safe under concurrent access. With check_same_thread=False
        the FastAPI threadpool shares connections, so a long write (ingest) can
        collide with a library POST / download-event write. Defaults would fail
        that second writer immediately with 'database is locked' (busy_timeout=0).
        WAL lets readers proceed during a write; busy_timeout makes a blocked
        writer wait instead of erroring. No-op on Postgres (MVCC handles this)."""
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()


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
