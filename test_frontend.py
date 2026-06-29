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
print("my-apps library    -> ok")

# Italian copy + no em dashes in templates (project rule)
for tmpl in Path("app/templates").glob("*.html"):
    assert "—" not in tmpl.read_text(), f"em dash found in {tmpl.name}"
print("no em dashes       -> ok")

print("\nPASS: frontend smoke test")
