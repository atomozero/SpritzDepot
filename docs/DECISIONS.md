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

**HPKG repos are single-baseUrl; the proxy must serve bytes, not link out.**
Confirmed authoritatively in the forum thread by phoudoin (HaikuPorts
contributor, haiku-os.org moderator) and by clasqm from repo-hosting
experience: HaikuDepot fetches every package as `baseUrl + filename`, so
arbitrary per-package URLs (GitHub release assets) cannot be referenced
directly. spritz therefore serves stable hpkg under its own baseUrl as an
on-demand proxy (fetch from author URL, verify sha256, cache), never a
permanent mirror. This was already the task 01 design; it is now fact, not
assumption. Ref: https://www.haiku-os.org/docs/develop/packages/Infrastructure.html

**ombra never builds packages here.** Following an author's latest release is
in scope only when the author ships a ready-made .hpkg per release (track the
new asset URL + checksum). Latest-release-as-source requires auto-build /
auto-version infrastructure (a build farm), which is a separate, later leg, not
part of the repo-proxy or the first native client.

**`package_repo` builds and runs on Linux/WSL. Spike done.** (Debian 12 / WSL2,
gcc 12.) Steps that worked, recorded in SETUP-WSL.md: build Haiku's `jam` from
`buildtools/jam`; `git clone --depth 1` the `haiku` tree; `./configure
--host-only` (no cross-tools, no OS image); `jam -q '<build>package_repo'` (and
`'<build>package'`). One source fix was needed: `src/kits/storage/sniffer/
RPattern.cpp` is missing `#include <cstddef>` for `offsetof`, fatal under gcc
12. Verified end to end: built a test .hpkg with `package`, ran `package_repo
create` to produce the HPKR catalog (it computes the package checksum itself),
and `package_repo list` reads it back. So the HaikuDepot-compatible catalog can
be generated entirely off-Haiku; no VM needed for the build step.

**Vendor-match IS enforced, with no override. This shapes the repo layout.**
`package_repo create` rejects any package whose `.PackageInfo` vendor differs
(case-insensitive) from the repository's `vendor`, aborting the whole repo with
`B_BAD_DATA`. Verified live ("package 'x' has unexpected vendor ... (expected
...)") and in source: `src/kits/package/hpkg/RepositoryWriterImpl.cpp:404-411`,
comment "all packages must have the same vendor as the repository". There is no
CLI flag to disable it. Consequence: spritz CANNOT pour many third-party
authors' hpkg into one flat repo. Options to decide in task 01: (a) one sub-repo
per vendor (baseUrl per vendor, many repo.info/HPKR, each internally uniform),
or (b) normalize/override the vendor field in a controlled rebuild step (changes
the author's bytes, fights the "point back to the author" principle and breaks
any author signature). Leaning (a). Record the final choice when implementing.

## Open (resolve and record here)

- **HaikuDepot and duplicate packages across repos.** phoudoin was unsure
- **HaikuDepot and duplicate packages across repos.** phoudoin was unsure
  whether HaikuDepot cleanly handles the same package/version in multiple
  repos. Relevant once spritz coexists with haiku/haikuports. Verify.
- **Identity scheme for cichéto `id`.** Reverse-domain (global, dedup-friendly)
  vs bàcaro/name (simple, explicit provenance). Currently reverse-domain.
  Revisit if two bàcari publish the same app.
