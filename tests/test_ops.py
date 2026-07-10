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

# The public /stats is catalog-only: operator data (who signed up, what they
# queued) is not for anonymous callers.
assert "users" not in s and "library_entries" not in s, s
print("stats is catalog   -> ok")

# /admin/stats is gated.
assert c.get("/admin/stats").status_code == 401
print("admin stats gated  -> ok")

ADMIN = {"X-Admin-Token": "t"}

# Counters move with a user + a queued install.
before = c.get("/admin/stats", headers=ADMIN).json()
tok = c.post("/auth/register",
             json={"email": "ops@x.io", "password": "longenoughpass1"}).json()["access_token"]
c.post("/library/org.haiku.genio", json={"channel": "stable", "arch": "x86_64"},
       headers={"Authorization": f"Bearer {tok}"})
after = c.get("/admin/stats", headers=ADMIN).json()
assert after["users"]["total"] == before["users"]["total"] + 1, (before, after)
assert after["library"]["pending"] == before["library"]["pending"] + 1, (before, after)
assert after["library"]["total"] == before["library"]["total"] + 1, (before, after)
print("counters move      -> ok")

# The admin view carries the catalog too, plus the operator sections.
a = after
assert a["catalog"]["cicheti"] == s["cicheti"], a
assert a["users"]["admins"] >= 0 and a["users"]["last_30d"] >= 1, a
assert a["downloads"]["window_days"] == 30, a
assert a["ombra"]["errors"] == 0 and a["ombra"]["failing"] == [], a
# `catalog.bacari` counts distinct taps among the cached cichéti; `bacari.rows`
# are the operational crawl records, written only by POST /ingest. This test
# seeds via ingest_directory(), so the catalog sees a tap and the crawl log is
# empty. Not a bug: the two answer different questions.
assert a["catalog"]["bacari"] >= 1, a
assert a["bacari"]["total"] == 0 and a["bacari"]["failing"] == 0, a
print("admin stats shape  -> ok")

# A resolve is recorded in the download log and surfaces in the ranking.
r = c.get("/resolve/org.haiku.genio", params={"channel": "stable", "arch": "x86_64"})
assert r.status_code == 200, r.text
dl = c.get("/admin/stats", headers=ADMIN).json()["downloads"]
assert dl["total"] >= 1 and dl["all_time"] >= 1, dl
assert dl["by_kind"].get("resolve", 0) >= 1, dl
assert dl["top"] and dl["top"][0]["id"] == "org.haiku.genio", dl
assert dl["top"][0]["name"], dl          # the ranking names the app, not just its id
print("download log       -> ok")

# The stats page renders (it is a shell; the numbers come from /admin/stats).
p = c.get("/admin/stats-page")
assert p.status_code == 200 and "/static/stats.js" in p.text, p.status_code
print("stats page         -> ok")

print("\nPASS: ops health + stats")
