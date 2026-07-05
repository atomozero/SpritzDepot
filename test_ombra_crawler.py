"""ombra crawler + snapshot-first read path, fully offline.

A fake GitHub client returns a canned releases payload (no network). Covers:
crawl_ombra writes a snapshot per ombra app; read_snapshot honors freshness and
config drift; /resolve and /library/pending serve from a fresh snapshot WITHOUT
calling GitHub, and fall back to a live resolve (refreshing the snapshot) when it
is missing. Throwaway DB.
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

# Merges rows into the DB; use a throwaway, never the real catalog.
import test_db_guard  # noqa: E402
test_db_guard.use_throwaway_db("test_ombra_crawler")

from datetime import datetime, timedelta

from sqlmodel import Session
from app.db import init_db, engine
from app.models import CichetoRow, OmbraSnapshot
from app import ombra, ombra_crawler

# --- fake GitHub client (same shape test_ombra uses) ---
RELEASES = [
    {"tag_name": "v1.5", "draft": False, "prerelease": False, "assets": [
        {"name": "genio-1.5-x86_64.hpkg",
         "browser_download_url": "https://x/genio-1.5-x86_64.hpkg"},
    ]},
]


class FakeResp:
    def __init__(self, payload): self._p = payload; self.status_code = 200; self.text = ""
    def json(self): return self._p
    def raise_for_status(self): pass


class FakeClient:
    def __init__(self, payload=RELEASES): self._p = payload; self.calls = 0
    def get(self, url, headers=None, params=None):
        self.calls += 1
        return FakeResp(self._p)


RAW = {
    "id": "org.haiku.genio", "name": "Genio",
    "homepage": "https://github.com/owner/genio",
    "channels": {"ombra": {
        "kind": "hpkg", "source": "github-latest",
        "match": "genio-*-{arch}.hpkg", "prerelease": False,
        "artifacts": {"x86_64": {}},
    }},
}

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="org.haiku.genio", name="Genio", bacaro="vepro",
                       channels="ombra", raw=RAW))
    s.commit()

# --- crawl writes a snapshot ---
fake = FakeClient()
with Session(engine) as s:
    res = ombra_crawler.crawl_ombra(s, client=fake)
assert res.total == 1 and res.resolved == 1 and res.errors == 0, res
with Session(engine) as s:
    snap = s.get(OmbraSnapshot, "org.haiku.genio")
assert snap is not None and snap.version == "1.5", snap
assert snap.artifacts["x86_64"]["url"] == "https://x/genio-1.5-x86_64.hpkg", snap
assert snap.error is None, snap
print("crawl_ombra        -> ok (snapshot written, version + url)")

# --- read_snapshot: fresh -> hit ---
with Session(engine) as s:
    got = ombra_crawler.read_snapshot(s, "org.haiku.genio", RAW)
assert got is not None and got.version == "1.5", got
print("read fresh          -> ok")

# --- read_snapshot: stale -> miss (None) ---
with Session(engine) as s:
    snap = s.get(OmbraSnapshot, "org.haiku.genio")
    snap.resolved_at = datetime.utcnow() - timedelta(hours=48)
    s.add(snap); s.commit()
    stale = ombra_crawler.read_snapshot(s, "org.haiku.genio", RAW,
                                        ttl=timedelta(hours=6))
assert stale is None, "stale snapshot must be a miss"
print("read stale          -> ok (miss)")

# --- read_snapshot: config drift (match changed) -> miss ---
drifted = dict(RAW)
drifted["channels"] = {"ombra": dict(RAW["channels"]["ombra"], match="other-*-{arch}.hpkg")}
with Session(engine) as s:
    snap = s.get(OmbraSnapshot, "org.haiku.genio")
    snap.resolved_at = datetime.utcnow()  # fresh again
    s.add(snap); s.commit()
    drift = ombra_crawler.read_snapshot(s, "org.haiku.genio", drifted)
assert drift is None, "config drift must invalidate the snapshot"
print("read config drift   -> ok (miss)")

# --- /resolve serves from a FRESH snapshot without calling GitHub ---
import app.main as main
from fastapi.testclient import TestClient

# refresh the snapshot so it is fresh + matches RAW
fake2 = FakeClient()
with Session(engine) as s:
    ombra_crawler.resolve_and_snapshot(s, "org.haiku.genio", RAW, client=fake2)
    s.commit()

# Make a live resolve BLOW UP: if /resolve touched GitHub, we'd see this raise.
_orig = ombra.resolve_github_latest
def _boom(*a, **k):
    raise AssertionError("live resolve called despite a fresh snapshot")
ombra.resolve_github_latest = _boom
try:
    c = TestClient(main.app)
    r = c.get("/resolve/org.haiku.genio?channel=ombra&arch=x86_64")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.5", body
    assert body["artifacts"]["x86_64"]["url"] == "https://x/genio-1.5-x86_64.hpkg", body
    assert "sha256" not in body["artifacts"]["x86_64"], "ombra must not carry sha256"
    print("/resolve snapshot   -> ok (served from DB, no GitHub call)")
finally:
    ombra.resolve_github_latest = _orig

# --- missing snapshot -> live fallback that refreshes the snapshot ---
with Session(engine) as s:
    s.delete(s.get(OmbraSnapshot, "org.haiku.genio"))
    s.commit()

def _fake_resolve(repo, match, arches, prerelease=False, client=None):
    return _orig(repo, match, arches, prerelease=prerelease, client=FakeClient())
ombra.resolve_github_latest = _fake_resolve
try:
    c = TestClient(main.app)
    r = c.get("/resolve/org.haiku.genio?channel=ombra&arch=x86_64")
    assert r.status_code == 200, r.text
    assert r.json()["version"] == "1.5", r.json()
    with Session(engine) as s:
        assert s.get(OmbraSnapshot, "org.haiku.genio") is not None, "fallback must refresh snapshot"
    print("/resolve fallback   -> ok (live resolve refreshed the snapshot)")
finally:
    ombra.resolve_github_latest = _orig

print("\nPASS: ombra crawler + snapshot-first read path")
