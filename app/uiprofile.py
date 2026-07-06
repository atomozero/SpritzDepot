"""Pick the UI profile (lite vs modern) for a request.

WebPositive is Haiku's stock browser: an older HaikuWebKit that lacks CSS grid,
custom properties, flex `gap`, fetch/Promise, etc. The whole frontend is written
lite-safe for it. But on a modern browser we can serve a richer look. This module
decides which profile a request gets, so a template can add a body class and the
CSS can layer modern styling as pure progressive enhancement.

Decision order:
  1. Explicit override: the `ui` cookie (set via /set-ui/<profile>). The user's
     choice always wins, for testing and preference.
  2. User-Agent: WebPositive (or any Haiku browser) -> lite.
  3. Default: modern. Most visitors are not on Haiku, and because the modern
     styling is layered enhancement, a Haiku browser that slips past detection
     still gets a fully usable (if plainer) page rather than a broken one.

Never raises: any problem falls back to the default profile.
"""
from __future__ import annotations

from starlette.requests import Request

LITE = "lite"
MODERN = "modern"
PROFILES = (LITE, MODERN)
DEFAULT = MODERN

# UA substrings that mean "serve the lite profile". WebPositive is the target;
# "Haiku" catches other Haiku-native browsers (and WebPositive builds whose name
# token we have not seen) so the OS that needs lite gets it even if the browser
# token changes. Matched case-insensitively.
_LITE_UA_MARKERS = ("webpositive", "haiku")


def normalize_profile(value: str | None) -> str | None:
    """Return a valid profile name, or None if the value is not one."""
    if value and value.lower() in PROFILES:
        return value.lower()
    return None


def is_lite_user_agent(user_agent: str | None) -> bool:
    """True if the User-Agent looks like a Haiku / WebPositive browser."""
    ua = (user_agent or "").lower()
    return any(marker in ua for marker in _LITE_UA_MARKERS)


def ui_profile(request: Request) -> str:
    """The UI profile for this request: 'lite' or 'modern'. Cookie override
    first, then User-Agent sniff, then the default."""
    try:
        override = normalize_profile(request.cookies.get("ui"))
        if override:
            return override
        if is_lite_user_agent(request.headers.get("user-agent")):
            return LITE
    except Exception:
        pass
    return DEFAULT
