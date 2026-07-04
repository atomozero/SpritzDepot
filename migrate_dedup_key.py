"""One-off migration: add and backfill CichetoRow.dedup_key.

SQLModel's create_all does not ALTER existing tables, so a database created
before the dedup_key column needs this. Idempotent: safe to run more than once.

    python migrate_dedup_key.py            # migrates ./spritz.db (or SPRITZ_DB_URL)
"""
import sqlite3
import sys
from urllib.parse import urlparse

from app import config
from app.models import dedup_key_for_name


def sqlite_path() -> str:
    url = config.DATABASE_URL if hasattr(config, "DATABASE_URL") else None
    # config doesn't expose DATABASE_URL; read the env the same way app.db does.
    import os
    url = os.environ.get("SPRITZ_DB_URL", "sqlite:///./spritz.db")
    if not url.startswith("sqlite"):
        print(f"Not a SQLite URL ({url}); run the equivalent ALTER/UPDATE on your DB.")
        sys.exit(2)
    # sqlite:///./spritz.db -> ./spritz.db
    return url.split("///", 1)[1]


def main() -> None:
    path = sqlite_path()
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cicheti)")]
    if "dedup_key" not in cols:
        conn.execute("ALTER TABLE cicheti ADD COLUMN dedup_key VARCHAR DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_cicheti_dedup_key "
                     "ON cicheti (dedup_key)")
        print("added dedup_key column + index")
    else:
        print("dedup_key column already present")

    # Backfill anything empty (new column, or rows ingested before the code change).
    rows = conn.execute(
        "SELECT id, name FROM cicheti WHERE dedup_key = '' OR dedup_key IS NULL"
    ).fetchall()
    for cid, name in rows:
        conn.execute("UPDATE cicheti SET dedup_key = ? WHERE id = ?",
                     (dedup_key_for_name(name), cid))
    conn.commit()
    total = conn.execute("SELECT count(*) FROM cicheti").fetchone()[0]
    print(f"backfilled {len(rows)} rows; {total} total")
    conn.close()


if __name__ == "__main__":
    main()
