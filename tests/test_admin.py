"""Admin page + bàcaro records test, offline (local git bàcaro)."""
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "test-admin-secret-123")
# A throwaway DB so the "first user becomes admin" bootstrap is exercised on an
# empty users table, and so we never touch the real catalog (spritz.db).
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_admin.db"
Path("test_admin.db").unlink(missing_ok=True)

from app.db import init_db
init_db()
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
ADMIN = {"X-Admin-Token": "test-admin-secret-123"}


def local_bacaro() -> str:
    src = Path("sample-bacaro").resolve()
    repo = Path(tempfile.mkdtemp()) / "vepro"
    repo.mkdir()
    for f in src.glob("*.yaml"):
        (repo / f.name).write_text(f.read_text())
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "commit", "-q", "-m", "x"]):
        subprocess.run(cmd, cwd=repo, env=env, check=True, capture_output=True)
    return str(repo)


# page renders, action endpoint gated
assert c.get("/admin").status_code == 200
assert 'id="admin-token"' in c.get("/admin").text
assert c.get("/static/admin.js").status_code == 200
assert c.get("/admin/bacari").status_code == 401, "admin/bacari must require token"
print("page + gating      -> ok")

# ingest via API records the tap with its url + outcome
url = local_bacaro()
ing = c.post("/ingest", json={"git_url": url, "bacaro": "vepro"}, headers=ADMIN)
assert ing.status_code == 200, ing.text
rec = c.get("/admin/bacari", headers=ADMIN).json()
assert rec and rec[0]["slug"] == "vepro" and rec[0]["git_url"] == url
assert rec[0]["last_ingested"] >= 1 and rec[0]["last_error"] is None
print("ingest record      -> ok")

# a failing ingest records the error and does not crash
bad = c.post("/ingest", json={"git_url": "ssh://nope/x", "bacaro": "badtap"},
             headers=ADMIN)
assert bad.status_code == 400, bad.text
badrec = [r for r in c.get("/admin/bacari", headers=ADMIN).json()
          if r["slug"] == "badtap"]
assert badrec and badrec[0]["last_error"], badrec
print("error record       -> ok")

# DELETE /bacari/{slug}: admin-gated, removes the tap's cichéti and record
assert c.delete("/bacari/vepro").status_code == 401, "delete must require admin"
# vepro has at least the seeded cichéto(s) from sample-bacaro
before = len(c.get("/search?bacaro=vepro").json()["results"])
assert before >= 1, "expected vepro cichéti before delete"
d = c.delete("/bacari/vepro", headers=ADMIN)
assert d.status_code == 200, d.text
assert d.json()["removed_cicheti"] == before, d.json()
assert c.get("/search?bacaro=vepro").json()["results"] == [], "cichéti not gone"
assert not [r for r in c.get("/admin/bacari", headers=ADMIN).json()
            if r["slug"] == "vepro"], "Bacaro record not gone"
print("delete bàcaro      -> ok (cichéti + record removed)")

# --- first user becomes admin; admin login passes the gate (no token) ---
admin_tok = c.post("/auth/register",
                   json={"email": "boss@x.io", "password": "longenoughpass1"}).json()["access_token"]
admin_auth = {"Authorization": f"Bearer {admin_tok}"}
# the admin user reaches an admin-only endpoint WITHOUT X-Admin-Token
assert c.get("/admin/bacari", headers=admin_auth).status_code == 200, "admin user gate"
# a second user is NOT admin and is rejected on the same endpoint
normal_tok = c.post("/auth/register",
                    json={"email": "normal@x.io", "password": "longenoughpass1"}).json()["access_token"]
assert c.get("/admin/bacari",
             headers={"Authorization": f"Bearer {normal_tok}"}).status_code == 401, \
    "non-admin user must be rejected"
# the shared token still works alongside
assert c.get("/admin/bacari", headers=ADMIN).status_code == 200
print("admin bootstrap    -> ok (first user admin, others not, token still works)")

print("\nPASS: admin page + bàcaro records + delete + admin users")

# --- bootstrap gating: with SPRITZ_BOOTSTRAP_ADMIN off, a fresh first user is
#     NOT auto-admin (a public prod deploy must not hand admin to whoever
#     registers first). Clear the users table and toggle the flag off. ---
from app import config as _cfg
from app.db import engine as _engine
from app.models import User as _User
from sqlmodel import Session as _Session, delete as _delete

_saved = _cfg.BOOTSTRAP_ADMIN
_cfg.BOOTSTRAP_ADMIN = False
try:
    with _Session(_engine) as _s:
        _s.exec(_delete(_User))
        _s.commit()
    tok = c.post("/auth/register",
                 json={"email": "first@x.io", "password": "longenoughpass1"}).json()["access_token"]
    r = c.get("/admin/bacari", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401, \
        f"bootstrap-off: first user must not be admin, got {r.status_code}"
    print("bootstrap gating   -> ok (off => first user not admin)")
finally:
    _cfg.BOOTSTRAP_ADMIN = _saved

Path("test_admin.db").unlink(missing_ok=True)
