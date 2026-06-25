"""Central runtime configuration and the startup security gate.

Two secrets matter for security:
  - SPRITZ_SECRET      signs the JWTs (auth.py)
  - SPRITZ_ADMIN_TOKEN authorizes /ingest (main.py)

The environment is selected by SPRITZ_ENV:
  - "dev"  (default): convenient fallbacks, but never silently insecure.
                      A missing admin token leaves /ingest closed (403),
                      not open. A warning is logged for the JWT fallback.
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
