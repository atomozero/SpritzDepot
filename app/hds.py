"""HaikuDepotServer screenshot client.

HaikuDepot screenshots are NOT inside the hpkg (unlike the HVIF icon we extract);
they are uploaded by maintainers and hosted on HaikuDepotServer. spritz stays
additive: it does not re-host or claim them, it points at what already exists.

API, verified live against depot.haiku-os.org:
  - list:     POST {BASE}/__api/v2/pkg/get-pkg-screenshots  {"pkgName": "<name>"}
              -> {"result": {"items": [{"code", "width", "height", "length"}, ...]}}
  - download: GET  {BASE}/__pkgscreenshot/{code}.png?tw=<W>&th=<H>
              (tw/th are REQUIRED; without them the server returns HTTP 400)

Everything here is best-effort: any failure (network, HDS down, package unknown)
returns an empty list / None so the caller degrades to "no screenshots" instead
of erroring the page.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from . import netguard

# Overridable so tests can point at a fake and so a self-hosted mirror is possible.
BASE_URL = os.environ.get("SPRITZ_HDS_URL", "https://depot.haiku-os.org").rstrip("/")

# Default render box for the proxied image (keeps aspect ratio within it).
DEFAULT_W = 800
DEFAULT_H = 600


class HdsError(RuntimeError):
    """A HaikuDepotServer request that could not be completed."""


def list_screenshots(pkg_name: str,
                     client: Optional[httpx.Client] = None) -> list[dict]:
    """Screenshot descriptors for a package: [{code, width, height}]. Empty list
    on any problem (never raises), so callers can just use what they get."""
    if not pkg_name:
        return []
    url = f"{BASE_URL}/__api/v2/pkg/get-pkg-screenshots"
    try:
        netguard.guard_url(url)
    except netguard.BlockedURLError:
        return []
    own = client or httpx.Client(timeout=6.0, follow_redirects=True)
    try:
        r = own.post(url, json={"pkgName": pkg_name})
        if r.status_code != 200:
            return []
        body = r.json()
        if body.get("error"):
            return []
        items = ((body.get("result") or {}).get("items")) or []
        out = []
        for it in items:
            code = it.get("code")
            if code:
                out.append({"code": code,
                            "width": it.get("width"),
                            "height": it.get("height")})
        return out
    except Exception:
        # Any failure (network, bad JSON, unexpected shape) degrades to "no
        # screenshots"; this must never break the page that calls it.
        return []
    finally:
        if client is None:
            own.close()


def get_description(pkg_name: str, lang: str = "en",
                    repository_source: str = "haikuports_x86_64",
                    client: Optional[httpx.Client] = None) -> Optional[dict]:
    """The curated, localized summary + description for a package from HDS, or
    None if unavailable. Returns {'summary': str|None, 'description': str|None}.

    Uses get-pkg with versionType ALL (the only value that returns the versions
    array carrying the texts, verified live) and reads the newest version's
    summary/description. Best-effort: any failure returns None so the caller
    keeps whatever it already had."""
    if not pkg_name:
        return None
    url = f"{BASE_URL}/__api/v2/pkg/get-pkg"
    try:
        netguard.guard_url(url)
    except netguard.BlockedURLError:
        return None
    own = client or httpx.Client(timeout=6.0, follow_redirects=True)
    try:
        r = own.post(url, json={"name": pkg_name,
                                "repositorySource": repository_source,
                                "versionType": "ALL",
                                "naturalLanguageCode": lang})
        if r.status_code != 200:
            return None
        body = r.json()
        if body.get("error"):
            return None
        versions = ((body.get("result") or {}).get("versions")) or []
        if not versions:
            return None
        v = versions[0]        # API returns newest first
        summary = (v.get("summary") or "").strip() or None
        description = (v.get("description") or "").strip() or None
        if not summary and not description:
            return None
        return {"summary": summary, "description": description}
    except Exception:
        return None
    finally:
        if client is None:
            own.close()


def screenshot_bytes(code: str, w: int = DEFAULT_W, h: int = DEFAULT_H,
                     client: Optional[httpx.Client] = None) -> Optional[bytes]:
    """Download one screenshot PNG (tw/th are required by HDS). Returns the bytes
    or None on any failure."""
    if not code:
        return None
    url = f"{BASE_URL}/__pkgscreenshot/{code}.png"
    try:
        netguard.guard_url(url)
    except netguard.BlockedURLError:
        return None
    own = client or httpx.Client(timeout=15.0, follow_redirects=True)
    try:
        r = own.get(url, params={"tw": w, "th": h})
        if r.status_code != 200:
            return None
        data = r.content
        # Sanity: must be a PNG, not an error page.
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return data
    except Exception:
        return None
    finally:
        if client is None:
            own.close()
