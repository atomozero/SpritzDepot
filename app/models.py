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

from sqlalchemy import event
from sqlmodel import SQLModel, Field, Column, JSON


def dedup_key_for_name(name: str) -> str:
    """The identity that makes two cichéti 'the same app in different repos':
    the name lowercased with - and _ folded together (so 'yab' from fatelk and
    'yab' from haikuports collide, but 'yab' and 'yab_devel' do not). Stored on
    the row (indexed) so grouping is a WHERE lookup, not a scan."""
    return (name or "").strip().lower().replace("-", "_")


class CichetoRow(SQLModel, table=True):
    """One row per app, keyed by reverse-domain id."""
    __tablename__ = "cicheti"

    id: str = Field(primary_key=True)          # org.haiku.genio
    name: str = Field(index=True)
    # Normalized name used to group the same app across repos (lowercased, - and _
    # folded). Indexed so "other copies of this app" is a WHERE dedup_key = ?
    # lookup instead of a full-table scan + Python filter on every app-page view.
    dedup_key: str = Field(default="", index=True)
    summary: str = ""
    bacaro: str = Field(default="", index=True)  # which tap it came from
    categories: str = Field(default="")          # comma-joined, for cheap LIKE search
    haikuports: Optional[str] = None             # bridge target, if any
    channels: str = Field(default="")            # comma-joined channel names
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))  # full cichéto
    ingested_at: datetime = Field(default_factory=datetime.utcnow)


# Keep dedup_key in sync with name automatically, so every insert/update (ingest,
# import-hpkr, tests, future call sites) gets the right value without having to
# remember to set it. Derived from name unless explicitly provided non-empty.
@event.listens_for(CichetoRow, "before_insert", propagate=True)
@event.listens_for(CichetoRow, "before_update", propagate=True)
def _fill_dedup_key(mapper, connection, target):  # noqa: ANN001
    # dedup_key is a pure function of name; keep them in lockstep.
    target.dedup_key = dedup_key_for_name(target.name)


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    # Bumped to invalidate all of a user's outstanding tokens at once. The JWT
    # carries the version it was minted with; tokens whose version is stale are
    # rejected. This is the revocation mechanism (logout-everywhere, on a
    # password change, or on compromise).
    token_version: int = Field(default=0)
    # The first user to register becomes admin (bootstrap); the rest are normal.
    # Admin users pass the admin gate alongside SPRITZ_ADMIN_TOKEN.
    is_admin: bool = Field(default=False)


class Bacaro(SQLModel, table=True):
    """Operational record of a tap that has been ingested: its git URL and the
    last crawl outcome. Not a source of truth (the git repo is); just so the
    admin page can list and re-crawl taps without re-typing the URL."""
    __tablename__ = "bacari"

    slug: str = Field(primary_key=True)
    git_url: str = ""
    last_ingested_at: Optional[datetime] = None
    last_ingested: int = 0           # how many cichéti on the last crawl
    last_removed: int = 0            # how many pruned on the last crawl
    last_error: Optional[str] = None


class DownloadEvent(SQLModel, table=True):
    """One append-only row per resolved download, so the catalog can show a real
    'most downloaded this month' chart instead of a fabricated one.

    Recorded when the daemon resolves an app for install (/resolve) and again,
    more strongly, when it confirms the install landed (/library/{id}/installed).
    `kind` distinguishes the two so we can weight or filter later. Kept lean and
    append-only; the ranking is a GROUP BY over a time window."""
    __tablename__ = "downloads"

    id: Optional[int] = Field(default=None, primary_key=True)
    cicheto_id: str = Field(index=True)
    channel: str = "stable"
    arch: Optional[str] = None
    kind: str = Field(default="resolve", index=True)  # 'resolve' | 'installed'
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class InstallState(SQLModel, table=True):
    """A user's library entry: the 'Play Store' queue.

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
