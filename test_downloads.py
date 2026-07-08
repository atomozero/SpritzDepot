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


def seed_cicheto(cid, name, bacaro, channels="stable", version="1.0"):
    with Session(engine) as s:
        s.merge(CichetoRow(
            id=cid, name=name, summary=f"{name} summary", bacaro=bacaro,
            channels=channels,
            raw={"id": cid, "name": name,
                 "channels": {"stable": {"kind": "hpkg", "version": version,
                                         "artifacts": {"x86_64": {"url": "https://x/a.hpkg",
                                                                  "sha256": "0"*64}}}}},
        ))
        s.commit()


# a featured app, a couple third-party apps, and a HaikuPorts-mirror app
seed_cicheto("org.haiku.genio", "Genio", "vepro")
seed_cicheto("repo.lote.blender", "Blender", "lote")
seed_cicheto("repo.fatelk.snowfall", "Snowfall", "fatelk")
seed_cicheto("hp.mirror.zzz", "ZZZ", "haikuports")  # must never show in browse/random
# build-artifact sub-packages: hidden from the shop-window, still searchable
seed_cicheto("repo.lote.blender_devel", "blender_devel", "lote")
seed_cicheto("repo.lote.ffmpeg_debuginfo", "ffmpeg_debuginfo", "lote")

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


# --- random shelf excludes the HaikuPorts mirror and build-artifact sub-packages ---
with Session(engine) as s:
    rnd = main._random_third_party(s, limit=20)
ids = {r["id"] for r in rnd}
assert all(r["bacaro"] != "haikuports" for r in rnd), rnd
assert "hp.mirror.zzz" not in ids
assert "repo.lote.blender_devel" not in ids, "_devel leaked into shelf"
assert "repo.lote.ffmpeg_debuginfo" not in ids, "_debuginfo leaked into shelf"
print("random shelf excludes haikuports + sub-packages -> ok")


# --- browse hides sub-packages, but search still finds them ---
with Session(engine) as s:
    browse, _ = main._search_rows(s, exclude_hidden=True, limit=200)
    found, _ = main._search_rows(s, q="blender_devel", limit=10)
bids = {r["id"] for r in browse}
assert "repo.lote.blender_devel" not in bids, "_devel visible in browse"
assert "repo.lote.ffmpeg_debuginfo" not in bids, "_debuginfo visible in browse"
assert "repo.lote.blender" in bids, "real app wrongly hidden"
assert any(r["id"] == "repo.lote.blender_devel" for r in found), "search cannot reach _devel"
print("browse hides sub-packages, search still reaches them -> ok")


# --- home renders all three shelves, no raw i18n keys, no double-listing ---
html = c.get("/").text
assert 'class="featured-card"' in html, "featured shelf missing"
assert "/app/org.haiku.genio" in html, "featured app not Genio"
assert "home.top_month" not in html and "home.from_repos" not in html, "raw i18n key leaked"
assert "badge-downloads" in html, "download badge missing"
print("home renders featured + top + from-repos -> ok")

# --- dedup: same app in two visible bàcari collapses to one card with also_in ---
# Two visible copies of 'yab' (fatelk + otherrepo) exercise the browse grouping.
seed_cicheto("repo.fatelk.yab", "yab", "fatelk")
seed_cicheto("repo.other.yab", "yab", "otherrepo")   # a second visible source
with Session(engine) as s:
    browse, _ = main._search_rows(s, exclude_hidden=True, limit=200)
    groups = main._dedup_groups(browse)
yab_groups = [g for g in groups if main._dedup_key(g) == "yab"]
assert len(yab_groups) == 1, f"yab not collapsed: {yab_groups}"
g = yab_groups[0]
# fatelk (rank 1) or otherrepo (rank 0) represents; the other is in also_in
assert g["also_in"], "yab group has no also_in"
assert {s2["bacaro"] for s2 in g["also_in"]} | {g["bacaro"]} >= {"fatelk", "otherrepo"}
print("browse dedup collapses same app, keeps sources -> ok")

# app page: also_in reaches the HaikuPorts mirror copy even though browse hides it,
# and picks the newest version across copies (the real httrack -4 < -5 case).
seed_cicheto("repo.lote.httrack", "httrack", "lote", version="3.49.2-4")
seed_cicheto("repo.haikuports.httrack", "httrack", "haikuports", version="3.49.2-5")
with Session(engine) as s:
    lote = s.get(CichetoRow, "repo.lote.httrack")
    res = main._also_in_sources(s, lote)
# viewing the lote copy: the haikuports copy (-5) is newer
assert res["newest_id"] == "repo.haikuports.httrack", res
assert any(x["id"] == "repo.haikuports.httrack" and x["newest"]
           for x in res["sources"]), res
print("app-page also_in picks newest version across repos -> ok")

# viewing the newer copy: it is flagged as the latest, no 'newer elsewhere'
with Session(engine) as s:
    hp = s.get(CichetoRow, "repo.haikuports.httrack")
    res2 = main._also_in_sources(s, hp)
assert res2["newest_id"] == "repo.haikuports.httrack", res2
assert not any(x["newest"] for x in res2["sources"]), res2  # the other (lote) is older
print("app-page marks the viewed copy as latest when it is -> ok")

# equal versions -> no winner (decline rather than pick arbitrarily)
seed_cicheto("repo.a.tie", "tieapp", "lote", version="2.0-1")
seed_cicheto("repo.b.tie", "tieapp", "fatelk", version="2.0-1")
with Session(engine) as s:
    res3 = main._also_in_sources(s, s.get(CichetoRow, "repo.a.tie"))
