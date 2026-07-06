#!/usr/bin/env bash
#
# Start the spritz registry server.
#
#   ./run.sh                 # dev: auto-reload on http://localhost:8000
#   ./run.sh --prod          # prod: no reload, enforces the config gate
#   ./run.sh --port 9000     # override the port (default 8000)
#   ./run.sh --host 0.0.0.0  # bind address (default 127.0.0.1)
#   ./run.sh --crawl         # prefetch ombra snapshots before serving
#   ./run.sh --no-seed       # never seed, even on an empty catalog
#
# Environment (see README "Variabili d'ambiente"): SPRITZ_ENV, SPRITZ_SECRET,
# SPRITZ_ADMIN_TOKEN, SPRITZ_GITHUB_TOKEN, SPRITZ_DB_URL, ... are read as-is;
# this script never overwrites a value you already exported.
set -euo pipefail

cd "$(dirname "$0")"

# --- defaults ---
HOST="127.0.0.1"
PORT="8000"
PROD=0
CRAWL=0
SEED=1

while [ $# -gt 0 ]; do
  case "$1" in
    --prod)     PROD=1 ;;
    --crawl)    CRAWL=1 ;;
    --no-seed)  SEED=0 ;;
    --host)     HOST="${2:?--host needs a value}"; shift ;;
    --port)     PORT="${2:?--port needs a value}"; shift ;;
    -h|--help)
      sed -n '3,14p' "$0" | sed 's/^# \{0,1\}//;s/^#$//'
      exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

# --- pick the interpreter: prefer the project venv ---
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
  echo "warning: .venv not found, using system python3 (run: python3 -m venv .venv)" >&2
else
  echo "error: no python found (expected .venv/bin/python or python3)" >&2
  exit 1
fi

if ! "$PY" -c "import uvicorn" 2>/dev/null; then
  echo "error: uvicorn not installed. Run: $PY -m pip install -r requirements.txt" >&2
  exit 1
fi

# --- prod: SPRITZ_ENV=prod turns on the config gate (the app refuses to start
#     without a real SPRITZ_SECRET and SPRITZ_ADMIN_TOKEN). Fail early and clearly
#     here instead of on the first request. ---
if [ "$PROD" -eq 1 ]; then
  export SPRITZ_ENV="prod"
  missing=""
  [ -z "${SPRITZ_SECRET:-}" ]      && missing="$missing SPRITZ_SECRET"
  [ -z "${SPRITZ_ADMIN_TOKEN:-}" ] && missing="$missing SPRITZ_ADMIN_TOKEN"
  if [ -n "$missing" ]; then
    echo "error: prod mode needs these env vars set:$missing" >&2
    echo "       export them (or a .env you source) before ./run.sh --prod" >&2
    exit 1
  fi
  [ -z "${SPRITZ_GITHUB_TOKEN:-}" ] && \
    echo "note: SPRITZ_GITHUB_TOKEN not set; ombra resolves are rate-limited to 60/h" >&2
else
  export SPRITZ_ENV="${SPRITZ_ENV:-dev}"
fi

# --- seed the catalog only when it is empty, so we never clobber a real one.
#     init_db() creates/upgrades the schema; the seed adds the sample bacaro. ---
if [ "$SEED" -eq 1 ]; then
  count="$("$PY" - <<'PY'
from app.db import init_db, engine
from sqlmodel import Session, select
from app.models import CichetoRow
init_db()
with Session(engine) as s:
    print(len(s.exec(select(CichetoRow.id)).all()))
PY
)"
  if [ "$count" = "0" ]; then
    echo "catalog empty -> seeding from sample-bacaro/"
    "$PY" seed.py
  else
    echo "catalog has $count apps -> not seeding"
  fi
fi

# --- optional: prefetch ombra snapshots so the first ombra request is fast ---
if [ "$CRAWL" -eq 1 ]; then
  echo "prefetching ombra snapshots..."
  "$PY" crawl_ombra.py || echo "warning: ombra crawl failed (server starts anyway)" >&2
fi

# --- serve. Reload in dev (watches the source); off in prod. ---
echo "starting spritz on http://$HOST:$PORT  (env=$SPRITZ_ENV)  docs: /docs"
if [ "$PROD" -eq 1 ]; then
  exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT"
else
  exec "$PY" -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
fi
