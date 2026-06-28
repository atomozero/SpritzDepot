"""End-to-end test for the repo-proxy layer (task 01), fully offline.

Builds a real hpkg with Haiku's `package` tool, serves it from a local HTTP
server, points a cichéto at it (with the real sha256), then drives:
  POST /repo/build  -> fetch+verify, read vendor, package_repo create
  GET  .../repo.info, .../repo, .../packages/<file>

Requires the host-built Haiku tools. Point at them with:
  SPRITZ_PACKAGE_REPO_BIN=/path/to/tools/package_repo/package_repo python test_repo_proxy.py
The `package` tool and the shared libs must sit in the sibling layout the
spike produces (tools/package/package and lib/ two levels up).
"""
import hashlib
import http.server
import os
import socketserver
import subprocess
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "test-secret")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "test-admin-secret-123")

TOOL = os.environ.get("SPRITZ_PACKAGE_REPO_BIN")
if not TOOL or not Path(TOOL).is_file():
    raise SystemExit("set SPRITZ_PACKAGE_REPO_BIN to the host-built package_repo")

WORK = Path(tempfile.mkdtemp(prefix="spritz-repoproxy-"))
os.environ["SPRITZ_REPO_CACHE"] = str(WORK / "cache")

PACKAGE = Path(TOOL).parent.parent / "package" / "package"


def _tool_env():
    env = dict(os.environ)
    for parent in Path(TOOL).resolve().parents:
        if (parent / "lib" / "libpackage_build.so").is_file():
            env["LD_LIBRARY_PATH"] = str(parent / "lib")
            break
    return env


def build_hpkg(name: str, vendor: str, arch: str = "x86_64") -> Path:
    root = WORK / f"{name}-root"
    (root / "apps").mkdir(parents=True, exist_ok=True)
    (root / "apps" / name).write_text(f"#!/bin/sh\necho {name}\n")
    (root / ".PackageInfo").write_text(
        f'name\t\t\t{name}\n'
        f'version\t\t\t1.0-1\n'
        f'architecture\t{arch}\n'
        f'summary\t\t\t"test package {name}"\n'
        f'description\t\t"built by test_repo_proxy"\n'
        f'packager\t\t"tester <t@t>"\n'
        f'vendor\t\t\t"{vendor}"\n'
        f'licenses\t\t"MIT"\n'
        f'copyrights\t\t"2026 test"\n'
        f'provides {{\n\t{name} = 1.0\n}}\n'
    )
    out = WORK / f"{name}-1.0-1-{arch}.hpkg"
    subprocess.run([str(PACKAGE), "create", "-C", str(root), str(out)],
                   env=_tool_env(), check=True, capture_output=True)
    return out


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 1. Build a real hpkg and serve the WORK dir over HTTP.
hpkg = build_hpkg("genio", vendor="Genio Team")
digest = sha256(hpkg)

httpd = socketserver.TCPServer(
    ("127.0.0.1", 0),
    lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(WORK), **k),
)
port = httpd.server_address[1]
threading.Thread(target=httpd.serve_forever, daemon=True).start()
asset_url = f"http://127.0.0.1:{port}/{hpkg.name}"

# 2. Seed the cache with a cichéto pointing at that asset (real sha256).
from app.db import init_db, engine
from sqlmodel import Session
from app.models import CichetoRow

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(
        id="org.haiku.genio", name="Genio", summary="IDE", bacaro="vepro",
        channels="stable", haikuports="genio",
        raw={
            "id": "org.haiku.genio", "name": "Genio",
            "channels": {"stable": {
                "version": "1.0", "kind": "hpkg",
                "artifacts": {"x86_64": {"url": asset_url, "sha256": digest}},
            }},
        },
    ))
    s.commit()

# 3. Drive the API.
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
admin = {"X-Admin-Token": os.environ["SPRITZ_ADMIN_TOKEN"]}

# build must be admin-gated
assert c.post("/repo/build").status_code == 401, "build should require admin"

r = c.post("/repo/build", headers=admin)
print("build ->", r.status_code, r.json())
assert r.status_code == 200, r.text
data = r.json()
assert not data["errors"], data["errors"]
assert data["built"] and data["built"][0]["packages"] == 1, data

# Use the advertised URL exactly as a client would (strip the host prefix for
# the in-process TestClient).
full_url = data["built"][0]["url"]
base = full_url.split("/current")[0].split("8000")[-1] + "/current"

info = c.get(f"{base}/repo.info")
print("repo.info ->", info.status_code)
assert info.status_code == 200 and "Genio Team" in info.text, info.text

cat = c.get(f"{base}/repo")
print("repo (HPKR) ->", cat.status_code, len(cat.content), "bytes")
assert cat.status_code == 200 and cat.content[:4] == b"hpkr", "catalog should be HPKR"

pkg = c.get(f"{base}/packages/{hpkg.name}")
print("package ->", pkg.status_code, len(pkg.content), "bytes")
assert pkg.status_code == 200, pkg.text
assert hashlib.sha256(pkg.content).hexdigest() == digest, "served package must match the verified hpkg"

# path traversal guard
assert c.get(f"{base}/packages/..%2f..%2frepo.info").status_code in (400, 404)

httpd.shutdown()
print("\nPASS: repo-proxy end to end (build, repo.info, HPKR catalog, verified package)")
