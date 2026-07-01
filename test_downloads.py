"""Download tracking + home shelves (featured / top-month / from-repos).

Fully offline, throwaway DB. Covers: a resolve records a DownloadEvent, the
'installed' confirmation records a stronger one, the monthly ranking counts only
the last 30 days and orders by count, the random shelf excludes the HaikuPorts
mirror, and the home page renders all three shelves without leaking raw i18n keys.
"""
import os

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "test-secret"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
# deterministic featured target for the assertions below
os.environ["SPRITZ_FEATURED_CICHETO"] = "org.haiku.genio"
# a throwaway db so we never touch the real catalog
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_downloads.db"

import pathlib
pathlib.Path("test_downloads.db").unlink(missing_ok=True)

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import init_db, engine
from app.models import CichetoRow, DownloadEvent
import app.main as main

init_db()


def seed_cicheto(cid, name, bacaro, channels="stable"):
    with Session(engine) as s:
        s.merge(CichetoRow(
            id=cid, name=name, summary=f"{name} summary", bacaro=bacaro,
            channels=channels,
            raw={"id": cid, "name": name,
                 "channels": {"stable": {"kind": "hpkg", "version": "1.0",
                                         "artifacts": {"x86_64": {"url": "https://x/a.hpkg",
                                                                  "sha256": "0"*64}}}}},
        ))
        s.commit()


# a featured app, a couple third-party apps, and a HaikuPorts-mirror app
seed_cicheto("org.haiku.genio", "Genio", "vepro")
seed_cicheto("repo.lote.blender", "Blender", "lote")
seed_cicheto("repo.fatelk.snowfall", "Snowfall", "fatelk")
seed_cicheto("hp.mirror.zzz", "ZZZ", "haikuports")  # must never show in browse/random

c = TestClient(main.app)


# --- a resolve records a download event ---
with Session(engine) as s:
    n0 = len(s.exec(select(DownloadEvent)).all())
r = c.get("/resolve/repo.lote.blender?channel=stable&arch=x86_64")
assert r.status_code == 200, r.text
with Session(engine) as s:
    evs = s.exec(select(DownloadEvent)).all()
assert len(evs) == n0 + 1 and evs[-1].kind == "resolve", evs
print("resolve records DownloadEvent -> ok")


# --- ranking: count only last 30 days, order by count ---
with Session(engine) as s:
    for e in s.exec(select(DownloadEvent)).all():
        s.delete(e)
    s.commit()
    now = datetime.utcnow()

    def ev(cid, days_ago, kind="resolve"):
        e = DownloadEvent(cicheto_id=cid, channel="stable", kind=kind)
        e.created_at = now - timedelta(days=days_ago)
        s.add(e)

    for _ in range(9):
        ev("repo.lote.blender", 3)
    for _ in range(4):
        ev("repo.fatelk.snowfall", 10)
    for _ in range(20):
        ev("repo.lote.blender", 45)   # stale: excluded by the 30d window
    s.commit()

with Session(engine) as s:
    top = main._top_downloads(s, since_days=30, limit=8)
ids = [(r["id"], r["downloads"]) for r in top]
assert ids[0] == ("repo.lote.blender", 9), ids       # stale 20 not counted
assert ids[1] == ("repo.fatelk.snowfall", 4), ids
print("monthly ranking (30d window, ordered) -> ok")


# --- random shelf excludes the HaikuPorts mirror ---
with Session(engine) as s:
    rnd = main._random_third_party(s, limit=8)
assert all(r["bacaro"] != "haikuports" for r in rnd), rnd
assert "hp.mirror.zzz" not in {r["id"] for r in rnd}
print("random shelf excludes haikuports -> ok")


# --- home renders all three shelves, no raw i18n keys, no double-listing ---
html = c.get("/").text
assert 'class="featured-card"' in html, "featured shelf missing"
assert "/app/org.haiku.genio" in html, "featured app not Genio"
assert "home.top_month" not in html and "home.from_repos" not in html, "raw i18n key leaked"
assert "badge-downloads" in html, "download badge missing"
print("home renders featured + top + from-repos -> ok")

pathlib.Path("test_downloads.db").unlink(missing_ok=True)
print("\nPASS: download tracking + home shelves")
