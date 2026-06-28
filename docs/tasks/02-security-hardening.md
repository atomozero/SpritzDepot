# Task 02: security hardening (gate before public repo)

Andrea committed in the forum to running security tests before making the
repo public. This is that checklist. Treat it as a release gate, not a
nice-to-have.

## Must fix before public

- [x] **Protect `/ingest`.** Done. Admin-only via `SPRITZ_ADMIN_TOKEN`
      (header `X-Admin-Token`), timing-safe compare. If the token is unset the
      endpoint is closed (503), never anonymous. See `require_admin` in
      `app/main.py`.
- [x] **SECRET_KEY.** Done. `SPRITZ_SECRET` comes from the environment via
      `app/config.py`. In `prod` mode (`SPRITZ_ENV=prod`) the app refuses to
      start if `SPRITZ_SECRET` or `SPRITZ_ADMIN_TOKEN` is missing or still the
      dev default; in `dev` it warns. Verified by `test_security.py`.
- [x] **Rate limiting.** Done with slowapi (keyed by client IP): `/auth/login`
      10/min, `/auth/register` 5/min, `/auth/change-password` 5/min, `/ingest`
      10/min. 429 on exceed. In-memory store; point at Redis in prod for
      multi-process correctness.
- [x] **HTTPS only** in production. `HTTPSRedirectAndHSTS` middleware redirects
      plain HTTP to HTTPS (honoring `X-Forwarded-Proto`) and sets HSTS, in prod
      only (dev http://localhost still works).
- [x] **Input validation on ingest.** `ingest.py` validates the git URL scheme
      (https always; local/file only in dev, never in prod; ssh/git/ftp
      rejected), times out the clone (60s), and caps repo size (50 MB) and file
      count (5000).

## Should fix soon

- [x] **Password policy.** Minimum length 8 (`MIN_PASSWORD_LENGTH`), enforced at
      register and change-password via Pydantic (422 on violation). bcrypt's
      72-byte truncation kept.
- [x] **Token lifetime + revocation.** Access token TTL cut to 2h. Revocation
      via a per-user `token_version` carried in the JWT; `/auth/logout-all` and
      `/auth/change-password` bump it, invalidating all outstanding tokens.
- [x] **Generic auth errors.** Login returns a generic 401 regardless of whether
      the email exists. Kept and commented.
- [x] **CORS.** Locked to `SPRITZ_CORS_ORIGINS` (default localhost dev frontend),
      never `*`.
- [x] **Proxy SSRF guard.** `repo_proxy._guard_fetch_url`: in prod, https only
      and reject private/loopback/link-local/reserved resolved addresses; caps
      the download (500 MB) and always verifies sha256. Relaxed in dev (tests
      fetch from 127.0.0.1).

## Verify

All covered by `test_security.py` (and the proxy paths by `test_repo_proxy.py`):

- `/ingest` returns 401 unauthenticated, 400 on an ssh:// URL.
- The app refuses to start with no `SPRITZ_SECRET` in prod mode.
- Repeated bad logins get rate-limited (429 after the budget).
- Short passwords are rejected (422); logout-all / change-password revoke tokens.
- The proxy rejects a sha256 mismatch (loopback rejection is prod-only, so it is
  exercised by code review of `_guard_fetch_url`, not the dev-mode test).

Anything deferred is recorded in `docs/DECISIONS.md`.
