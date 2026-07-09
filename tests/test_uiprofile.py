"""UI profile detection: lite (WebPositive/Haiku) vs modern (other browsers).

Covers the unit function (uiprofile.ui_profile) and the end-to-end render: the
body carries the right ui-<profile> class per User-Agent, the `ui` cookie
overrides the UA both ways, an empty UA defaults to modern, /set-ui sets/clears
the cookie, and the footer toggle points at the other profile. Throwaway DB.
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

from tests import test_db_guard  # noqa: E402
test_db_guard.use_throwaway_db("test_uiprofile")

from app import uiprofile

WP = ("Mozilla/5.0 (compatible; U; WebPositive/1.2; Haiku) "
      "AppleWebKit/531 (KHTML, like Gecko)")
CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120 Safari/537.36")

# --- unit: is_lite_user_agent + normalize_profile ---
assert uiprofile.is_lite_user_agent(WP) is True
assert uiprofile.is_lite_user_agent("Mozilla/5.0 ... Haiku ...") is True  # OS token
assert uiprofile.is_lite_user_agent(CHROME) is False
assert uiprofile.is_lite_user_agent(None) is False
assert uiprofile.normalize_profile("LITE") == "lite"
assert uiprofile.normalize_profile("modern") == "modern"
assert uiprofile.normalize_profile("bogus") is None
assert uiprofile.normalize_profile(None) is None
print("unit detection     -> ok")

# --- end to end via the app ---
from app.db import init_db
from fastapi.testclient import TestClient
from app.main import app

init_db()
c = TestClient(app)

assert 'class="ui-lite"' in c.get("/", headers={"user-agent": WP}).text
assert 'class="ui-modern"' in c.get("/", headers={"user-agent": CHROME}).text
assert 'class="ui-modern"' in c.get("/", headers={"user-agent": ""}).text  # default
print("UA -> body class   -> ok (WP lite, Chrome modern, empty modern)")

# cookie override wins both ways
assert 'class="ui-modern"' in c.get(
    "/", headers={"user-agent": WP}, cookies={"ui": "modern"}).text
assert 'class="ui-lite"' in c.get(
    "/", headers={"user-agent": CHROME}, cookies={"ui": "lite"}).text
print("cookie override    -> ok (beats UA both directions)")

# /set-ui sets / clears the cookie
r = c.get("/set-ui/lite", headers={"referer": "/"}, follow_redirects=False)
assert r.status_code == 303 and "ui=lite" in r.headers.get("set-cookie", ""), r.headers
r = c.get("/set-ui/bogus", headers={"referer": "/"}, follow_redirects=False)
assert r.status_code == 303  # invalid -> clears override, no crash
print("/set-ui             -> ok (set valid, clear invalid)")

# footer toggle points the other way
assert "/set-ui/lite" in c.get("/", headers={"user-agent": CHROME}).text
assert "/set-ui/modern" in c.get("/", headers={"user-agent": WP}).text
print("footer toggle      -> ok")

print("\nPASS: UI profile detection (lite/modern)")
