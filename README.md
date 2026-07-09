# spritz registry (v0.1)

[![tests](https://github.com/atomozero/SpritzDepot/actions/workflows/tests.yml/badge.svg)](https://github.com/atomozero/SpritzDepot/actions/workflows/tests.yml)

A federated catalog and installer for Haiku OS software. It covers what
HaikuDepot does not: the latest release of an app, straight from its author
(GitHub releases, BeSly, Fat Elk, third-party Haiku repos, old archives).

spritz is **additive to HaikuPorts, never a rival or a fork**: dependencies are
resolved by the system solver against the repos already present, and every app
can declare a `bridge` to its curated HaikuPorts package. Think AUR to the
official Arch repos, the nursery, not the competitor.

This repo is the **registry server** (FastAPI): discovery plus the two install
paths. The install queue and native `spritz://` handler live in a separate
Haiku-side daemon (not in this repo).

## Core concepts

- **cichéto**: an app manifest, a small YAML file. Schema in `app/schemas.py`.
- **bàcaro**: a tap, a git repo of cichéti. Git is the source of truth; the DB
  is a rebuildable projection.
- **channels**: `stable` (pinned + sha256) and `ombra` (follows the author's
  latest GitHub release).
- **bridge**: links an app to its HaikuPorts package.

## Two install paths

- **stable → repo-proxy.** A standard Haiku repository (`repo.info` + HPKR
  catalog) built with `package_repo`, served under `/repo/{vendor}/{arch}/...`.
  The user adds one URL in HaikuDepot, no new client needed. One sub-repo per
  vendor (a `package_repo` constraint, see `docs/DECISIONS.md`).
- **ombra + third-party hpkr + browser queue → native client.** A static HPKR
  repo cannot follow an author's latest release, so `ombra` resolves it live
  and the native daemon consumes the browser install queue.

## Running

```bash
pip install -r requirements.txt
python seed.py                 # seed the cache from the local sample bàcaro
uvicorn app.main:app --reload  # then open http://localhost:8000/docs
```

Copy `.env.example` to `.env` to override defaults (in `dev` all have working
fallbacks). Contributing? See [CONTRIBUTING.md](CONTRIBUTING.md).

Tests live in `tests/` as runnable scripts. Run the whole suite under pytest
(each script runs isolated in its own subprocess, on a throwaway DB); this is
what CI runs:

```bash
pip install -r requirements-dev.txt
pytest -q
```

Or run a single script directly, as a module from the repo root (in-process,
no network unless noted):

```bash
python -m tests.test_flow       # end-to-end catalog + library flow
python -m tests.test_security   # auth, rate-limit, validation, prod gate
python -m tests.test_frontend   # page rendering
SPRITZ_PACKAGE_REPO_BIN=... python -m tests.test_repo_proxy  # repo-proxy (needs package_repo)
```

## Configuration

Set via environment variables. In `prod` the app **refuses to start** if
`SPRITZ_SECRET` or `SPRITZ_ADMIN_TOKEN` are missing or still the dev default;
in `dev` it starts with a warning.

| Variable | Default | Purpose |
|---|---|---|
| `SPRITZ_ENV` | `dev` | `dev` (convenient fallbacks, warnings only) or `prod` (gate active, HTTP→HTTPS + HSTS). |
| `SPRITZ_SECRET` | dev fallback | JWT signing key. Required in `prod`. |
| `SPRITZ_ADMIN_TOKEN` | unset | Admin token for `/ingest`, `/repo/build` (`X-Admin-Token`). Endpoints closed (503) if unset. Required in `prod`. |
| `SPRITZ_DB_URL` | `sqlite:///./spritz.db` | Database URL. Point to Postgres in prod (see `migrations/`). |
| `SPRITZ_PUBLIC_BASE_URL` | `http://localhost:8000` | Public URL announced in `repo.info`. Must be reachable by HaikuDepot. |
| `SPRITZ_CORS_ORIGINS` | localhost | Allowed CORS origins (CSV). Never `*`. |
| `SPRITZ_PACKAGE_REPO_BIN` | unset | Path to Haiku's `package_repo` (see `docs/SETUP-WSL.md`). Without it the repo-proxy returns 503; the rest of the server still runs. |
| `SPRITZ_HVIF2PNG_BIN` | unset | Path to Haiku's `hvif2png` for icon extraction. Without it `/icon` returns 404 and the frontend uses a placeholder. |
| `SPRITZ_GITHUB_TOKEN` | unset | Optional GitHub token; raises the release-API rate limit from 60 to 5000/h. Recommended in `prod`. |
| `SPRITZ_REPO_CACHE` | `packages-cache` | Where the repo-proxy downloads hpkg and builds catalogs. Gitignored. |
| `SPRITZ_UPLOAD_DIR` | `packages-cache/assets` | Where uploaded icons/screenshots land. Gitignored. |
| `SPRITZ_MAX_HPKG_ICON_BYTES` | `104857600` | Above this size spritz won't download an hpkg just for its icon. |
| `SPRITZ_HDS_URL` | `https://depot.haiku-os.org` | HaikuDepotServer base URL, source of proxied/cached screenshots. |
| `SPRITZ_FEATURED_CICHETO` | `repo.haikuports.genio` | Featured cichéto id(s) on the home (CSV → carousel). Missing ids are skipped. |
| `SPRITZ_BROWSE_HIDDEN_BACARI` | `haikuports` | Bàcari hidden from the showcase (CSV). Still searchable and linkable. |
| `SPRITZ_BROWSE_HIDDEN_SUFFIXES` | `_devel,_debuginfo,_debug,_source,_sources,_doc,_docs,_dev` | Sub-package suffixes hidden from the showcase (CSV). Still searchable. |

## Layout

```
app/
  schemas.py     cichéto format (Pydantic validation)
  models.py      DB tables (cichéto cache, users, library queue)
  db.py          engine/session (SQLite dev, Postgres prod)
  config.py      env + prod security gate
  auth.py        bcrypt + JWT (direct bcrypt, not passlib)
  ingest.py      crawl a bàcaro (git or dir) → cache
  ombra.py       ombra resolver (author's latest GitHub release)
  hpkr.py        HPKR catalog reader (third-party Haiku repos)
  hvif.py        HVIF icon extraction → PNG (via hvif2png)
  hpkg_heap.py   shared heap decompression (none/zlib/zstd)
  repo_proxy.py  HaikuDepot-compatible layer (fetch+verify, HPKR, serve)
  main.py        FastAPI routes (API + frontend)
  templates/     Jinja pages
  static/        frontend CSS + JS
sample-bacaro/   sample cichéto (Genio)
tests/           runnable test scripts + test_scripts.py (pytest wrapper) + fixtures/
```

## Key endpoints

Full interactive docs at `/docs`. Highlights:

| Method | Path | For |
|---|---|---|
| GET  | `/search?q=&category=&bacaro=&limit=&offset=` | catalog (filters + pagination) |
| GET  | `/cicheto/{id}` | app page |
| GET  | `/resolve/{id}?channel=&arch=` | Haiku daemon (url + sha256 + requires) |
| GET  | `/icon/{id}` | app icon extracted from the hpkg (PNG, cached) |
| POST | `/auth/register` · `/auth/login` | account (rate-limited) |
| POST | `/library/{id}` · `/library/{id}/installed` | queue install / daemon confirm |
| GET  | `/library/pending` | daemon polls |
| POST | `/ingest` | crawl a bàcaro + auto-rebuild repo (admin) |
| POST | `/repo/build` · `/repo/import-hpkr` | rebuild sub-repos / import third-party repo (admin) |
| GET  | `/repo/{vendor}/{arch}/current/{repo.info,repo,packages/{file}}` | HaikuDepot |

## Next steps (not in v1)

1. **Haiku daemon** consuming `/library/pending` (closes the Play Store loop).
2. **Trust tiers, manifest signing, transparency log** (signed index
   assertions, deliberately outside the editable cichéto).
3. **Commercial layer** (`spritz offri`, paid apps via a Merchant of Record).

To verify on real Haiku (not WSL): frontend rendering in WebPositive, the native
client probe and `spritz://` scheme, and adding the repo-proxy in HaikuDepot.

## Security notes

- **`/ingest` and repo-admin routes are admin-only** (`X-Admin-Token`), closed
  when the token is unset. In `prod` the app refuses to start without a real
  secret and admin token.
- **Auth**: min 12-char passwords, short-lived JWTs (2h) with server-side
  revocation via `token_version` (logout, logout-all, password change, account
  deletion). Generic 401 on login (does not reveal whether an email exists, and
  pays a bcrypt on the unknown-email path to stay timing-indistinguishable).
- **Ingest**: git URL validated (https; local only in dev), clone with timeout
  and caps on size and file count.
- **Repo-proxy**: SSRF guard on author URLs (prod: https only, no internal
  hosts), download size caps, sha256 always verified.
- `sha256` is mandatory on pinned channels. `github-latest` channels do not
  pre-compute the hash; the daemon verifies it at download and logs what it saw.
- Trust tier and price are **not** in the cichéto (an editable git file): they
  belong to the signed index, so a fork cannot self-promote.

## Privacy

Data controller: **Andrea Bernardi** (andrea@studiobernardi.eu).

spritz collects the minimum: email and password (bcrypt hash) for login, plus
your library list. No tracking cookies, no profiling; download stats are
anonymous (no user id, no IP) and the IP is used in memory by the rate-limiter
only, never stored. Legal basis is service performance (GDPR art. 6.1.b); data
is kept while the account is active. Users exercise their rights in-app:
`/privacy` shows the notice, `/account` exports data as JSON (arts. 15, 20) or
deletes the account and library (art. 17).

## Third-party components

- **haikon_full.js** (`app/static/`): client-side HVIF → SVG parser/renderer by
  3dEyes (Gerasim Troeglazov), from https://hvif-store.art (see also
  https://github.com/threedeyes/hvif-tools). MIT licensed. spritz uses it to
  draw app icons as SVG in the browser (via `/hvif/{id}`), without depending on
  the native `hvif2png`. Server-side PNG rendering stays as an alternative.

## License

spritz is released under the **MIT** license (see [LICENSE](LICENSE)).
Copyright (c) 2026 Andrea Bernardi. Includes third-party code under its own MIT
license (see "Third-party components" above).
