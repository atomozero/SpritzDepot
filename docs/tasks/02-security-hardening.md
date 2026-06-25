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
- [ ] **Rate limiting.** At minimum on `/auth/login`, `/auth/register`, and
      `/ingest`. Use slowapi or equivalent. Prevents credential stuffing and
      ingest abuse.
- [ ] **HTTPS only** in production. Reject or redirect plain HTTP. Set secure
      headers (HSTS).
- [ ] **Input validation on ingest.** Validate the git URL scheme (https only,
      no file://, no ssh to arbitrary hosts), cap repo size and file count,
      time-limit the clone. A malicious bàcaro must not be able to hang or
      fill the disk.

## Should fix soon

- [ ] **Password policy.** Enforce a minimum length. bcrypt already truncates
      at 72 bytes (handled in `auth.py`), keep that.
- [ ] **Token lifetime + revocation.** One-week JWT with no revocation is
      coarse. Consider shorter access tokens plus a refresh mechanism, or a
      token version field on the user for invalidation.
- [ ] **Generic auth errors.** Login already returns a generic 401, keep it
      that way (do not leak whether the email exists).
- [ ] **CORS.** Lock the allowed origins to the known web frontend, not `*`.
- [ ] **Proxy SSRF guard** (overlaps with task 01). When the repo-proxy fetches
      an author URL, restrict to https public hosts, block internal/loopback
      addresses, cap response size, and always verify sha256.

## Verify

- Confirm `/ingest` returns 401/403 unauthenticated.
- Confirm the app refuses to start with no `SPRITZ_SECRET` set in prod mode.
- Confirm repeated bad logins get rate-limited.
- Confirm the proxy rejects a hash mismatch and a loopback URL.

Record anything deferred, with the reason, in `docs/DECISIONS.md`.
