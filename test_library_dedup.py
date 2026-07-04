"""The library queue is one row per (user, app): a double-queue upserts, it does
not create duplicate pending rows (audit high). Throwaway DB, offline.
"""
import os
import pathlib

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_library_dedup.db"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_library_dedup.db" + s).unlink(missing_ok=True)

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import init_db, engine
from app.models import CichetoRow, InstallState
from app.main import app

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="x.y.z", name="Z", bacaro="vepro", channels="stable",
                       raw={"id": "x.y.z", "name": "Z"}))
    s.commit()

c = TestClient(app)
tok = c.post("/auth/register",
             json={"email": "q@x.io", "password": "longenough1"}).json()["access_token"]
auth = {"Authorization": f"Bearer {tok}"}

# queue the same app twice with different channels
assert c.post("/library/x.y.z", json={"channel": "stable", "arch": "x86_64"},
              headers=auth).status_code == 200
assert c.post("/library/x.y.z", json={"channel": "ombra", "arch": "x86_64"},
              headers=auth).status_code == 200

with Session(engine) as s:
    rows = s.exec(select(InstallState)).all()
assert len(rows) == 1, f"expected one library row, got {len(rows)}"
assert rows[0].channel == "ombra", "re-queue should update the channel in place"
print("double-queue upserts to one row (channel updated) -> ok")

# remove then re-queue: still one row
assert c.post("/library/x.y.z/remove", headers=auth).status_code == 200
assert c.post("/library/x.y.z", json={"channel": "stable"}, headers=auth).status_code == 200
with Session(engine) as s:
    rows = s.exec(select(InstallState)).all()
assert len(rows) == 1, f"remove+requeue should keep one row, got {len(rows)}"
print("remove + re-queue stays one row -> ok")

for s in ("", "-wal", "-shm"):
    pathlib.Path("test_library_dedup.db" + s).unlink(missing_ok=True)
print("\nPASS: library queue dedup")
