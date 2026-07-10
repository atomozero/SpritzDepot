"""SSRF guard for outbound fetches of URLs that come from cichéti / admin input.

spritz downloads author-supplied URLs (hpkg artifacts, icons) and admin-supplied
repo URLs. Without a guard, a malicious cichéto or a compromised admin could make
the server fetch internal services (cloud metadata at 169.254.169.254, localhost
admin panels, private-range hosts). This blocks that.

Policy:
  - The private/internal-address rejection is ALWAYS on, in dev and prod. Even a
    dev instance must never be trickable into hitting 169.254.169.254 or an
    internal host; there is no legitimate reason to relax that. What dev relaxes
    is ONLY the https-scheme requirement (tests and local repos use http on
    loopback), and it explicitly allows loopback so the test suite can fetch from
    127.0.0.1.
  - In prod: https only, and loopback is rejected too.

Redirects are the other half of the guard: guard_url only validates the URL you
hand it, but an HTTP 30x can point Location: at an internal host that was never
checked. So callers must NOT use httpx's follow_redirects=True on untrusted URLs;
they use fetch_guarded / stream_guarded here, which follow redirects manually and
re-run guard_url on every hop.

Shared by repo_proxy, hvif, hpkr, hds and main so every outbound fetch is guarded
the same way.
"""
from __future__ import annotations

import contextlib
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

from . import config

MAX_REDIRECTS = 5


class BlockedURLError(RuntimeError):
    """The URL is refused before any network request is made."""


def _ip_forbidden(ip: ipaddress._BaseAddress) -> bool:
    """Whether an address is off-limits. Loopback is allowed in dev only (the
    test suite hits 127.0.0.1); everything private/internal is always refused."""
    if ip.is_loopback and not config.IS_PROD:
        return False
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def guard_url(url: str) -> str:
    """Validate `url` and return a safe IP literal to connect to.

    Always rejects hosts that resolve to a private/loopback/link-local/multicast/
    reserved/unspecified address. In prod additionally requires https and rejects
    loopback; in dev http and loopback are allowed (for tests / local repos).

    Returns one resolved, validated IP. Callers connect to THAT IP (with the host
    preserved as Host header + TLS SNI) so the address that was checked is the
    address that is dialed. Without this, guard_url resolves the name but httpx
    resolves it again on connect, and an attacker controlling DNS could answer
    the two lookups differently (DNS rebinding) to reach an internal service.
    Raises BlockedURLError if the URL or every resolved address is refused."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname

    if not host:
        raise BlockedURLError(f"refusing to fetch URL with no host: {url}")

    if config.IS_PROD and scheme != "https":
        raise BlockedURLError(f"refusing non-https URL in prod: {url}")
    if scheme not in ("http", "https"):
        raise BlockedURLError(f"refusing non-http(s) URL: {url}")

    # A bare IP literal in the URL is validated directly (no name to resolve).
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _ip_forbidden(literal):
            raise BlockedURLError(f"refusing to fetch internal address {literal}")
        return str(literal)

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BlockedURLError(f"cannot resolve host {host}: {e}") from e

    safe_ip = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _ip_forbidden(ip):
            # If ANY resolved address is internal, refuse the whole host: a
            # mixed answer (one public, one internal) is exactly the rebinding
            # trick, so we do not just pick a good one.
            raise BlockedURLError(
                f"refusing to fetch internal address {ip} ({host})")
        if safe_ip is None:
            safe_ip = str(ip)

    if safe_ip is None:
        raise BlockedURLError(f"cannot resolve host {host}")
    return safe_ip


def _pinned_request(client: httpx.Client, method: str, url: str,
                    safe_ip: str, **kwargs) -> httpx.Request:
    """Build a request that connects to `safe_ip` (the address guard_url just
    validated) while keeping the original host for routing, the Host header, and
    TLS SNI. This closes the DNS-rebinding gap: httpx dials the exact IP we
    checked instead of resolving the name a second time."""
    original = httpx.URL(url)
    host = original.host
    # Point the connection at the validated IP; preserve the host everywhere it
    # matters so virtual-hosting and certificate validation still work.
    dial_url = original.copy_with(host=safe_ip)
    headers = kwargs.pop("headers", None) or {}
    headers = dict(headers)
    headers.setdefault("Host", original.netloc.decode("ascii"))
    extensions = dict(kwargs.pop("extensions", None) or {})
    extensions.setdefault("sni_hostname", host)
    return client.build_request(method, dial_url, headers=headers,
                                extensions=extensions, **kwargs)


def _guarded_redirects(client: httpx.Client, method: str, url: str,
                       stream: bool, **kwargs):
    """Issue the request, following redirects MANUALLY and re-running guard_url on
    every Location. Returns the final (already-read for non-stream) response, or a
    context-managed streaming response. Raises BlockedURLError if any hop is bad."""
    hops = 0
    current = url
    while True:
        safe_ip = guard_url(current)
        req = _pinned_request(client, method, current, safe_ip, **kwargs)
        resp = client.send(req, stream=stream)
        if resp.is_redirect and hops < MAX_REDIRECTS:
            location = resp.headers.get("location")
            resp.close()
            if not location:
                raise BlockedURLError(f"redirect with no Location from {current}")
            # resolve relative redirects against the current URL
            current = str(httpx.URL(current).join(location))
            hops += 1
            continue
        if resp.is_redirect:
            resp.close()
            raise BlockedURLError(f"too many redirects starting at {url}")
        return resp


def fetch_guarded(method: str, url: str, *, timeout: float = 30.0,
                  **kwargs) -> httpx.Response:
    """A buffered GET/POST that guards the initial URL and every redirect hop.
    Never uses httpx's automatic redirect-following. Caller reads .content."""
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        resp = _guarded_redirects(client, method, url, stream=False, **kwargs)
        resp.read()
        return resp


@contextlib.contextmanager
def stream_guarded(method: str, url: str, *, timeout: float = 60.0, **kwargs):
    """Streaming variant of fetch_guarded: guards every hop, then yields the final
    streaming response. Use for large/capped downloads (icons, artifacts)."""
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        resp = _guarded_redirects(client, method, url, stream=True, **kwargs)
        try:
            yield resp
        finally:
            resp.close()
