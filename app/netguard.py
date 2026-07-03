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


def guard_url(url: str) -> None:
    """Raise BlockedURLError if `url` must not be fetched.

    Always rejects hosts that resolve to a private/loopback/link-local/multicast/
    reserved/unspecified address. In prod additionally requires https and rejects
    loopback; in dev http and loopback are allowed (for tests / local repos)."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname

    if not host:
        raise BlockedURLError(f"refusing to fetch URL with no host: {url}")

    if config.IS_PROD and scheme != "https":
        raise BlockedURLError(f"refusing non-https URL in prod: {url}")
    if scheme not in ("http", "https"):
        raise BlockedURLError(f"refusing non-http(s) URL: {url}")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BlockedURLError(f"cannot resolve host {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # loopback is allowed in dev only (the test suite hits 127.0.0.1).
        loopback_ok = ip.is_loopback and not config.IS_PROD
        if loopback_ok:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise BlockedURLError(
                f"refusing to fetch internal address {ip} ({host})")


def _guarded_redirects(client: httpx.Client, method: str, url: str,
                       stream: bool, **kwargs):
    """Issue the request, following redirects MANUALLY and re-running guard_url on
    every Location. Returns the final (already-read for non-stream) response, or a
    context-managed streaming response. Raises BlockedURLError if any hop is bad."""
    hops = 0
    current = url
    while True:
        guard_url(current)
        req = client.build_request(method, current, **kwargs)
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
