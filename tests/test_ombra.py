"""Tests for the ombra (github-latest) resolver, fully offline.

Uses a fake httpx client that returns a canned GitHub releases payload, so no
network and deterministic. Covers: repo-from-homepage, prerelease skipping,
asset pattern matching per arch, and the /resolve route integration (no
sha256 in ombra output).
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "test-secret")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

# This test merges rows into the DB; use a throwaway, never the real catalog.
from tests import test_db_guard  # noqa: E402
test_db_guard.use_throwaway_db("test_ombra")

from app import ombra


class FakeResp:
    def __init__(self, status, payload, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Stands in for httpx.Client; returns the releases payload it was given."""
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self._status = status
        self._text = text
        self.requested = None

    def get(self, url, headers=None, params=None):
        self.requested = url
        return FakeResp(self._status, self._payload, self._text)


RELEASES = [
    {"tag_name": "v9.9", "draft": True, "prerelease": False, "assets": []},
    {"tag_name": "v2.0-rc1", "draft": False, "prerelease": True, "assets": [
        {"name": "genio-2.0rc1-x86_64.hpkg", "browser_download_url": "https://x/rc.hpkg"},
    ]},
    {"tag_name": "v1.5", "draft": False, "prerelease": False, "assets": [
        {"name": "genio-1.5-x86_64.hpkg", "browser_download_url": "https://x/genio-1.5-x86_64.hpkg"},
        {"name": "genio-1.5-x86_gcc2h.hpkg", "browser_download_url": "https://x/genio-1.5-x86_gcc2h.hpkg"},
        {"name": "SHA256SUMS", "browser_download_url": "https://x/sums"},
    ]},
]


# --- repo_from_homepage ---
assert ombra.repo_from_homepage("https://github.com/Genio-The-Haiku-IDE/Genio") \
    == "Genio-The-Haiku-IDE/Genio"
assert ombra.repo_from_homepage("https://github.com/owner/name.git") == "owner/name"
assert ombra.repo_from_homepage("https://example.org/x") is None
assert ombra.repo_from_homepage(None) is None
print("repo_from_homepage -> ok")

# --- stable release, prerelease excluded: picks v1.5, matches both arches ---
res = ombra.resolve_github_latest(
    "owner/genio", "genio-*-{arch}.hpkg", ["x86_64", "x86_gcc2h"],
    prerelease=False, client=FakeClient(RELEASES))
assert res.version == "1.5", res.version
assert res.artifacts["x86_64"] == "https://x/genio-1.5-x86_64.hpkg"
assert res.artifacts["x86_gcc2h"] == "https://x/genio-1.5-x86_gcc2h.hpkg"
print("latest stable      -> ok (1.5, both arches matched)")

# --- prerelease allowed: picks the rc, only x86_64 asset present ---
res2 = ombra.resolve_github_latest(
    "owner/genio", "genio-*-{arch}.hpkg", ["x86_64", "x86_gcc2h"],
    prerelease=True, client=FakeClient(RELEASES))
assert res2.version == "2.0-rc1", res2.version
assert res2.artifacts.get("x86_64") == "https://x/rc.hpkg"
assert "x86_gcc2h" not in res2.artifacts  # no matching asset in the rc
print("prerelease         -> ok (rc picked, missing arch absent)")

# --- error paths ---
try:
    ombra.resolve_github_latest("bad repo", "p-{arch}", ["x86_64"],
                                client=FakeClient(RELEASES))
    raise SystemExit("FAIL: invalid repo accepted")
except ombra.OmbraError:
    pass

try:
    ombra.resolve_github_latest("o/n", "p-{arch}", ["x86_64"],
                                client=FakeClient([], status=200))
    raise SystemExit("FAIL: empty releases accepted")
except ombra.OmbraError:
    pass
print("error paths        -> ok")

# --- /resolve route integration: ombra returns urls without sha256 ---
import app.main as main
from app.db import init_db
from sqlmodel import Session
from app.db import engine
from app.models import CichetoRow

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(
        id="org.haiku.genio", name="Genio", summary="IDE", bacaro="vepro",
        channels="ombra",
        raw={
            "id": "org.haiku.genio", "name": "Genio",
            "homepage": "https://github.com/Genio-The-Haiku-IDE/Genio",
            "channels": {"ombra": {
                "kind": "hpkg", "source": "github-latest",
                "match": "genio-*-{arch}.hpkg", "prerelease": False,
                "artifacts": {"x86_64": {}},  # arch hint
            }},
        },
    ))
    s.commit()

# Monkeypatch the resolver so the route does not hit the network.
_orig = ombra.resolve_github_latest
def _fake_resolve(repo, match, arches, prerelease=False, client=None):
    return _orig(repo, match, arches, prerelease=prerelease,
                 client=FakeClient(RELEASES))
ombra.resolve_github_latest = _fake_resolve
try:
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    r = c.get("/resolve/org.haiku.genio?channel=ombra&arch=x86_64")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.5", body
    art = body["artifacts"]["x86_64"]
    assert art["url"] == "https://x/genio-1.5-x86_64.hpkg", art
    assert "sha256" not in art, "ombra must not carry a pre-computed sha256"
    print("/resolve ombra     -> ok (live url, no sha256)")

    # /library/pending must resolve ombra live too (one poll, no extra call).
    tok = c.post("/auth/register",
                 json={"email": "ombra@x.io", "password": "longenoughpass1"}).json()["access_token"]
    auth = {"Authorization": f"Bearer {tok}"}
    q = c.post("/library/org.haiku.genio",
               json={"channel": "ombra", "arch": "x86_64"}, headers=auth)
    assert q.status_code == 200, q.text
    pend = c.get("/library/pending", headers=auth)
    assert pend.status_code == 200, pend.text
    items = pend.json()
    assert len(items) == 1, items
    it = items[0]
    assert it["channel"] == "ombra" and it["version"] == "1.5", it
    assert it["artifacts"]["x86_64"]["url"] == "https://x/genio-1.5-x86_64.hpkg", it
    assert "sha256" not in it["artifacts"]["x86_64"], "ombra pending: no sha256"
    print("/library/pending   -> ok (ombra resolved live in the poll)")
finally:
    ombra.resolve_github_latest = _orig

print("\nPASS: ombra resolver + /resolve + /library/pending integration")
