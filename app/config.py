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

# Whether the first user to register is auto-promoted to admin. Convenient in
# dev, dangerous on a public prod deploy (a stranger who registers first would
# own the admin routes), so it defaults ON in dev and OFF in prod. Force with
# SPRITZ_BOOTSTRAP_ADMIN=1 / 0.
_bootstrap_env = os.environ.get("SPRITZ_BOOTSTRAP_ADMIN")
if _bootstrap_env is not None:
    BOOTSTRAP_ADMIN = _bootstrap_env.strip().lower() in ("1", "true", "yes", "on")
else:
    BOOTSTRAP_ADMIN = ENV != "prod"

# Whether the app sits behind a trusted reverse proxy that sets X-Forwarded-For
# and X-Forwarded-Proto. When on, the rate limiter keys on the client IP from
# X-Forwarded-For (else every request looks like it comes from the proxy and all
# clients share one bucket, so one abuser throttles everyone). Leave OFF unless
# the app is ONLY reachable through that proxy: a directly-reachable app with
# this on lets a client spoof its rate-limit key (and its forwarded scheme) with
# a header. Defaults OFF.
_trust_proxy_env = os.environ.get("SPRITZ_TRUST_PROXY")
TRUST_PROXY = (_trust_proxy_env or "").strip().lower() in ("1", "true", "yes", "on")

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
# A Haiku package puts its HVIF icon in the package attributes near the start, so
# we never need the whole hpkg to extract it. 100 MB was excessive (a single icon
# request could pull tens of MB); 25 MB comfortably covers real apps while cutting
# the bandwidth/time an attacker can force per /icon call. Raise if a legit app is
# ever truncated.
MAX_HPKG_FETCH_FOR_ICON = int(
    os.environ.get("SPRITZ_MAX_HPKG_ICON_BYTES", str(25 * 1024 * 1024)))  # 25 MB

# Total-size cap for the on-disk media cache (extracted icons + proxied
# screenshots under UPLOAD_DIR). Without a bound, enumerating icon/screenshot ids
# could fill the disk until writes (and SQLite) fail. When a write would exceed
# this, the least-recently-used cached files are evicted first.
MAX_CACHE_BYTES = int(
    os.environ.get("SPRITZ_MAX_CACHE_BYTES", str(2 * 1024 * 1024 * 1024)))  # 2 GB

# Bàcari that are "everything HaikuDepot already shows" (a mirror of HaikuPorts).
# They stay in the catalog and are fully searchable, but the browse/home view
# hides them so the shop-window highlights the third-party sources that are
# spritz's actual value (the apps HaikuDepot does NOT show). Comma-separated
# slugs. A blank search + no filters excludes these; a query or an explicit
# category/bàcaro filter includes them.
BROWSE_HIDDEN_BACARI = [
    b.strip() for b in os.environ.get("SPRITZ_BROWSE_HIDDEN_BACARI", "haikuports")
    .split(",") if b.strip()
]

# The cichéto id(s) highlighted in the home hero ("featured apps"). A CSV list:
# each id that exists in the catalog becomes a card in the featured carousel, in
# the given order; absent ids are skipped. A single id still works (one card).
# FEATURED_CICHETO keeps the first id for any old single-value call site;
# FEATURED_CICHETI is the parsed list. Override with SPRITZ_FEATURED_CICHETO.
_DEFAULT_FEATURED = ("org.haiku.genio,com.atomozero.localsend,"
                     "com.atomozero.sestriere,com.atomozero.teslaviewer")
FEATURED_CICHETI = [s.strip() for s in os.environ.get(
    "SPRITZ_FEATURED_CICHETO", _DEFAULT_FEATURED).split(",") if s.strip()]
FEATURED_CICHETO = FEATURED_CICHETI[0] if FEATURED_CICHETI else None

# Sub-package name suffixes that are build artifacts, not apps: -devel headers,
# -debuginfo symbols, -source trees, -doc/-docs, and -source_debuginfo. The
# browse/home view hides cichéti whose id or name ends in one of these (they
# stay fully searchable and reachable by direct link), so the shop-window shows
# real apps, not the _devel/_debuginfo noise a repo import pulls in.
# Comma-separated, matched case-insensitively against the id and the name.
BROWSE_HIDDEN_SUFFIXES = [
    s.strip().lower() for s in os.environ.get(
        "SPRITZ_BROWSE_HIDDEN_SUFFIXES",
        "_devel,_debuginfo,_debug,_source,_sources,_doc,_docs,_dev",
    ).split(",") if s.strip()
]


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
