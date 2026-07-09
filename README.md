# spritz

[![tests](https://github.com/atomozero/SpritzDepot/actions/workflows/tests.yml/badge.svg)](https://github.com/atomozero/SpritzDepot/actions/workflows/tests.yml)

A federated catalog and installer for Haiku OS software. It covers what HaikuDepot does not: the latest release of an app, straight from its author. Out of the box a fresh Haiku machine only enables the `haiku` and `haikuports` repos, so everything else (apps in GitHub releases, BeSly, Fat Elk, old BeOS archives) is invisible unless you already know the URL. BeBits filled this gap on BeOS and was never rebuilt. spritz is that rebuild: one searchable index of sources that already exist, always pointing back to the original author instead of re-hosting binaries.

This repo is the **registry server** (FastAPI): discovery plus the two install paths. The native `spritz://` handler and install queue live in a separate Haiku-side daemon.

If spritz saves you time, consider supporting development: [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-atomozero-yellow?logo=buymeacoffee)](https://buymeacoffee.com/atomozero)

> [!NOTE]
> spritz is additive to HaikuPorts, never a rival or a fork. Dependencies are resolved by the system solver against the repos already present, and every app can declare a `bridge` to its HaikuPorts package. Think AUR to the official Arch repos: the nursery, not the competitor.

## Features

* Federated taps (bàcari): anyone publishes a git repo of app manifests in minutes
* Manifests are small YAML files (cichéti), no build recipe, no re-hosted binaries
* Two release channels per app: `stable` (pinned + sha256) and `ombra` (follows the author's latest GitHub release)
* A `bridge` field links an app to its curated HaikuPorts package
* repo-proxy layer: serve stable apps as a standard Haiku repository, added with one URL in HaikuDepot, no new client needed
* Reads third-party HPKR repos (BeSly, Fat Elk, an author's own server), the gap HaikuDepot does not cover
* Public catalog with search, categories, and per-tap browsing
* Server-rendered web frontend (Italian), lightweight enough for WebPositive
* App icons extracted from the hpkg, rendered as SVG in the browser or PNG server-side
* Email + password accounts, install queue, and a Play-Store-style library the Haiku daemon polls
* Publish page: authors fill a form and get a cichéto YAML for their own git tap

## Quick start

```
pip install -r requirements.txt
python seed.py                 # seed the cache from the local sample bàcaro
uvicorn app.main:app --reload  # then open http://localhost:8000/docs
```

Copy `.env.example` to `.env` to override defaults. In dev everything has a working fallback, so you can start with none. The two settings that matter in production are `SPRITZ_SECRET` (JWT signing key) and `SPRITZ_ADMIN_TOKEN` (guards `/ingest`); with `SPRITZ_ENV=prod` the app refuses to start on the dev defaults.

## Tests

CI runs the whole suite under pytest; do the same before a PR:

```
pip install -r requirements-dev.txt
pytest -q
```

Each `tests/test_*.py` is a standalone script run in its own subprocess. To run one directly:

```
python -m tests.test_flow
```

## How it works

The install path splits in two, and the split is imposed by the Haiku repo format, not chosen:

- **stable → repo-proxy.** A standard Haiku repository (`repo.info` + HPKR catalog) built with `package_repo`, served under `/repo/{vendor}/{arch}/...`. The user adds one URL in HaikuDepot; the system solver does the rest.
- **ombra + third-party hpkr + browser queue → native client.** A static HPKR repo cannot follow an author's latest release, so `ombra` resolves it live and the native daemon consumes the browser install queue.

Git is the source of truth: taps are git repos, and the DB is a rebuildable projection of them. The full API is at `/docs`; the module layout, endpoint map, and settings table are in [docs/REFERENCE.md](docs/REFERENCE.md).

> [!CAUTION]
> This is a young registry. The security hardening is in place (admin-gated ingest, prod secret gate, rate limiting, SSRF guards, see `docs/tasks/02-security-hardening.md`), but it has not been through an external security review yet. Run your own instance at your own risk, and do not expose it to the public internet without one.

## Contributing

Contributions are welcome, see [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and conventions. The one rule for any human-readable text: keep spritz additive to HaikuPorts, never framed as bypassing or replacing it.

## Privacy

Data controller: **Andrea Bernardi** (andrea@studiobernardi.eu). spritz collects the minimum: email and password (bcrypt hash) for login, plus your library list. No tracking cookies, no profiling; download stats are anonymous and the IP is used in memory by the rate-limiter only, never stored. Users export or delete their data in-app (`/account`), and `/privacy` shows the full notice.

## License

spritz is released under the **MIT** license (see [LICENSE](LICENSE)). Copyright (c) 2026 Andrea Bernardi. It bundles **haikon_full.js** by 3dEyes (Gerasim Troeglazov, https://hvif-store.art), also MIT, to draw HVIF app icons as SVG in the browser.

---

If spritz is useful to you: [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-atomozero-yellow?logo=buymeacoffee)](https://buymeacoffee.com/atomozero)
