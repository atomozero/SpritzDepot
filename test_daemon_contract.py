"""The daemon-facing pending/installed contract (audit high).

pending: every item carries source + version + bridge + notes; a haikuports
bridge app gets an actionable pkgman note (not an empty-artifacts retry signal);
a pruned app transitions to a terminal state instead of looping forever.
installed: a stale confirm on a since-re-queued row is superseded, not clobbered.
Throwaway DB, offline.
"""
import os
import pathlib

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_daemon_contract.db"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_daemon_contract.db" + s).unlink(missing_ok=True)

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import init_db, engine
from app.models import CichetoRow, InstallState
from app.main import app

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="hp.app", name="HpApp", bacaro="haikuports",
                       channels="stable",
                       raw={"id": "hp.app", "name": "HpApp",
                            "bridge": {"haikuports": "hpapp"},
                            "channels": {"stable": {"kind": "hpkg",
                                                    "source": "haikuports"}}}))
    s.merge(CichetoRow(id="st.app", name="StApp", bacaro="vepro",
                       channels="stable",
                       raw={"id": "st.app", "name": "StApp",
                            "channels": {"stable": {"kind": "hpkg", "version": "1.2-1",
                                "artifacts": {"x86_64": {"url": "https://x/a.hpkg",
                                                         "sha256": "0" * 64}}}}}))
    s.merge(CichetoRow(id="a.b", name="AB", bacaro="vepro", channels="stable,ombra",
                       raw={"id": "a.b", "name": "AB",
                            "channels": {"stable": {}, "ombra": {}}}))
    s.commit()

c = TestClient(app)
tok = c.post("/auth/register",
             json={"email": "d@x.io", "password": "longenough1"}).json()["access_token"]
auth = {"Authorization": f"Bearer {tok}"}


# --- pending contract ---
c.post("/library/hp.app", json={"channel": "stable", "arch": "x86_64"}, headers=auth)
c.post("/library/st.app", json={"channel": "stable", "arch": "x86_64"}, headers=auth)
pend = {p["cicheto"]: p for p in c.get("/library/pending", headers=auth).json()}

hp = pend["hp.app"]
assert hp["source"] == "haikuports", hp
assert any("pkgman install" in n for n in hp["notes"]), "bridge app must get a pkgman note"
assert hp["bridge"] == {"haikuports": "hpapp"}, hp
print("pending: haikuports bridge -> actionable note + bridge, not a retry -> ok")

st = pend["st.app"]
assert st["version"] == "1.2-1" and st["source"] is None, st
assert st["notes"] == [] and "bridge" in st, st
print("pending: stable carries version + source + empty notes -> ok")


# --- pruned app -> terminal state, not an endless pending loop ---
c.post("/library/a.b", json={"channel": "stable"}, headers=auth)
with Session(engine) as s:
    s.delete(s.get(CichetoRow, "a.b"))
    s.commit()
c.get("/library/pending", headers=auth)  # first poll transitions it
with Session(engine) as s:
    row = s.exec(select(InstallState).where(InstallState.cicheto_id == "a.b")).first()
assert row.state == "unavailable", f"pruned app should be terminal, got {row.state}"
print("pending: pruned app -> unavailable, no infinite loop -> ok")


# --- installed race: stale confirm is superseded, not clobbering ---
# re-add a.b and drive the re-queue race
with Session(engine) as s:
    s.merge(CichetoRow(id="a.b", name="AB", bacaro="vepro", channels="stable,ombra",
                       raw={"id": "a.b", "name": "AB",
                            "channels": {"stable": {}, "ombra": {}}}))
    s.commit()
c.post("/library/a.b", json={"channel": "stable"}, headers=auth)
c.post("/library/a.b", json={"channel": "ombra"}, headers=auth)   # row now = ombra
r = c.post("/library/a.b/installed", json={"channel": "stable"}, headers=auth)
assert r.json()["status"] == "superseded", r.json()
with Session(engine) as s:
    row = s.exec(select(InstallState).where(InstallState.cicheto_id == "a.b")).first()
assert row.state == "pending" and row.channel == "ombra", "ombra request was clobbered"
print("installed: stale stable confirm superseded, ombra request kept -> ok")

# correct confirm + backward compat (no body)
assert c.post("/library/a.b/installed", json={"channel": "ombra"},
              headers=auth).json()["status"] == "installed"
c.post("/library/a.b", json={"channel": "stable"}, headers=auth)
assert c.post("/library/a.b/installed", headers=auth).json()["status"] == "installed"
print("installed: matching confirm + bodyless (old daemon) both work -> ok")

for s in ("", "-wal", "-shm"):
    pathlib.Path("test_daemon_contract.db" + s).unlink(missing_ok=True)
print("\nPASS: daemon pending/installed contract")
