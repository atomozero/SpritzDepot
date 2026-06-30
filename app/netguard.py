"""SSRF guard for outbound fetches of URLs that come from cichéti / admin input.

spritz downloads author-supplied URLs (hpkg artifacts, icons) and admin-supplied
repo URLs. Without a guard, a malicious cichéto or a compromised admin could make
the server fetch internal services (cloud metadata at 169.254.169.254, localhost
admin panels, private-range hosts). This blocks that.

Policy: in prod, https only and the resolved address must be a public unicast
IP (reject private / loopback / link-local / multicast / reserved /
unspecified). In dev it is relaxed so tests can fetch from 127.0.0.1.

Shared by repo_proxy, hvif, and hpkr so every outbound fetch is guarded the
same way.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from . import config


class BlockedURLError(RuntimeError):
    """The URL is refused before any network request is made."""


def guard_url(url: str) -> None:
    """Raise BlockedURLError if `url` must not be fetched. No-op (beyond a host
    check) in dev; strict in prod."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname

    if not host:
        raise BlockedURLError(f"refusing to fetch URL with no host: {url}")
    if not config.IS_PROD:
        return  # dev/test: allow http + loopback

    if scheme != "https":
        raise BlockedURLError(f"refusing non-https URL in prod: {url}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BlockedURLError(f"cannot resolve host {host}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            raise BlockedURLError(
                f"refusing to fetch internal address {ip} ({host})")
