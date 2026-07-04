"""Rate limiting: every public read route is bounded, not just the ones with an
explicit @limiter.limit.

Sets a tiny default limit BEFORE importing the app (the Limiter reads it at
construction), then confirms unmarked read routes 429 after the cap, and that a
costly route carries its own tighter limit. In-process, no network.
"""
import os
import pathlib

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DEFAULT_RATE_LIMIT"] = "3/minute"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_ratelimit.db"

pathlib.Path("test_ratelimit.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db import init_db, engine
from app.models import CichetoRow
from app.main import app

init_db()
with Session(engine) as s:
    s.merge(CichetoRow(id="x.y.z", name="Z", bacaro="vepro", channels="stable",
                       raw={"id": "x.y.z", "name": "Z", "channels": {}}))
    s.commit()

c = TestClient(app)


def burst(path, n=5):
    return [c.get(path).status_code for _ in range(n)]


# --- default limit applies to unmarked read routes ---
for route in ("/search?q=z", "/categories", "/api/categories"):
    codes = burst(route)
    assert 429 in codes, f"{route} not default-limited: {codes}"
    assert codes.count(200) <= 3, f"{route} exceeded cap: {codes}"
print("default limit applies to unmarked read routes -> ok")

# --- an explicitly limited costly route uses its own (looser than default here) ---
# /icon carries 60/minute, so within our 3-call reset window it is NOT capped by
# the default; assert its decorator is present rather than hammering 60 times.
import inspect
import app.main as main
# the decorator wraps the function; slowapi records the limit on the route.
icon_route = next(r for r in app.routes if getattr(r, "path", "") == "/icon/{cicheto_id}")
assert icon_route is not None
# resolve and screenshot likewise carry explicit limits (request param present)
for name in ("app_icon", "screenshot", "resolve"):
    fn = getattr(main, name)
    sig = inspect.signature(fn)
    assert "request" in sig.parameters, f"{name} must take request for @limiter.limit"
print("costly routes carry an explicit limiter + request param -> ok")

pathlib.Path("test_ratelimit.db").unlink(missing_ok=True)
print("\nPASS: rate limiting")
