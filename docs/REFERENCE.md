# Reference

Detail that would clutter the README: the module layout, the endpoint map, and
the full environment table. The interactive API is always at `/docs`, and
`.env.example` at the repo root is the authoritative list of settings with their
defaults.

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

## Endpoints

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

## Environment

See `.env.example` for the full list with defaults. In `prod` the app refuses to
start if `SPRITZ_SECRET` or `SPRITZ_ADMIN_TOKEN` are missing or still the dev
default; in `dev` it starts with a warning.

| Variable | Default | Purpose |
|---|---|---|
| `SPRITZ_ENV` | `dev` | `dev` (convenient fallbacks, warnings only) or `prod` (gate active, HTTP→HTTPS + HSTS). |
| `SPRITZ_SECRET` | dev fallback | JWT signing key. Required in `prod`. |
| `SPRITZ_ADMIN_TOKEN` | unset | Admin token for `/ingest`, `/repo/build` (`X-Admin-Token`). Endpoints closed (503) if unset. Required in `prod`. |
| `SPRITZ_DB_URL` | `sqlite:///./spritz.db` | Database URL. Point to Postgres in prod (see `migrations/`). |
| `SPRITZ_PUBLIC_BASE_URL` | `http://localhost:8000` | Public URL announced in `repo.info`. Must be reachable by HaikuDepot. |
| `SPRITZ_CORS_ORIGINS` | localhost | Allowed CORS origins (CSV). Never `*`. |
| `SPRITZ_DEFAULT_RATE_LIMIT` | `120/minute` | Global default rate limit applied to routes. |
| `SPRITZ_BOOTSTRAP_ADMIN` | dev on, prod off | Auto-promote the first registered user to admin. Force with `1`/`0`. |
| `SPRITZ_PACKAGE_REPO_BIN` | unset | Path to Haiku's `package_repo` (see `docs/SETUP-WSL.md`). Without it the repo-proxy returns 503; the rest of the server still runs. |
| `SPRITZ_HVIF2PNG_BIN` | unset | Path to Haiku's `hvif2png` for icon extraction. Without it `/icon` returns 404 and the frontend uses a placeholder. |
| `SPRITZ_GITHUB_TOKEN` | unset | Optional GitHub token; raises the release-API rate limit from 60 to 5000/h. Recommended in `prod`. |
| `SPRITZ_REPO_CACHE` | `packages-cache` | Where the repo-proxy downloads hpkg and builds catalogs. Gitignored. |
| `SPRITZ_UPLOAD_DIR` | `packages-cache/assets` | Where uploaded icons/screenshots land. Gitignored. |
| `SPRITZ_MAX_CACHE_BYTES` | `2147483648` (2 GB) | Max total bytes for the cichéto cache before pruning. |
| `SPRITZ_MAX_HPKG_ICON_BYTES` | `104857600` (100 MB) | Above this size spritz won't download an hpkg just for its icon. |
| `SPRITZ_HDS_URL` | `https://depot.haiku-os.org` | HaikuDepotServer base URL, source of proxied/cached screenshots. |
| `SPRITZ_FEATURED_CICHETO` | `repo.haikuports.genio` | Featured cichéto id(s) on the home (CSV → carousel). Missing ids are skipped. |
| `SPRITZ_BROWSE_HIDDEN_BACARI` | `haikuports` | Bàcari hidden from the showcase (CSV). Still searchable and linkable. |
| `SPRITZ_BROWSE_HIDDEN_SUFFIXES` | `_devel,_debuginfo,_debug,_source,_sources,_doc,_docs,_dev` | Sub-package suffixes hidden from the showcase (CSV). Still searchable. |
