"""Database engine and session management.

SQLite for the prototype; swap the URL for Postgres in production
without touching the rest of the code (SQLModel handles both).
"""
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = "sqlite:///./spritz.db"

# check_same_thread=False is needed only for SQLite + FastAPI's threadpool.
engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)


def init_db() -> None:
    """Create tables. Called once at startup."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a session per request."""
    with Session(engine) as session:
        yield session
