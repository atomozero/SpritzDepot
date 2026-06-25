"""Security checks for /ingest and the prod config gate.

Runs in-process (FastAPI TestClient), no network, no long-running server.
Run with the admin token set:

    SPRITZ_ENV=dev SPRITZ_SECRET=x SPRITZ_ADMIN_TOKEN=test-admin-secret-123 \
        python test_security.py
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "test-secret")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "test-admin-secret-123")

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from app.main import app

ADMIN = os.environ["SPRITZ_ADMIN_TOKEN"]
c = TestClient(app)


def _make_local_git_bacaro() -> str:
    """Turn sample-bacaro/ into a throwaway local git repo and return its path.

    Keeps the happy-path test offline: /ingest clones this local repo instead
    of reaching the network.
    """
    src = Path("sample-bacaro").resolve()
    repo = Path(tempfile.mkdtemp(prefix="bacaro-git-")) / "vepro"
    repo.mkdir()
    for f in src.glob("*.yaml"):
        (repo / f.name).write_text(f.read_text())
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    run = lambda *a: subprocess.run(a, cwd=repo, env=env, check=True,
                                    capture_output=True)
    run("git", "init", "-q")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return str(repo)


git_url = _make_local_git_bacaro()
body = {"git_url": git_url, "bacaro": "vepro"}

r1 = c.post("/ingest", json=body)
print("ingest no token     ->", r1.status_code)
assert r1.status_code == 401, r1.text

r2 = c.post("/ingest", json=body, headers={"X-Admin-Token": "wrong"})
print("ingest wrong token  ->", r2.status_code)
assert r2.status_code == 401, r2.text

r3 = c.post("/ingest", json=body, headers={"X-Admin-Token": ADMIN})
print("ingest valid token  ->", r3.status_code, r3.json())
assert r3.status_code == 200, r3.text

# Prod gate: missing secrets must raise.
from app import config
saved = (config.IS_PROD, config.SECRET_KEY, config.ADMIN_TOKEN)
config.IS_PROD = True
config.SECRET_KEY = "dev-only-change-me"
config.ADMIN_TOKEN = None
try:
    config.check_prod_config()
    raise SystemExit("FAIL: prod gate did not raise on missing secrets")
except RuntimeError:
    print("prod gate            -> raises on missing secrets (OK)")
finally:
    config.IS_PROD, config.SECRET_KEY, config.ADMIN_TOKEN = saved

print("\nPASS: all security checks")
