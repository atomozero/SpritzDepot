"""Frontend smoke test (server-rendered pages), in-process, no network.

Renders the home, a search, an app page, and the static assets, asserting the
key elements task 03 requires: search box, HaikuPorts bridge badge/note, the
install section with channels, and the degrading-button script.

    SPRITZ_SECRET=x SPRITZ_ADMIN_TOKEN=t python test_frontend.py
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "test-secret")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "test-admin-secret-123")

from pathlib import Path

from app.db import init_db
from app.ingest import ingest_directory

init_db()
ingest_directory(Path("sample-bacaro"), "vepro")

from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

# Home
h = c.get("/")
assert h.status_code == 200, h.text
assert 'name="q"' in h.text, "home should have a search box"
assert "Genio" in h.text, "home should list the seeded app"
print("home               -> ok")

# Search
hq = c.get("/?q=genio")
assert hq.status_code == 200 and "Genio" in hq.text
assert "anche su HaikuPorts" in hq.text, "bridge badge should show"
empty = c.get("/?q=zzzznomatch")
assert "Nessun risultato" in empty.text, "empty search should say so"
print("search             -> ok")

# Categories + filters
cats = c.get("/api/categories").json()
assert {"category": "editors", "count": 1} in cats, cats
assert [a["id"] for a in c.get("/search?category=development").json()["results"]] == ["org.haiku.genio"]
assert c.get("/search?category=dev").json()["results"] == [], "partial category must not match"
vepro_ids = {a["id"] for a in c.get("/search?bacaro=vepro").json()["results"]}
assert "org.haiku.genio" in vepro_ids, vepro_ids
assert c.get("/search?bacaro=nope").json()["results"] == []
# pagination shape
_pg = c.get("/search?limit=1&offset=0").json()
assert _pg["limit"] == 1 and "total" in _pg and len(_pg["results"]) <= 1, _pg
catpg = c.get("/categories")
assert catpg.status_code == 200 and "editors" in catpg.text
hf = c.get("/?category=editors").text
assert "Genio" in hf and "editors" in hf  # filtered-by-category view
assert "/?category=editors" in c.get("/?q=genio").text, "category badge must be a link"
print("categories+filters -> ok")

# Add-to-library button on the app page
_ap = c.get("/app/org.haiku.genio").text
assert 'id="lib-add"' in _ap and "library-add.js" in _ap, "add-to-library button missing"
assert c.get("/static/library-add.js").status_code == 200
print("add-to-library     -> ok")

# App page
ap = c.get("/app/org.haiku.genio")
assert ap.status_code == 200, ap.text
assert "Anche su HaikuPorts" in ap.text, "bridge note missing"
assert "Canale stable" in ap.text and "Canale ombra" in ap.text, "channels missing"
assert "install-button.js" in ap.text, "degrading button script missing"
assert "spritz" in ap.text.lower()
print("app page           -> ok")

# 404
assert c.get("/app/does.not.exist").status_code == 404
print("missing app 404    -> ok")

# Login page + shared auth.js wired into every page
lg = c.get("/login")
assert lg.status_code == 200 and 'id="auth-form"' in lg.text
assert c.get("/static/auth.js").status_code == 200
assert c.get("/static/login.js").status_code == 200
assert "/static/auth.js" in c.get("/").text, "auth.js must load on every page"
assert 'id="nav-login"' in c.get("/").text, "header must have a login link"
print("login page         -> ok")

# i18n: language picker + cookie-driven translation
_home = c.get("/").text
assert '<select class="lang-picker"' in _home, "language <select> missing"
assert '<option value="de"' in _home and '<option value="ja"' in _home
c.cookies.set("lang", "de")
assert "Der Software-Katalog für Haiku" in c.get("/").text, "German hero missing"
c.cookies.set("lang", "fr")
assert "Le catalogue de logiciels pour Haiku" in c.get("/").text
sl = c.get("/set-lang/es", follow_redirects=False)
assert sl.status_code == 303 and "lang=es" in sl.headers.get("set-cookie", "")
c.cookies.delete("lang")
print("i18n               -> ok")

# Haiku SVG placeholder (used when an app has no extractable icon)
ph = c.get("/placeholder.svg?name=Blender")
assert ph.status_code == 200 and ph.headers["content-type"].startswith("image/svg")
assert ph.text.lstrip().startswith("<svg") and ">B<" in ph.text
# the home card falls back to it
assert "/placeholder.svg?name=" in c.get("/?q=genio").text
print("svg placeholder    -> ok")

# Static + bootstrap + api
assert c.get("/static/spritz.css").status_code == 200
js = c.get("/static/install-button.js")
assert js.status_code == 200 and "spritz://install/" in js.text
assert c.get("/get-spritz").status_code == 200
assert c.get("/api").json().get("service") == "spritz registry"
print("static/api         -> ok")

# Publish page + generation flow
pub = c.get("/publish")
assert pub.status_code == 200 and 'id="publish-form"' in pub.text
assert c.get("/static/publish.js").status_code == 200
form = {"id": "org.test.pub", "name": "Pub", "summary": "test",
        "bacaro": "tap", "arch": "x86_64",
        "hpkg_url": "https://e.org/pub-1.0-x86_64.hpkg", "sha256": "a" * 64,
        "version": "1.0", "haikuports": "pub"}
assert c.post("/publish", json=form).status_code == 401, "publish must require auth"
_tok = c.post("/auth/register",
              json={"email": "pubtest@x.io", "password": "longenough1"}).json()["access_token"]
form_icon = dict(form, icon="https://example.org/icon.png")
gen = c.post("/publish", json=form_icon, headers={"Authorization": f"Bearer {_tok}"})
assert gen.status_code == 200, gen.text
assert "org.test.pub.yaml" in gen.headers.get("content-disposition", "")
assert "icon: https://example.org/icon.png" in gen.text, "icon URL should be in the YAML"
# a bad icon URL is rejected by the schema
assert c.post("/publish", json=dict(form, icon="not-a-url"),
              headers={"Authorization": f"Bearer {_tok}"}).status_code == 422
# Round-trip: the generated YAML must ingest cleanly.
import tempfile, yaml as _yaml
from app.ingest import ingest_directory
_d = Path(tempfile.mkdtemp())
(_d / "org.test.pub.yaml").write_text(gen.text)
rep = ingest_directory(_d, "tap")
assert rep["ingested"] == ["org.test.pub"] and not rep["failed"], rep
print("publish round-trip -> ok")

# Image upload (convenience) + serving + validation
import struct as _struct, zlib as _zlib
def _png():
    sig = b"\x89PNG\r\n\x1a\n"
    def chunk(t, d):
        return _struct.pack(">I", len(d)) + t + d + _struct.pack(">I", _zlib.crc32(t + d) & 0xffffffff)
    ihdr = _struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = _zlib.compress(b"\x00\xff\x00\x00")
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")
_png_bytes = _png()
_ut = c.post("/auth/register",
             json={"email": "up@x.io", "password": "longenough1"}).json()["access_token"]
_ua = {"Authorization": f"Bearer {_ut}"}
assert c.post("/upload/image?kind=icon",
              files={"file": ("i.png", _png_bytes, "image/png")}).status_code == 401
up = c.post("/upload/image?kind=icon",
            files={"file": ("i.png", _png_bytes, "image/png")}, headers=_ua)
assert up.status_code == 200, up.text
served = c.get("/assets/" + up.json()["filename"])
assert served.status_code == 200 and served.content == _png_bytes
# a renamed non-image is rejected by magic bytes
assert c.post("/upload/image?kind=icon",
              files={"file": ("x.png", b"not an image", "image/png")},
              headers=_ua).status_code == 400
assert c.get("/assets/..%2f..%2fspritz.db").status_code in (400, 404)
print("image upload       -> ok")

# 'My apps' page + library API (name + state)
lp = c.get("/library-page")
assert lp.status_code == 200 and 'id="lib-list"' in lp.text
assert c.get("/static/library.js").status_code == 200
_lt = c.post("/auth/register",
             json={"email": "libtest@x.io", "password": "longenough1"}).json()["access_token"]
_la = {"Authorization": f"Bearer {_lt}"}
assert c.get("/library", headers=_la).json() == [], "new user library is empty"
c.post("/library/org.haiku.genio", json={"channel": "stable", "arch": "x86_64"},
       headers=_la)
lib = c.get("/library", headers=_la).json()
assert lib and lib[0]["name"] == "Genio" and lib[0]["state"] == "pending", lib
# remove it again -> library empty; idempotent; needs auth
assert c.post("/library/org.haiku.genio/remove", headers=_la).status_code == 200
assert c.get("/library", headers=_la).json() == [], "remove should empty the library"
assert c.post("/library/org.haiku.genio/remove", headers=_la).status_code == 200  # idempotent
assert c.post("/library/org.haiku.genio/remove").status_code == 401  # needs auth
assert 'data-s-remove' in c.get("/library-page").text
print("my-apps library    -> ok (add + remove)")

# Italian copy + no em dashes in templates (project rule)
for tmpl in Path("app/templates").glob("*.html"):
    assert "—" not in tmpl.read_text(), f"em dash found in {tmpl.name}"
print("no em dashes       -> ok")

print("\nPASS: frontend smoke test")
