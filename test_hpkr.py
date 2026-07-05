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

# This test merges rows into the DB; use a throwaway, never the real catalog.
import test_db_guard  # noqa: E402
test_db_guard.use_throwaway_db("test_hpkr")

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

# resolve_from_repo with a fake HTTP client serving the fixture. fetch_catalog
# now streams (guarded + size-capped), so the fake exposes .stream() yielding a
# context-managed response with iter_bytes.
class _FakeStream:
    status_code = 200
    def __init__(self, data): self._data = data
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_bytes(self, n=65536):
        for i in range(0, len(self._data), n):
            yield self._data[i:i + n]

class FakeClient:
    def stream(self, method, url, **k):
        assert url.endswith("/repo"), url
        return _FakeStream(blob)

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

# import-hpkr now fetches via netguard.fetch_guarded (guarded, no blind redirects).
# Patch it to return our fixture instead of hitting the network.
class _FakeBufResp:
    status_code = 200
    content = blob
    def raise_for_status(self): pass

def _fake_fetch_guarded(method, url, **k):
    assert url.endswith("/repo"), url
    return _FakeBufResp()

import contextlib as _ctx

@_ctx.contextmanager
def _fake_stream_guarded(method, url, **k):
    assert url.endswith("/repo"), url
    yield _FakeStream(blob)

_orig_fetch = main.netguard.fetch_guarded
_orig_guard = main.netguard.guard_url
_orig_stream = hpkr.netguard.stream_guarded
main.netguard.fetch_guarded = _fake_fetch_guarded
# The fixture host is fake; skip the real DNS/SSRF guard for this offline test.
# (The guard itself is covered in test_security.) Also serve the live /resolve
# fetch (resolve_from_repo -> fetch_catalog -> stream_guarded) from the fixture.
main.netguard.guard_url = lambda url: None
hpkr.netguard.stream_guarded = _fake_stream_guarded
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

    # /library/pending resolves hpkr-repo live too (not just ombra), so the
    # daemon gets the real download URL in one poll.
    ut = c.post("/auth/register",
                json={"email": "hpkruser@x.io", "password": "longenough1"}).json()["access_token"]
    uauth = {"Authorization": f"Bearer {ut}"}
    c.post("/library/repo.tap.helloapp", json={"channel": "stable", "arch": "x86_64"},
           headers=uauth)
    pend = c.get("/library/pending", headers=uauth).json()
    assert len(pend) == 1, pend
    art = pend[0]["artifacts"].get("x86_64", {})
    assert art.get("url", "").endswith("/packages/helloapp-1.2.3-4-x86_64.hpkg"), pend
    print("pending hpkr-repo  -> ok (resolved live in the poll)")
finally:
    main.netguard.fetch_guarded = _orig_fetch
    main.netguard.guard_url = _orig_guard
    hpkr.netguard.stream_guarded = _orig_stream

print("\nPASS: HPKR parser + resolve_from_repo + import-hpkr")
