# Contributing to spritz

Thanks for helping. spritz is the registry server for a federated Haiku
software catalog. This file is the short version; the README covers what the
project is and how to run it.

## Setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python seed.py                 # seed the cache from the local sample bàcaro
uvicorn app.main:app --reload  # http://localhost:8000/docs
```

Copy `.env.example` to `.env` if you want to override defaults. In `dev`
everything has a working fallback, so you can start with none.

## Tests

CI runs the whole suite under pytest; do the same before opening a PR:

```bash
pytest -q
```

Each `tests/test_*.py` is a standalone script run in its own subprocess (see
`tests/test_scripts.py`). To run one directly:

```bash
python -m tests.test_flow
```

Add coverage for behavior you change. New tests follow the existing
script style (module-level asserts) and are picked up automatically.

## Conventions

- **Python**: type hints, small modules, FastAPI dependency injection.
- **Language**: English for code, comments, and dev docs (keeps the repo
  contributor-ready). Italian only for user-facing strings (web UI, forum
  posts, announcements).
- **Auth**: use `bcrypt` directly, as in `app/auth.py`. Do **not** reintroduce
  `passlib` (it breaks in this environment).
- **DB**: SQLite in dev, but keep everything Postgres-compatible (SQLModel
  handles both). Never write to the real `spritz.db` from a test; the tests set
  a throwaway `SPRITZ_DB_URL`.
- **Prose**: no em dashes; use commas, colons, or parentheses.

## The one framing rule (applies to all user-facing copy)

spritz is **additive to HaikuPorts, never a rival or a fork**. Dependencies are
resolved by the system solver against the repos already present, and every app
can declare a `bridge` to its HaikuPorts package. Think AUR to the official
Arch repos: the nursery, not the competitor. Please keep any human-readable
text (UI strings, docs, commit messages) on this line.

## Pull requests

- Keep changes focused; describe what and why.
- Make sure `pytest -q` is green.
- Update the README or `docs/` when you change behavior they describe.
