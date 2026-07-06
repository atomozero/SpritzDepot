"""The /hvif endpoint: serve an app's raw HVIF blob for client-side SVG rendering.

No hvif2png needed. Covers: a real fixture hpkg yields its 'ncif' blob; the blob
is cached; a second request is served from cache; an app with no hpkg gets a 404
and a negative-cache marker; the templates carry data-hvif so the frontend can
upgrade the icon. Throwaway DB + throwaway cache dir.
"""
import os
import pathlib
import shutil

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_hvif_endpoint.db"
os.environ["SPRITZ_UPLOAD_DIR"] = "/tmp/_hvif_endpoint_cache"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_hvif_endpoint.db" + s).unlink(missing_ok=True)
shutil.rmtree("/tmp/_hvif_endpoint_cache", ignore_errors=True)

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import init_db, engine
from app.models import CichetoRow
import app.main as main
from app import hvif

FIXTURE = pathlib.Path(
    "tests/fixtures/minecraft_installer-1.3.2-1-x86_64.hpkg").resolve()
HPKG = FIXTURE.read_bytes()

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="test.mc", name="MC", bacaro="vepro", channels="stable",
        raw={"id": "test.mc", "name": "MC", "channels": {"stable": {
            "kind": "hpkg",
            "artifacts": {"x86_64": {"url": "https://x/mc.hpkg"}}}}}))
    s.merge(CichetoRow(id="test.noicon", name="NoIcon", bacaro="vepro",
        channels="stable",
        raw={"id": "test.noicon", "name": "NoIcon", "channels": {"stable": {}}}))
    s.commit()

# Stub the hpkg fetch so extraction is offline: return the fixture bytes.
_orig = hvif.hvif_blob_from_hpkg_url
def _fake_blob(url, client=None):
    return hvif._extract_hvif(HPKG)
hvif.hvif_blob_from_hpkg_url = _fake_blob
main.hvif.hvif_blob_from_hpkg_url = _fake_blob
try:
    c = TestClient(main.app)

    # --- app with an hpkg -> raw HVIF blob ---
    r = c.get("/hvif/test.mc")
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"ncif", r.content[:8]
    assert len(r.content) > 1000, len(r.content)
    print("hvif blob served   -> ok (ncif,", len(r.content), "bytes)")

    # --- cached: file written under the hvif cache dir ---
    cached = pathlib.Path("/tmp/_hvif_endpoint_cache/hvif/test.mc.hvif")
    assert cached.is_file() and cached.read_bytes()[:4] == b"ncif"
    # second request still 200 (served from cache; break the extractor to prove it)
    hvif.hvif_blob_from_hpkg_url = lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not re-extract"))
    main.hvif.hvif_blob_from_hpkg_url = hvif.hvif_blob_from_hpkg_url
    assert c.get("/hvif/test.mc").status_code == 200
    hvif.hvif_blob_from_hpkg_url = _fake_blob
    main.hvif.hvif_blob_from_hpkg_url = _fake_blob
    print("hvif cache         -> ok (second hit from disk)")

    # --- app with no hpkg -> 404 + negative cache ---
    r = c.get("/hvif/test.noicon")
    assert r.status_code == 404, r.text
    assert pathlib.Path("/tmp/_hvif_endpoint_cache/hvif/test.noicon.none").is_file()
    print("no-icon 404 + miss -> ok")

    # --- unknown app -> 404 ---
    assert c.get("/hvif/does.not.exist").status_code == 404
    # --- path traversal guard ---
    assert c.get("/hvif/..%2Fevil").status_code in (400, 404)
    print("404 + traversal    -> ok")

    # --- templates carry data-hvif so the frontend upgrades icons ---
    page = c.get("/app/test.mc").text
    assert 'data-hvif="test.mc"' in page, "app page must tag its icon with data-hvif"
    assert "/static/icon.js" in page and "/static/haikon_full.js" in page
    print("templates wired    -> ok (data-hvif + scripts)")
finally:
    hvif.hvif_blob_from_hpkg_url = _orig
    main.hvif.hvif_blob_from_hpkg_url = _orig
    shutil.rmtree("/tmp/_hvif_endpoint_cache", ignore_errors=True)
    for s in ("", "-wal", "-shm"):
        pathlib.Path("test_hvif_endpoint.db" + s).unlink(missing_ok=True)

print("\nPASS: /hvif endpoint + client-side icon wiring")
