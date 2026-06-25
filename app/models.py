"""Database tables (the cache + accounts + library).

The cichéto cache stores the full validated manifest as JSON in `raw`,
plus a few flattened, indexed columns so search and resolve are fast
without parsing JSON every time. This is the "DB" half of the
git + cache model: git repos are the source of truth, this is the
queryable projection rebuilt on every ingest.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field, Column, JSON


class CichetoRow(SQLModel, table=True):
    """One row per app, keyed by reverse-domain id."""
    __tablename__ = "cicheti"

    id: str = Field(primary_key=True)          # org.haiku.genio
    name: str = Field(index=True)
    summary: str = ""
    bacaro: str = Field(default="", index=True)  # which tap it came from
    categories: str = Field(default="")          # comma-joined, for cheap LIKE search
    haikuports: Optional[str] = None             # bridge target, if any
    channels: str = Field(default="")            # comma-joined channel names
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))  # full cichéto
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InstallState(SQLModel, table=True):
    """A user's library entry — the 'Play Store' queue.

    state: 'pending'  -> queued from the web, daemon hasn't acted yet
           'installed'-> daemon confirmed it landed
           'removed'  -> user uninstalled
    """
    __tablename__ = "library"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(index=True, foreign_key="users.id")
    cicheto_id: str = Field(index=True)
    channel: str = "stable"
    arch: Optional[str] = None
    state: str = Field(default="pending", index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
