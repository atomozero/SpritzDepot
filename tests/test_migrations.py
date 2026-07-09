"""The alembic migration history is complete: applying it to a clean DB produces
the same schema as create_all (i.e. the models). This catches the drift where a
model change ships via create_all but is never added to alembic, so a fresh
Postgres/alembic deploy would be missing it (audit high).

Uses throwaway DBs, no network.
"""
import os
import pathlib
import sqlite3
import subprocess
import sys

_ALEMBIC_DB = "test_migrations_alembic.db"
_CREATEALL_DB = "test_migrations_createall.db"
for db in (_ALEMBIC_DB, _CREATEALL_DB):
    for s in ("", "-wal", "-shm"):
        pathlib.Path(db + s).unlink(missing_ok=True)


def _schema(path: str) -> dict:
    c = sqlite3.connect(path)
    tables = sorted(r[0] for r in c.execute(
        "select name from sqlite_master where type='table' "
        "and name not like 'sqlite_%' and name != 'alembic_version'"))
    out = {}
    for t in tables:
        cols = sorted(r[1] for r in c.execute(f"PRAGMA table_info({t})"))
        out[t] = cols
    c.close()
    return out


# build one DB by running the full alembic history
env = {**os.environ, "SPRITZ_DB_URL": f"sqlite:///./{_ALEMBIC_DB}",
       "SPRITZ_ENV": "dev", "SPRITZ_SECRET": "x", "SPRITZ_ADMIN_TOKEN": "t"}
r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                   env=env, capture_output=True, text=True)
assert r.returncode == 0, f"alembic upgrade failed:\n{r.stderr}"
print("alembic upgrade head on a clean DB -> ok")

# build the other by create_all (the models)
env2 = {**os.environ, "SPRITZ_DB_URL": f"sqlite:///./{_CREATEALL_DB}",
        "SPRITZ_ENV": "dev", "SPRITZ_SECRET": "x", "SPRITZ_ADMIN_TOKEN": "t"}
r2 = subprocess.run(
    [sys.executable, "-c", "from app.db import init_db; init_db()"],
    env=env2, capture_output=True, text=True)
assert r2.returncode == 0, f"create_all failed:\n{r2.stderr}"

alembic_schema = _schema(_ALEMBIC_DB)
createall_schema = _schema(_CREATEALL_DB)
diffs = {t: (alembic_schema.get(t), createall_schema.get(t))
         for t in set(alembic_schema) | set(createall_schema)
         if alembic_schema.get(t) != createall_schema.get(t)}
assert not diffs, f"alembic schema drifted from the models: {diffs}"
print("alembic schema matches create_all (models) -> ok")

for db in (_ALEMBIC_DB, _CREATEALL_DB):
    for s in ("", "-wal", "-shm"):
        pathlib.Path(db + s).unlink(missing_ok=True)
print("\nPASS: migrations complete + in sync with models")
