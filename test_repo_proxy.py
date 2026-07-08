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
    # This test needs Haiku's host-built package_repo, absent in a plain WSL/CI
    # env. Skip cleanly (exit 0) rather than fail, so the suite stays green where
    # the tool is not available; run it explicitly on a machine that has it.
    print("SKIP: test_repo_proxy needs SPRITZ_PACKAGE_REPO_BIN (host-built "
          "package_repo); not set, skipping.")
    raise SystemExit(0)

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
# repo.info must use the correct field names (identifier + baseurl, not url).
assert "identifier" in info.text and "baseurl" in info.text, info.text

cat = c.get(f"{base}/repo")
print("repo (HPKR) ->", cat.status_code, len(cat.content), "bytes")
assert cat.status_code == 200 and cat.content[:4] == b"hpkr", "catalog should be HPKR"

pkg = c.get(f"{base}/packages/{hpkg.name}")
print("package ->", pkg.status_code, len(pkg.content), "bytes")
assert pkg.status_code == 200, pkg.text
assert hashlib.sha256(pkg.content).hexdigest() == digest, "served package must match the verified hpkg"

# path traversal guard
assert c.get(f"{base}/packages/..%2f..%2frepo.info").status_code in (400, 404)

# --- identifier stays stable across rebuilds (point 1) ---
import re as _re
ident1 = _re.search(r'identifier\s+"([^"]+)"', info.text).group(1)
c.post("/repo/build", headers=admin)
info2 = c.get(f"{base}/repo.info")
ident2 = _re.search(r'identifier\s+"([^"]+)"', info2.text).group(1)
print("identifier stable ->", ident1 == ident2)
assert ident1 == ident2, f"identifier changed across rebuild: {ident1} != {ident2}"

# --- sha256 tamper is rejected, no file served (point 4) ---
from app import repo_proxy
import tempfile as _tf
bad_dest = Path(_tf.mkdtemp()) / "tampered.hpkg"
try:
    repo_proxy.fetch_verified(asset_url, "0" * 64, bad_dest)
    raise SystemExit("FAIL: tampered sha256 was accepted")
except repo_proxy.RepoProxyError as e:
    assert "mismatch" in str(e).lower(), e
    assert not bad_dest.exists(), "partial file must be removed on hash mismatch"
print("sha256 tamper      -> rejected, no file left")

# --- automatic rebuild on /ingest (point 3) ---
# Add a second cichéto, ingest it (rebuild=true default), confirm a new sub-repo
# appears without a manual /repo/build.
hpkg2 = build_hpkg("medo", vendor="Zen Team")
dig2 = sha256(hpkg2)
bacaro2 = Path(_tf.mkdtemp()) / "vepro2"
bacaro2.mkdir()
(bacaro2 / "medo.yaml").write_text(
    "cicheto: 1\nid: org.zen.medo\nname: Medo\nsummary: video\n"
    "channels:\n  stable:\n    version: '1.0'\n    kind: hpkg\n    artifacts:\n"
    f"      x86_64:\n        url: {asset_url.rsplit('/',1)[0]}/{hpkg2.name}\n"
    f"        sha256: {dig2}\n"
)
# turn it into a local git repo so /ingest can clone it
subprocess.run(["git", "init", "-q"], cwd=bacaro2, check=True)
subprocess.run(["git", "add", "-A"], cwd=bacaro2, check=True,
               env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t"})
subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=bacaro2, check=True,
               env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
ing = c.post("/ingest", json={"git_url": str(bacaro2), "bacaro": "vepro2"}, headers=admin)
print("ingest+autobuild ->", ing.status_code, ing.json().get("repo", {}).get("built"))
assert ing.status_code == 200, ing.text
built_vendors = {b["vendor"] for b in ing.json()["repo"]["built"]}
assert "Zen Team" in built_vendors, ing.json()
# and the new sub-repo is immediately servable
zen = c.get("/repo/Zen-Team/x86_64/current/repo")
assert zen.status_code == 200 and zen.content[:4] == b"hpkr", "new repo not served"
print("new sub-repo served ->", zen.status_code)

httpd.shutdown()
print("\nPASS: repo-proxy end to end + stable identifier + sha256 tamper + auto-rebuild")
