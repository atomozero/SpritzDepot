"""Health and stats endpoints, offline."""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

from pathlib import Path
from app.db import init_db
from app.ingest import ingest_directory

init_db()
ingest_directory(Path("sample-bacaro"), "vepro")

from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

h = c.get("/health")
assert h.status_code == 200 and h.json()["status"] == "ok", h.text
print("health             -> ok")

s = c.get("/stats").json()
assert s["cicheti"] >= 1, s
assert s["bacari"] >= 1, s
assert s["with_haikuports_bridge"] >= 1, s          # Genio has a bridge
assert s["by_channel"].get("stable") and s["by_channel"].get("ombra"), s
assert "editors" in s["by_category"], s
print("stats shape        -> ok")

# counters move with a user + a queued install
before = c.get("/stats").json()
tok = c.post("/auth/register",
             json={"email": "ops@x.io", "password": "longenough1"}).json()["access_token"]
c.post("/library/org.haiku.genio", json={"channel": "stable", "arch": "x86_64"},
       headers={"Authorization": f"Bearer {tok}"})
after = c.get("/stats").json()
assert after["users"] == before["users"] + 1, (before, after)
assert after["library_entries"] == before["library_entries"] + 1, (before, after)
print("counters move      -> ok")

print("\nPASS: ops health + stats")
