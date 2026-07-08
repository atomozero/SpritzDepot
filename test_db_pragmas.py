"""SQLite is configured for concurrent access: busy_timeout + a safe journal.

The journal mode is WAL on a normal filesystem (readers proceed during a write),
but DELETE on a 9p/drvfs/network mount (WSL /mnt), where WAL's shared-memory file
corrupts. This test asserts whichever mode the code should pick for where the DB
actually lives. Throwaway DB, offline.
"""
import os
import pathlib

os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_db_pragmas.db"
for suffix in ("", "-wal", "-shm"):
    pathlib.Path("test_db_pragmas.db" + suffix).unlink(missing_ok=True)

from sqlalchemy import text
from app import db
from app.db import engine

expected_journal = "delete" if db._DB_ON_NETWORK_FS else "wal"

with engine.connect() as c:
    got = c.execute(text("PRAGMA journal_mode")).scalar()
    assert got == expected_journal, f"journal_mode {got!r}, expected {expected_journal!r}"
    assert c.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    assert c.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL
print(f"sqlite PRAGMAs: journal={expected_journal} (network_fs="
      f"{db._DB_ON_NETWORK_FS}) + busy_timeout=5000 + synchronous=NORMAL -> ok")

for suffix in ("", "-wal", "-shm"):
    pathlib.Path("test_db_pragmas.db" + suffix).unlink(missing_ok=True)
print("\nPASS: db pragmas")
