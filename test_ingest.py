"""Tests for ingest robustness: pruning stale cichéti and listing bàcari.

Offline, uses ingest_directory against temp dirs (no git, no network).
"""
import os
import tempfile
from pathlib import Path

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

from app.db import init_db, engine
from sqlmodel import Session, select
from app.models import CichetoRow
from app.ingest import ingest_directory, list_bacari

init_db()
# clean slate
with Session(engine) as s:
    for r in s.exec(select(CichetoRow)).all():
        s.delete(r)
    s.commit()


def cich(id, name="App", cats="utilities"):
    return (f"cicheto: 1\nid: {id}\nname: {name}\nsummary: s\n"
            f"categories: [{cats}]\n"
            "channels:\n  stable:\n    version: '1'\n    kind: hpkg\n"
            "    artifacts:\n      x86_64:\n        url: https://e.org/a.hpkg\n"
            f"        sha256: {'a'*64}\n")


def write_bacaro(files: dict) -> Path:
    d = Path(tempfile.mkdtemp())
    for fname, content in files.items():
        (d / fname).write_text(content)
    return d


# --- first ingest: two apps in 'tapA' ---
a = write_bacaro({"one.yaml": cich("org.a.one"), "two.yaml": cich("org.a.two")})
r1 = ingest_directory(a, "tapA")
assert set(r1["ingested"]) == {"org.a.one", "org.a.two"}, r1
assert r1["removed"] == [], r1
print("first ingest       -> ok (2 apps, nothing removed)")

# --- a different bàcaro 'tapB' with its own app ---
b = write_bacaro({"x.yaml": cich("org.b.x")})
ingest_directory(b, "tapB")

# --- re-ingest tapA with 'two' removed -> 'two' must be pruned, tapB untouched ---
a2 = write_bacaro({"one.yaml": cich("org.a.one")})
r2 = ingest_directory(a2, "tapA")
assert r2["ingested"] == ["org.a.one"], r2
assert r2["removed"] == ["org.a.two"], r2
print("prune stale        -> ok (org.a.two removed)")

with Session(engine) as s:
    ids = {r.id for r in s.exec(select(CichetoRow)).all()}
assert ids == {"org.a.one", "org.b.x"}, ids
print("tapB untouched     -> ok (org.b.x still present)")

# --- prune=False keeps stale rows ---
a3 = write_bacaro({"three.yaml": cich("org.a.three")})
r3 = ingest_directory(a3, "tapA", prune=False)
assert r3["removed"] == [], r3
with Session(engine) as s:
    a_ids = {r.id for r in s.exec(
        select(CichetoRow).where(CichetoRow.bacaro == "tapA")).all()}
assert a_ids == {"org.a.one", "org.a.three"}, a_ids  # one kept, three added
print("prune=False        -> ok (no removal)")

# --- a cichéto cannot hijack another tap by id; pruning is per crawl slug ---
# Re-ingest tapA empty: removes all tapA rows, leaves tapB.
empty = write_bacaro({})
r4 = ingest_directory(empty, "tapA")
assert set(r4["removed"]) == {"org.a.one", "org.a.three"}, r4
with Session(engine) as s:
    ids = {r.id for r in s.exec(select(CichetoRow)).all()}
assert ids == {"org.b.x"}, ids
print("empty re-ingest    -> ok (tapA cleared, tapB intact)")

# --- list_bacari ---
bacari = list_bacari()
names = {x["bacaro"]: x["count"] for x in bacari}
assert names == {"tapB": 1}, names
print("list_bacari        -> ok", names)

print("\nPASS: ingest pruning + bàcari listing")
