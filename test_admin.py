"""Admin page + bàcaro records test, offline (local git bàcaro)."""
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "test-admin-secret-123")

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
assert rec[0]["last_ingested"] == 1 and rec[0]["last_error"] is None
print("ingest record      -> ok")

# a failing ingest records the error and does not crash
bad = c.post("/ingest", json={"git_url": "ssh://nope/x", "bacaro": "badtap"},
             headers=ADMIN)
assert bad.status_code == 400, bad.text
badrec = [r for r in c.get("/admin/bacari", headers=ADMIN).json()
          if r["slug"] == "badtap"]
assert badrec and badrec[0]["last_error"], badrec
print("error record       -> ok")

print("\nPASS: admin page + bàcaro records")