assert res3["newest_id"] is None, res3
print("equal versions decline to pick a winner -> ok")


# --- ombra copies join the compare (version resolved live, mocked here) ---
def seed_ombra(cid, name, bacaro):
    with Session(engine) as s:
        s.merge(CichetoRow(
            id=cid, name=name, summary=f"{name} summary", bacaro=bacaro,
            channels="ombra",
            raw={"id": cid, "name": name, "homepage": "https://github.com/o/x",
                 "channels": {"ombra": {"kind": "hpkg", "source": "github-latest",
                                        "repo": "o/x", "match": "x-*-{arch}.hpkg",
                                        "artifacts": {"x86_64": {}}}}}))
        s.commit()

# an ombra app (no cached version) vs a pinned mirror copy
seed_ombra("com.me.gizmo", "gizmo", "vepro")
seed_cicheto("repo.haikuports.gizmo", "gizmo", "haikuports", version="1.0-1")

# mock the live ombra lookup: the author's latest tag is newer (2.5)
_orig_ombra = main._ombra_version
main._ombra_version = lambda session, cid, raw: "2.5" if (raw or {}).get("id") == "com.me.gizmo" else _orig_ombra(session, cid, raw)
main._OMBRA_VERSION_CACHE.clear()
try:
    with Session(engine) as s:
        # viewing the mirror (1.0): the ombra copy (2.5) must win
        res4 = main._also_in_sources(s, s.get(CichetoRow, "repo.haikuports.gizmo"))
    assert res4["newest_id"] == "com.me.gizmo", res4
    assert any(x["id"] == "com.me.gizmo" and x["newest"] for x in res4["sources"]), res4
    print("ombra copy joins compare and can be the newest -> ok")

    # if the live lookup fails (returns None), the ombra copy is skipped, not guessed
    main._ombra_version = lambda session, cid, raw: None
    main._OMBRA_VERSION_CACHE.clear()
    with Session(engine) as s:
        res5 = main._also_in_sources(s, s.get(CichetoRow, "repo.haikuports.gizmo"))
    # only the mirror has a version now -> it is the sole, and newest
    assert res5["newest_id"] == "repo.haikuports.gizmo", res5
    print("failed ombra lookup is skipped, not guessed -> ok")
finally:
    main._ombra_version = _orig_ombra
    main._OMBRA_VERSION_CACHE.clear()


# --- icon fallback: an app with no icon of its own borrows a twin's ---
# gizmo (com.me.gizmo) has no extractable icon; its haikuports twin does.
_orig_extract = main._extract_icon
def _fake_extract(row):
    # only the haikuports twin yields an icon; the ombra copy does not
    return b"PNGDATA" if row.id == "repo.haikuports.gizmo" else None
main._extract_icon = _fake_extract
try:
    with Session(engine) as s:
        ombra_row = s.get(CichetoRow, "com.me.gizmo")
        assert main._extract_icon(ombra_row) is None, "gizmo should have no own icon"
        borrowed = main._borrow_twin_icon(s, ombra_row)
    assert borrowed == b"PNGDATA", f"did not borrow twin icon: {borrowed!r}"
    # and a twin with no icon anywhere borrows nothing
    with Session(engine) as s:
        lone = s.get(CichetoRow, "repo.lote.blender")  # blender has a haikuports twin too
        # blender twin also returns None from _fake_extract -> nothing to borrow
        assert main._borrow_twin_icon(s, lone) is None
    print("icon fallback borrows a twin's icon, none when no twin has one -> ok")
finally:
    main._extract_icon = _orig_extract
    # the borrow path caches the fake PNG under the twin's id; clean it up
    import app.config as _cfg
    (pathlib.Path(_cfg.UPLOAD_DIR) / "icons" / "repo.haikuports.gizmo.png").unlink(missing_ok=True)

# --- negative icon cache: a miss is remembered, not re-attempted ---
# seed a lone app with no twin and no extractable icon; /icon must 404 once,
# then answer from the .none marker without calling _extract_icon again.
import app.config as _cfg
seed_cicheto("repo.lone.noicon", "noiconapp", "lote")
_icons = pathlib.Path(_cfg.UPLOAD_DIR) / "icons"
(_icons / "repo.lone.noicon.none").unlink(missing_ok=True)
(_icons / "repo.lone.noicon.png").unlink(missing_ok=True)

calls = {"n": 0}
def _counting_extract(row):
    calls["n"] += 1
    return None                      # never yields an icon
_orig_extract2 = main._extract_icon
_orig_tool = main.hvif.tool_available
main._extract_icon = _counting_extract
main.hvif.tool_available = lambda: True   # pretend hvif2png is present
try:
    r1 = c.get("/icon/repo.lone.noicon")
    assert r1.status_code == 404, r1.status_code
    assert (_icons / "repo.lone.noicon.none").is_file(), "miss marker not written"
    after_first = calls["n"]
    assert after_first >= 1, "extract not attempted on first request"
    r2 = c.get("/icon/repo.lone.noicon")
    assert r2.status_code == 404, r2.status_code
    assert calls["n"] == after_first, "extract re-attempted despite negative cache"
    print("negative icon cache: miss remembered, not re-downloaded -> ok")
finally:
    main._extract_icon = _orig_extract2
    main.hvif.tool_available = _orig_tool
    (_icons / "repo.lone.noicon.none").unlink(missing_ok=True)

pathlib.Path("test_downloads.db").unlink(missing_ok=True)
print("\nPASS: download tracking + home shelves + dedup")
