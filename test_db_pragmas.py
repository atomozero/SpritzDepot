"""SQLite is configured for concurrent access: WAL + busy_timeout.

Without these, a second writer during a long write fails immediately with
'database is locked'. Throwaway DB, offline.
"""
import os
import pathlib

os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_db_pragmas.db"
for suffix in ("", "-wal", "-shm"):
    pathlib.Path("test_db_pragmas.db" + suffix).unlink(missing_ok=True)

from sqlalchemy import text
from app.db import engine

with engine.connect() as c:
    assert c.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    assert c.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    assert c.execute(text("PRAGMA synchronous")).scalar() == 1  # NORMAL
print("sqlite PRAGMAs: WAL + busy_timeout=5000 + synchronous=NORMAL -> ok")

for suffix in ("", "-wal", "-shm"):
    pathlib.Path("test_db_pragmas.db" + suffix).unlink(missing_ok=True)
print("\nPASS: db pragmas")
