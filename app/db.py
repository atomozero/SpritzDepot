"""Database engine and session management.

SQLite for the prototype; set SPRITZ_DB_URL to a Postgres URL in production
without touching the rest of the code (SQLModel handles both).
"""
import os
import subprocess

from sqlalchemy import event
from sqlmodel import SQLModel, create_engine, Session

DATABASE_URL = os.environ.get("SPRITZ_DB_URL", "sqlite:///./spritz.db")

# check_same_thread=False is only needed for SQLite + FastAPI's threadpool.
_IS_SQLITE = DATABASE_URL.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _IS_SQLITE else {}
# For a long-lived Postgres deploy: pre_ping drops dead connections (server
# restart, idle timeout) instead of handing a stale one to a request; recycle
# caps connection age. No effect on SQLite (single-file, no pool to speak of).
_engine_kw = {} if _IS_SQLITE else {"pool_pre_ping": True, "pool_recycle": 1800}
engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args,
                       **_engine_kw)


def _sqlite_path(url: str) -> str:
    """The filesystem path from a sqlite:/// URL, or '' if not a file DB."""
    if not url.startswith("sqlite"):
        return ""
    # sqlite:///relative or sqlite:////absolute ; ignore :memory:
    tail = url.split("sqlite:///", 1)[-1]
    return "" if tail.startswith(":memory:") or not tail else tail


def _on_network_fs(path: str) -> bool:
    """True if `path` lives on a filesystem where SQLite WAL is unsafe: WSL2's 9p
    mount of the Windows drives (/mnt/c, /mnt/d ...), or a classic drvfs/cifs
    share. WAL memory-maps a -shm file, which these filesystems do not honour
    reliably, and the result is intermittent 'database disk image is malformed'.
    On such a filesystem we fall back to the rollback journal instead of WAL.
    Best-effort: any detection failure returns False (keep WAL)."""
    if not path:
        return False
    try:
        target = os.path.dirname(os.path.abspath(path)) or "."
        out = subprocess.run(["stat", "-f", "-c", "%T", target],
                             capture_output=True, text=True, timeout=3)
        fstype = (out.stdout or "").strip().lower()
        # 9p = WSL2 Windows-drive mount; others are network/shared mounts.
        return fstype in {"9p", "v9fs", "drvfs", "cifs", "smb2", "fuseblk", "nfs"}
    except Exception:
        return False


# Decided once at import: is the SQLite file on a WAL-unsafe filesystem?
_DB_ON_NETWORK_FS = _on_network_fs(_sqlite_path(DATABASE_URL))


if _IS_SQLITE:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        """Make SQLite safe under concurrent access. With check_same_thread=False
        the FastAPI threadpool shares connections, so a long write (ingest) can
        collide with a library POST / download-event write. Defaults would fail
        that second writer immediately with 'database is locked' (busy_timeout=0).
        WAL lets readers proceed during a write; busy_timeout makes a blocked
        writer wait instead of erroring. No-op on Postgres (MVCC handles this).

        WAL is skipped when the DB is on a 9p/drvfs/network filesystem (e.g. a
        WSL2 /mnt/d path): WAL's shared-memory file corrupts there. We use the
        DELETE journal instead, which is slower but stable on those filesystems."""
        cur = dbapi_conn.cursor()
        if _DB_ON_NETWORK_FS:
            cur.execute("PRAGMA journal_mode=DELETE")
        else:
            cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA synchronous=NORMAL")
        # Enforce foreign keys (off by default in SQLite): the library.user_id ->
        # users.id reference should actually be checked.
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def init_db() -> None:
    """Ensure the schema exists. Called once at startup.

    In dev/test this create_all's the tables (convenient, no migration step). In
    prod the schema is owned by Alembic (`alembic upgrade head`), so create_all is
    skipped: running it against a migrated DB masks schema drift and can conflict
    with Alembic's view of the tables. Import models first so every table is
    registered on SQLModel.metadata before create_all.
    """
    from . import models  # noqa: F401  (registers tables as a side effect)
    from . import config
    if config.IS_PROD:
        return  # schema managed by Alembic in production
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yields a session per request."""
    with Session(engine) as session:
        yield session
