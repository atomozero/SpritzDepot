"""HPKR catalog parser test, against a real fixture.

tests/fixtures/sample.hpkr was generated with Haiku's own package_repo from two
packages (helloapp-1.2.3-4-x86_64, otherapp-0.9-1-x86_64). The parser must
reproduce exactly the canonical filenames package_repo records, so this guards
the binary format handling (endianness, string table, attribute type enums,
nested version).
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

from pathlib import Path
from app import hpkr

FIXTURE = Path(__file__).parent / "tests" / "fixtures" / "sample.hpkr"

blob = FIXTURE.read_bytes()
pkgs = hpkr.parse_catalog(blob)
got = sorted(p.filename() for p in pkgs)
want = ["helloapp-1.2.3-4-x86_64.hpkg", "otherapp-0.9-1-x86_64.hpkg"]
assert got == want, f"got {got}, want {want}"
print("parse_catalog      -> ok", got)

# arch + version decoded correctly
hello = [p for p in pkgs if p.name == "helloapp"][0]
assert hello.architecture == "x86_64" and hello.version == "1.2.3-4", hello
print("fields decoded     -> ok (arch x86_64, version 1.2.3-4)")

# bad magic is rejected
try:
    hpkr.parse_catalog(b"NOPE" + blob[4:])
    raise SystemExit("FAIL: bad magic accepted")
except hpkr.HpkrError:
    print("bad magic rejected -> ok")

# resolve_from_repo with a fake HTTP client serving the fixture
class FakeResp:
    status_code = 200
    content = blob
    def raise_for_status(self): pass

class FakeClient:
    def get(self, url, headers=None, params=None):
        assert url.endswith("/repo"), url
        return FakeResp()

urls = hpkr.resolve_from_repo("https://tap.example.org/repo", "helloapp",
                              client=FakeClient())
assert urls == {"x86_64": {"url":
        "https://tap.example.org/repo/packages/helloapp-1.2.3-4-x86_64.hpkg"}}, urls
assert "sha256" not in urls["x86_64"], "hpkr resolve must not invent a sha256"
print("resolve_from_repo  -> ok (url composed, no sha256)")

# missing package -> error
try:
    hpkr.resolve_from_repo("https://tap.example.org/repo", "nope",
                           client=FakeClient())
    raise SystemExit("FAIL: missing package accepted")
except hpkr.HpkrError:
    print("missing package    -> ok")

# --- POST /repo/import-hpkr: admin-gated, creates one cichéto per package ---
import app.main as main
from app.db import init_db
from fastapi.testclient import TestClient

init_db()

# Make the endpoint's httpx fetch return our fixture instead of hitting network.
class _FakeStreamResp:
    status_code = 200
    content = blob
    def raise_for_status(self): pass
class _FakeHttpxClient:
    def __init__(self, *a, **k): pass
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, url, headers=None, params=None): return _FakeStreamResp()
    def close(self): pass

_orig_client = main.httpx.Client
main.httpx.Client = _FakeHttpxClient
try:
    c = TestClient(main.app)
    ADMIN = {"X-Admin-Token": os.environ["SPRITZ_ADMIN_TOKEN"]}
    # gated
    assert c.post("/repo/import-hpkr",
                  json={"repo_url": "https://x/repo", "bacaro": "t"}).status_code == 401
    # HaikuPorts URLs refused (bridge, not re-serve)
    assert c.post("/repo/import-hpkr",
                  json={"repo_url": "https://eu.hpkg.haiku-os.org/haikuports/x",
                        "bacaro": "hp"}, headers=ADMIN).status_code == 400
    # import the fixture's two packages
    r = c.post("/repo/import-hpkr",
               json={"repo_url": "https://tap.example.org/repo", "bacaro": "tap"},
               headers=ADMIN)
    assert r.status_code == 200, r.text
    body_ = r.json()
    assert body_["found_in_catalog"] == 2 and len(body_["ingested"]) == 2, body_
    # the imported cichéto resolves live to the package URL
    res = c.get("/resolve/repo.tap.helloapp?channel=stable&arch=x86_64").json()
    assert res["source"] == "hpkr-repo"
    assert res["artifacts"]["x86_64"]["url"].endswith(
        "/packages/helloapp-1.2.3-4-x86_64.hpkg"), res
    print("import-hpkr        -> ok (2 imported, resolves live)")
finally:
    main.httpx.Client = _orig_client

print("\nPASS: HPKR parser + resolve_from_repo + import-hpkr")
