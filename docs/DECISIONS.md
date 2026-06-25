# Decisions

A running log of design decisions and their rationale, so contributors do not
re-litigate settled questions. Append new findings, especially the spike
results from task 01.

## Settled

**Additive to HaikuPorts, not a fork.** Both a design and a survival choice.
Dependencies resolve through the system solver against existing repos; the
`bridge` field links apps to their HaikuPorts package. Framing matters as much
as code: nothing user-facing may read as bypassing or replacing HaikuPorts.

**Two install layers, split imposed by the format.**
- stable hpkg -> repo-proxy, works in HaikuDepot as-is, no new client.
- ombra + zip + remote queue -> native client only.
A static HPKR repository cannot follow an author's latest release, so ombra
cannot live in the HaikuDepot-compatible repo. The split is structural, not a
preference.

**Repo-proxy, not mirror.** The Haiku repo format requires all packages under
one baseUrl, so spritz must serve the hpkg itself. It does so as an on-demand
proxy (fetch author URL, verify sha256, cache), keeping the author as the
source of truth rather than permanently re-hosting.

**cichéto holds tech only; trust tier and price live in the signed index.**
The cichéto is an editable file in a git repo, so putting tier or price in it
would let a fork self-promote. Those are assertions of the index, signed,
added later.

**git + cache.** Bàcari (git repos of cichéti) are the source of truth; the DB
is a rebuildable projection for fast search and resolve.

**Direct bcrypt, not passlib.** passlib's bcrypt backend errors against the
installed bcrypt here (72-byte detection bug). Using `bcrypt` directly removes
the broken layer. Do not reintroduce passlib.

**Checksums mandatory on locked channels, verified on download.** Already in
the schema and enforced by the proxy. Non-negotiable for stable; ombra verifies
at download time and logs the seen hash (acceptable only for nightlies).

**`/ingest` guarded by a shared admin token, not a User.is_admin flag.** Ingest
is an operator action, not an end-user one, so a single `SPRITZ_ADMIN_TOKEN`
(header `X-Admin-Token`, timing-safe compare) is enough and needs no schema
migration. If unset, the endpoint is closed (503), never anonymous. Revisit if
multiple distinct admins ever need separate, revocable credentials.

**Secrets are env-driven with a prod startup gate.** `app/config.py` reads
`SPRITZ_SECRET` and `SPRITZ_ADMIN_TOKEN`; `SPRITZ_ENV=prod` makes the app refuse
to start if either is missing or still the dev default. `dev` keeps a fallback
but warns. Dev fallback exists only so `seed.py` / `test_flow.py` run with no
setup; it must never reach production, which the gate enforces.

**Deferred from task 02 (not yet done):** rate limiting on `/auth/*` and
`/ingest`, HTTPS-only + HSTS, and ingest input validation (git URL scheme,
clone size/time caps). Tracked in `docs/tasks/02-security-hardening.md`; still
required before the repo goes public.

## Open (resolve and record here)

- **Does `package_repo` build for Linux/WSL?** Gates task 01. See SETUP-WSL.md.
- **Vendor-match requirement.** Does current `package_repo` require every
  hpkg's internal vendor to match the repo vendor? If yes, proxying many
  authors into one repo needs a workaround (sub-repos per vendor, or override).
- **HaikuDepot and duplicate packages across repos.** phoudoin was unsure
  whether HaikuDepot cleanly handles the same package/version in multiple
  repos. Relevant once spritz coexists with haiku/haikuports. Verify.
- **Identity scheme for cichéto `id`.** Reverse-domain (global, dedup-friendly)
  vs bàcaro/name (simple, explicit provenance). Currently reverse-domain.
  Revisit if two bàcari publish the same app.
