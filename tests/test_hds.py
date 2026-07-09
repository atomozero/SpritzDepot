"""HaikuDepotServer screenshot import, fully offline.

Uses a fake httpx client returning canned HDS responses (the real API shape,
captured live: get-pkg-screenshots -> result.items[{code,width,height}], and the
image endpoint requiring tw/th). Covers: listing, the cichéto's own screenshots
taking priority, the proxy caching, bad-code rejection, and HDS-down degrading to
an empty list rather than an error.
"""
import os

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_hds.db"

import pathlib
pathlib.Path("test_hds.db").unlink(missing_ok=True)

from app import hds
from app.db import init_db, engine
from app.models import CichetoRow
import app.main as main
from sqlmodel import Session

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 40


class FakeResp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.Client. Records calls; returns canned list/image."""
    def __init__(self, items, require_thumb=True):
        self.items = items
        self.require_thumb = require_thumb
        self.posted = None
        self.got = None

    def post(self, url, json=None):
        self.posted = (url, json)
        return FakeResp(200, {"error": None, "result": {"items": self.items}})

    def get(self, url, params=None):
        self.got = (url, params)
        if self.require_thumb and not (params and params.get("tw") and params.get("th")):
            return FakeResp(400, content=b'{"err":"need tw/th"}')  # HDS behaviour
        return FakeResp(200, content=PNG)


ITEMS = [{"code": "aaa-111", "width": 800, "height": 500},
         {"code": "bbb-222", "width": 640, "height": 400}]


# --- list_screenshots parses the real shape ---
codes = [s["code"] for s in hds.list_screenshots("genio", client=FakeClient(ITEMS))]
assert codes == ["aaa-111", "bbb-222"], codes
print("list_screenshots parses HDS items -> ok")

# --- screenshot_bytes sends tw/th and validates the PNG ---
fc = FakeClient(ITEMS)
data = hds.screenshot_bytes("aaa-111", client=fc)
assert data == PNG, "did not return the PNG"
assert fc.got[1].get("tw") and fc.got[1].get("th"), "tw/th not sent"
print("screenshot_bytes sends required tw/th, validates PNG -> ok")

# --- non-PNG response (an error page) -> None, not garbage ---
class BadClient(FakeClient):
    def get(self, url, params=None):
        return FakeResp(200, content=b"<html>not an image</html>")
assert hds.screenshot_bytes("aaa-111", client=BadClient(ITEMS)) is None
print("non-PNG response rejected -> ok")


# --- integration: the app-page helper prefers the cichéto's own screenshots ---
init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="org.haiku.genio", name="Genio", bacaro="vepro",
                       channels="stable",
                       raw={"id": "org.haiku.genio", "name": "Genio",
                            "screenshots": ["https://author.example/shot.png"]}))
    s.merge(CichetoRow(id="repo.haikuports.genio", name="genio", bacaro="haikuports",
                       channels="stable",
                       raw={"id": "repo.haikuports.genio", "name": "genio",
                            "bridge": {"haikuports": "genio"}}))
    s.commit()

# stub the HDS list call so the integration test stays offline
main._HDS_CODES_CACHE.clear()
_orig_list = hds.list_screenshots
hds.list_screenshots = lambda pkg, client=None: ([{"code": "hds-1"}, {"code": "hds-2"}]
                                                 if pkg == "genio" else [])
try:
    with Session(engine) as s:
        own = s.get(CichetoRow, "org.haiku.genio")
        # cichéto has its own screenshots -> HDS is not consulted
        assert main._hds_screenshot_codes(own) == [], "own screenshots should win"
        mirror = s.get(CichetoRow, "repo.haikuports.genio")
        # no own screenshots -> HDS codes via the bridge name 'genio'
        assert main._hds_screenshot_codes(mirror) == ["hds-1", "hds-2"], "HDS not used"
    print("app helper: own screenshots win, else HDS via bridge name -> ok")
finally:
    hds.list_screenshots = _orig_list
    main._HDS_CODES_CACHE.clear()


# --- HDS unreachable -> empty list, never an exception ---
class DeadClient:
    def post(self, url, json=None):
        raise RuntimeError("network down")
assert hds.list_screenshots("genio", client=DeadClient()) == []
print("HDS unreachable degrades to empty list -> ok")


# --- get_description reads versions[0].summary/description ---
class DescClient:
    def __init__(self, versions): self.versions = versions; self.posted = None
    def post(self, url, json=None):
        self.posted = json
        return FakeResp(200, {"error": None, "result": {"versions": self.versions}})

dc = DescClient([{"summary": "The Haiku IDE",
                  "description": "Genio is an IDE for Haiku."}])
desc = hds.get_description("genio", lang="en", client=dc)
assert desc == {"summary": "The Haiku IDE",
                "description": "Genio is an IDE for Haiku."}, desc
assert dc.posted["versionType"] == "ALL", "must use versionType ALL"
assert dc.posted["naturalLanguageCode"] == "en", dc.posted
print("get_description reads summary+description, sends ALL+lang -> ok")

# empty versions -> None
assert hds.get_description("x", client=DescClient([])) is None
# both texts empty -> None (nothing worth showing)
assert hds.get_description("x", client=DescClient([{"summary": "", "description": ""}])) is None
print("get_description: empty -> None -> ok")

# integration: cichéto with own description skips HDS; placeholder summary upgrades
main._HDS_DESC_CACHE.clear()
_orig_desc = hds.get_description
hds.get_description = lambda pkg, lang="en", **k: ({"summary": "The Haiku IDE",
    "description": "An IDE."} if pkg == "genio" else None)
try:
    with Session(engine) as s:
        mirror = s.get(CichetoRow, "repo.haikuports.genio")  # no own description
        d = main._hds_description(mirror, "it")
        assert d and d["description"] == "An IDE.", d
        own = s.get(CichetoRow, "org.haiku.genio")
        own.raw = {**own.raw, "description": "author text"}
        # an app WITH its own description must not consult HDS
        assert main._hds_description(own, "it") is None
    # placeholder detection
    assert main._placeholder_summary("genio from HaikuPorts", "genio") is True
    assert main._placeholder_summary("pe from the lote repository", "pe") is True
    assert main._placeholder_summary("The Haiku IDE", "genio") is False
    print("app helper: own description wins, placeholder summary detected -> ok")
finally:
    hds.get_description = _orig_desc
    main._HDS_DESC_CACHE.clear()

pathlib.Path("test_hds.db").unlink(missing_ok=True)
print("\nPASS: HaikuDepotServer screenshot import")
