"""Central runtime configuration and the startup security gate.

Two secrets matter for security:
  - SPRITZ_SECRET      signs the JWTs (auth.py)
  - SPRITZ_ADMIN_TOKEN authorizes /ingest (main.py)

The environment is selected by SPRITZ_ENV:
  - "dev"  (default): convenient fallbacks, but never silently insecure.
                      A missing admin token leaves /ingest closed (503 when the
                      token is unset, 401 on a wrong token), not open. A warning
                      is logged for the JWT fallback.
  - "prod"          : both secrets are required. check_prod_config() is
                      called at startup and raises if either is missing or
                      still set to a development default, so the process
                      refuses to run in an insecure state.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("spritz.config")

ENV = os.environ.get("SPRITZ_ENV", "dev").lower()
IS_PROD = ENV == "prod"

# A sentinel default we must never accept in production.
_DEV_SECRET = "dev-only-change-me"

SECRET_KEY = os.environ.get("SPRITZ_SECRET", _DEV_SECRET)

# No development default: if the admin token is unset, /ingest stays closed
# rather than falling back to a guessable value.
ADMIN_TOKEN = os.environ.get("SPRITZ_ADMIN_TOKEN")

# Path to Haiku's host-built `package_repo` tool (see docs/SETUP-WSL.md step 2).
# If unset or not found, the repo-proxy layer reports 503 instead of crashing,
# so the rest of the server runs fine without it.
PACKAGE_REPO_BIN = os.environ.get("SPRITZ_PACKAGE_REPO_BIN")

# Where the proxy caches downloaded hpkg and generated catalogs. Keep it out of
# the source tree; gitignored.
REPO_CACHE_DIR = os.environ.get("SPRITZ_REPO_CACHE", "packages-cache")

# Public base URL the generated repo.info advertises (the `url` field). The repo
# must be reachable here for HaikuDepot to fetch packages.
PUBLIC_BASE_URL = os.environ.get("SPRITZ_PUBLIC_BASE_URL", "http://localhost:8000")

# Allowed CORS origins for the web frontend, comma-separated. Locked, never "*"
# in prod (credentials + wildcard is unsafe and disallowed by browsers anyway).
# Default: the dev frontend on localhost.
CORS_ORIGINS = [
    o.strip() for o in os.environ.get(
        "SPRITZ_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000"
    ).split(",") if o.strip()
]

# Uploaded images (icons, screenshots). A convenience: authors may upload here
# instead of hosting the image themselves, but the cichéto still references it
# by URL (served from spritz), so git stays the source of truth. Strict caps.
UPLOAD_DIR = os.environ.get("SPRITZ_UPLOAD_DIR",
                            os.path.join(REPO_CACHE_DIR, "assets"))
MAX_ICON_BYTES = 2 * 1024 * 1024        # 2 MB
MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024  # 5 MB

# Icon extraction from hpkg (Haiku HVIF icon -> PNG). hvif2png is a host-built
# Haiku tool (see docs/SETUP-WSL.md); without it, icon extraction is skipped and
# the frontend shows the generated placeholder. We refuse to download an hpkg
# larger than this just to pull an icon out of it.
HVIF2PNG_BIN = os.environ.get("SPRITZ_HVIF2PNG_BIN")
MAX_HPKG_FETCH_FOR_ICON = int(
    os.environ.get("SPRITZ_MAX_HPKG_ICON_BYTES", str(100 * 1024 * 1024)))  # 100 MB


def check_prod_config() -> None:
    """Fail fast in production if security-critical secrets are missing.

    Called from the app startup hook. In dev it only warns; in prod it
    raises RuntimeError so the process will not serve traffic insecurely.
    """
    problems: list[str] = []

    if not SECRET_KEY or SECRET_KEY == _DEV_SECRET:
        problems.append(
            "SPRITZ_SECRET is unset or still the development default; "
            "set it to a strong random value."
        )
    if not ADMIN_TOKEN:
        problems.append(
            "SPRITZ_ADMIN_TOKEN is unset; /ingest would be unreachable. "
            "Set it to a strong random value."
        )

    if not problems:
        return

    if IS_PROD:
        raise RuntimeError(
            "Refusing to start in prod with insecure config:\n  - "
            + "\n  - ".join(problems)
        )

    for p in problems:
        log.warning("dev mode: %s", p)
