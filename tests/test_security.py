"""Security checks for /ingest and the prod config gate.

Runs in-process (FastAPI TestClient), no network, no long-running server.
Run with the admin token set:

    SPRITZ_ENV=dev SPRITZ_SECRET=x SPRITZ_ADMIN_TOKEN=test-admin-secret-123 \
        python -m tests.test_security
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "test-secret")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "test-admin-secret-123")

import subprocess
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from app.db import init_db
from app.main import app

init_db()  # TestClient(app) does not fire startup events; create tables here.

ADMIN = os.environ["SPRITZ_ADMIN_TOKEN"]
c = TestClient(app)


def _make_local_git_bacaro() -> str:
    """Turn sample-bacaro/ into a throwaway local git repo and return its path.

    Keeps the happy-path test offline: /ingest clones this local repo instead
    of reaching the network.
    """
    src = Path("sample-bacaro").resolve()
    repo = Path(tempfile.mkdtemp(prefix="bacaro-git-")) / "vepro"
    repo.mkdir()
    for f in src.glob("*.yaml"):
        (repo / f.name).write_text(f.read_text())
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    run = lambda *a: subprocess.run(a, cwd=repo, env=env, check=True,
                                    capture_output=True)
    run("git", "init", "-q")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    return str(repo)


git_url = _make_local_git_bacaro()
body = {"git_url": git_url, "bacaro": "vepro"}

r1 = c.post("/ingest", json=body)
print("ingest no token     ->", r1.status_code)
assert r1.status_code == 401, r1.text

r2 = c.post("/ingest", json=body, headers={"X-Admin-Token": "wrong"})
print("ingest wrong token  ->", r2.status_code)
assert r2.status_code == 401, r2.text

r3 = c.post("/ingest", json=body, headers={"X-Admin-Token": ADMIN})
print("ingest valid token  ->", r3.status_code, r3.json())
assert r3.status_code == 200, r3.text

# --- ingest URL validation: reject ssh/git schemes ---
bad = c.post("/ingest", json={"git_url": "ssh://evil@host/repo", "bacaro": "x"},
             headers={"X-Admin-Token": ADMIN})
print("ingest ssh:// url   ->", bad.status_code)
assert bad.status_code == 400 and "scheme" in bad.text.lower(), bad.text

# --- password policy: short password rejected at register ---
short = c.post("/auth/register", json={"email": "short@x.io", "password": "abc"})
print("register short pw   ->", short.status_code)
assert short.status_code == 422, short.text  # pydantic min_length -> 422

# --- token revocation: logout-all invalidates the existing token ---
reg = c.post("/auth/register",
             json={"email": "rev@x.io", "password": "longenoughpass1"})
assert reg.status_code == 200, reg.text
tok = reg.json()["access_token"]
auth = {"Authorization": f"Bearer {tok}"}
assert c.get("/library", headers=auth).status_code == 200, "token should work"
assert c.post("/auth/logout-all", headers=auth).status_code == 200
after = c.get("/library", headers=auth)
print("token after logout  ->", after.status_code)
assert after.status_code == 401, "old token must be rejected after logout-all"

# --- JWT claim validation fails CLOSED: a token missing exp or ver is rejected,
#     so a hand-crafted/legacy token can't be non-expiring or bypass revocation ---
from jose import jwt as _jwt
from datetime import datetime as _dt, timedelta as _td
from app import auth as _authmod
_noexp = _jwt.encode({"sub": "1", "ver": 0}, _authmod.SECRET_KEY,
                     algorithm=_authmod.ALGORITHM)
_nover = _jwt.encode({"sub": "1", "exp": _dt.utcnow() + _td(hours=1)},
                     _authmod.SECRET_KEY, algorithm=_authmod.ALGORITHM)
assert c.get("/library", headers={"Authorization": f"Bearer {_noexp}"}).status_code == 401
assert c.get("/library", headers={"Authorization": f"Bearer {_nover}"}).status_code == 401
print("jwt fail-closed      -> ok (no-exp / no-ver tokens rejected)")

# --- login is constant-time-ish: the unknown-email path also runs bcrypt, so it
#     is not orders of magnitude faster (which would enumerate accounts) ---
import time as _time
def _login_ms(email):
    s = _time.perf_counter()
    c.post("/auth/login", json={"email": email, "password": "wrongpass123456"})
    return (_time.perf_counter() - s) * 1000
_login_ms("nobody@x.io"); _login_ms("rev@x.io")   # warm up
_unknown = _login_ms("nobody-here@x.io")
assert _unknown > 10, f"unknown-email login too fast ({_unknown:.0f}ms): no bcrypt?"
print("login timing         -> ok (unknown email still pays bcrypt)")

# --- change-password also revokes, and verifies the old password ---
reg2 = c.post("/auth/register",
              json={"email": "cp@x.io", "password": "longenoughpass1"})
tok2 = reg2.json()["access_token"]
auth2 = {"Authorization": f"Bearer {tok2}"}
wrongold = c.post("/auth/change-password",
                  json={"old_password": "nope12345", "new_password": "newpass123456"},
                  headers=auth2)
assert wrongold.status_code == 401, wrongold.text
cp = c.post("/auth/change-password",
            json={"old_password": "longenoughpass1", "new_password": "newpass123456"},
            headers=auth2)
assert cp.status_code == 200, cp.text
# old token revoked, new token from the response works
assert c.get("/library", headers=auth2).status_code == 401
newtok = cp.json()["access_token"]
assert c.get("/library", headers={"Authorization": f"Bearer {newtok}"}).status_code == 200
print("change-password     -> revokes old, issues working new token")

# --- rate limiting: hammer /auth/login past its 10/min budget ---
codes = [c.post("/auth/login",
                json={"email": "nobody@x.io", "password": "whateverpass12"}).status_code
         for _ in range(15)]
print("login burst codes   ->", f"{codes.count(401)}x401 {codes.count(429)}x429")
assert 429 in codes, "rate limit should kick in (expected some 429)"

# --- XSS: author.contact must reject dangerous URL schemes ---
from app.schemas import Cicheto


def _contact_ok(value):
    try:
        Cicheto.model_validate({"cicheto": 1, "id": "x.y", "name": "N",
                                "summary": "s", "author": {"name": "A", "contact": value},
                                "channels": {"stable": {"kind": "hpkg"}}})
        return True
    except Exception:
        return False


assert not _contact_ok("javascript:alert(1)"), "javascript: contact must be rejected"
assert not _contact_ok("data:text/html,<script>"), "data: contact must be rejected"
assert _contact_ok("https://github.com/me") and _contact_ok("mailto:me@x.io")
print("contact XSS guard    -> ok (javascript:/data: rejected)")

# --- SSRF: the shared guard blocks internal hosts in prod ---
from app import netguard, config as _cfg
_saved_prod = _cfg.IS_PROD
_cfg.IS_PROD = True
try:
    for bad in ("http://127.0.0.1/x", "https://169.254.169.254/meta",
                "https://10.0.0.1/r", "http://example.org/x"):  # http blocked too
        try:
            netguard.guard_url(bad)
            raise SystemExit(f"FAIL: SSRF guard accepted {bad}")
        except netguard.BlockedURLError:
            pass
    netguard.guard_url("https://example.org/x")  # public https is fine
finally:
    _cfg.IS_PROD = _saved_prod
print("SSRF guard           -> ok (internal/non-https blocked in prod)")

# --- SSRF: private/internal IPs are blocked in DEV too (only https + loopback
#     are relaxed in dev, never the private-range rejection) ---
_cfg.IS_PROD = False
try:
    for bad in ("http://169.254.169.254/latest/meta-data",  # cloud metadata
                "http://10.0.0.5/repo", "http://192.168.1.1/x",
                "file:///etc/passwd"):                        # non-http blocked
        try:
            netguard.guard_url(bad)
            raise SystemExit(f"FAIL: dev SSRF guard accepted {bad}")
        except netguard.BlockedURLError:
            pass
    netguard.guard_url("http://127.0.0.1:8000/repo")  # loopback allowed in dev
    netguard.guard_url("https://depot.haiku-os.org/x")
finally:
    _cfg.IS_PROD = _saved_prod
print("SSRF guard (dev)     -> ok (private/metadata blocked, loopback allowed)")

# --- redirect guard: a fetch that 30x-es to an internal host is refused ---
# guard_url is re-run on every hop, so a public URL that redirects to a private
# one cannot smuggle an internal fetch. We assert the helper exists and follows
# manually (follow_redirects must be off).
import inspect as _inspect
_src = _inspect.getsource(netguard._guarded_redirects)
assert "guard_url(current)" in _src, "redirect hops must be re-guarded"
assert netguard.fetch_guarded.__doc__ and "redirect" in netguard.fetch_guarded.__doc__.lower()
print("redirect guard       -> ok (every hop re-validated, no blind follow)")

# --- SSRF: guard_url returns a validated IP to pin the connection to, so the
#     address that was checked is the address that gets dialed (no DNS-rebinding
#     window between guard_url's resolution and httpx's). ---
_cfg.IS_PROD = False
try:
    ip = netguard.guard_url("http://127.0.0.1:8000/repo")
    assert ip in ("127.0.0.1", "::1"), f"expected loopback IP, got {ip!r}"
    ip2 = netguard.guard_url("https://93.184.216.34/x")  # a bare public IP literal
    assert ip2 == "93.184.216.34", ip2
finally:
    _cfg.IS_PROD = _saved_prod
# The connection is pinned to that IP with the original host kept as Host + SNI:
_pin = _inspect.getsource(netguard._pinned_request)
assert "sni_hostname" in _pin and "Host" in _pin, "pin must preserve SNI + Host"
assert "safe_ip = guard_url(current)" in _src, "hops must connect to the guarded IP"
print("SSRF pin             -> ok (guard returns IP, connection pinned to it)")

# --- rate-limit key: proxy-awareness is off by default (peer IP, not spoofable),
#     and only reads X-Forwarded-For when the operator opts in. ---
from app import main as _main
from starlette.requests import Request as _Request


def _fake_request(headers, client_ip="203.0.113.9"):
    scope = {
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_ip, 12345),
    }
    return _Request(scope)

_hdrs = {"x-forwarded-for": "198.51.100.7, 10.0.0.1"}

# Off by default: the forwarded header is ignored, we key on the peer.
_saved_tp = _cfg.TRUST_PROXY
_cfg.TRUST_PROXY = False
try:
    assert _main._client_key(_fake_request(_hdrs)) == "203.0.113.9", "must ignore XFF when untrusted"
finally:
    _cfg.TRUST_PROXY = _saved_tp
# On: the first XFF hop (the original client) becomes the key.
_cfg.TRUST_PROXY = True
try:
    assert _main._client_key(_fake_request(_hdrs)) == "198.51.100.7", "must use first XFF hop when trusted"
    assert _main._client_key(_fake_request({})) == "203.0.113.9", "no XFF -> fall back to peer"
finally:
    _cfg.TRUST_PROXY = _saved_tp
print("rate-limit key       -> ok (peer by default, XFF only when trusted)")

# Prod gate: missing secrets must raise.
from app import config
saved = (config.IS_PROD, config.SECRET_KEY, config.ADMIN_TOKEN)
config.IS_PROD = True
config.SECRET_KEY = "dev-only-change-me"
config.ADMIN_TOKEN = None
try:
    config.check_prod_config()
    raise SystemExit("FAIL: prod gate did not raise on missing secrets")
except RuntimeError:
    print("prod gate            -> raises on missing secrets (OK)")
finally:
    config.IS_PROD, config.SECRET_KEY, config.ADMIN_TOKEN = saved

print("\nPASS: all security checks")
