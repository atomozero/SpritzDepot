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

**repo.info field names: `identifier` + `baseurl`, never `url` for the base.**
Verified against Haiku's parser (`RepositoryInfo.cpp` SetTo): the textual
repo.info keys are `name`, `identifier`, `baseurl`, `vendor`, `summary`,
`priority`, `architecture`. `url` is a *legacy alias for identifier*, not the
base URL, an easy and silent mistake (the first cut made it). `identifier` is
the stable repo identity HaikuDepot keys on, so spritz generates a UUID once per
sub-repo and persists it in `<sub-repo>/identifier`, reusing it across rebuilds.

**Repo-proxy is a verified mirror-on-build, not fetch-on-request.** The task 01
plan said "proxy the bytes on first request." In practice `package_repo` must
read every hpkg to compute its checksum and attributes when it builds the HPKR
catalog, so the bytes are already local at build time. We keep them and serve
from cache. sha256 is still verified at fetch and the author URL stays the
source of truth; this just means spritz holds a copy of each stable hpkg it
catalogs. Side benefit: a stable repo keeps working if an author URL goes down
between rebuilds. Implemented in `app/repo_proxy.py`.

**Token revocation via a per-user version, not a token blacklist or refresh
flow.** JWTs carry `ver` (the user's `token_version`); `current_user` rejects a
token whose `ver` is stale. Bumping `token_version` (logout-all, password
change) invalidates every outstanding token at once, with no server-side token
store. Access TTL cut to 2h. A full refresh-token flow is deferred: this covers
revocation, which was the actual requirement, at a fraction of the complexity.

**Security relaxations are dev-only and gated on `SPRITZ_ENV`.** Two checks are
strict in prod and relaxed in dev so tests and local work stay frictionless: the
ingest URL validator allows local/file bàcari only in dev, and the proxy SSRF
guard allows http + loopback only in dev. In prod both demand https and reject
internal addresses. The relaxation can never reach prod because it is keyed on
`IS_PROD`, the same flag the startup gate enforces.

**Rate-limit storage is in-memory for now.** slowapi with the default in-process
store is correct for a single worker. Before running multiple workers in prod,
point it at Redis (`storage_uri`), or limits are per-process and thus looser.
Recorded so it is not forgotten at deploy time.

**ombra resolves live at /resolve, follows GitHub releases, never builds.**
`app/ombra.py` resolves a `github-latest` channel against the author's newest
release (GitHub releases API, prerelease-aware), matching `.hpkg` assets per
arch by the cichéto `match` pattern. It returns asset URLs with NO sha256: the
schema and project line say the client verifies the hash at download and logs
it. The channel may name its repo explicitly (`repo: owner/name`) or have it
derived from a github.com `homepage`. Only releases that already ship a
ready-made `.hpkg` are followed; building from source stays out (build-farm,
later leg). `SPRITZ_GITHUB_TOKEN` raises the API rate limit. Both `/resolve` and
`/library/pending` resolve ombra live, so the daemon gets the real URLs in one
poll; a live-resolve failure leaves empty artifacts + a note (retry next poll),
never a hard failure of the whole poll.

**Image upload is a convenience, not a hosting model; the cichéto still uses
URLs.** Authors may upload an icon/screenshot (`POST /upload/image`) and spritz
serves it at `/assets/<sha256>.ext`, but the cichéto references images by URL
either way, so the git + cache model is untouched (an uploaded image's URL is
just one more URL in the YAML). This is a deliberate, bounded exception to "no
re-hosting": it covers authors with nowhere to host an image, while binaries
(hpkg) are still never re-hosted, only proxied with checksums. Uploads are
strict: image-only by magic bytes (not extension), size-capped (2MB/5MB),
content-addressed (safe paths, dedup), authenticated, rate-limited.

**Ingest prunes, and attributes by crawl slug not by self-declared packager.**
The DB is a projection of the bàcari, so a re-ingest removes cichéti that
vanished from that bàcaro (prune=True default), keeping the cache faithful.
Crucially, a row is attributed to the slug the crawl was run under, NOT to the
cichéto's own `packager.bacaro`: otherwise a malicious cichéto could claim
another tap's slug and get another tap's rows pruned or hijacked. `/bacari`
lists known taps with counts and last-ingest. `prune=False` is available for
batch/partial ingests.

**Admin page reuses the admin token; a Bacaro table records taps.** `/admin` is
served to anyone but inert without the token; every action posts the token as
`X-Admin-Token` and is verified server-side (same gate as `/ingest`). A small
`Bacaro` table (slug, git_url, last crawl outcome) is upserted on each ingest so
the page can list taps and re-crawl them without re-typing the URL. It is an
operational record, not a source of truth (the git repo still is). `init_db`
now imports models before create_all so new tables register regardless of
import order.

**Schema: create_all in dev, Alembic for persistent DBs.** `create_all` (run at
startup) adds missing *tables* but NOT *columns* to existing tables, so it is
fine for throwaway SQLite dev but not for an evolving prod DB. Alembic is now
set up (`alembic.ini`, `migrations/`) with an initial migration covering the
full schema; `SPRITZ_DB_URL` is shared by the app and Alembic (and lets prod
point at Postgres without code changes). Prod path: `alembic upgrade head` on a
clean DB, then incremental migrations per model change. Dev keeps using
create_all for convenience; the two do not conflict (create_all is idempotent).

**Bridge-only cichéti (`source: haikuports`) for apps already in HaikuPorts.**
An app already curated in HaikuPorts is catalogued without a competing spritz
download: its stable channel uses `source: haikuports` (no artifacts) plus a
`bridge`. `/resolve` returns empty artifacts, the bridge, and a note
(`pkgman install <pkg>`); the app page shows the HaikuPorts install command, not
the repo/get-spritz buttons. This makes the additive-to-HaikuPorts principle
concrete: spritz says "this exists, get the curated version there". The
sample-bàcaro ships 3DMov as the worked example.

**HPKR catalog reader for third-party repos, not HaikuPorts.** `app/hpkr.py` is
a pure-Python reader for a repository's `repo` (HPKR) catalog: it lists packages
and composes their download URL as `baseUrl + name-version-arch.hpkg`. Used by
the `hpkr-repo` channel so a cichéto can point at a third-party Haiku repository
(BeSly, an author's own server) that HaikuDepot does not show by default.
Deliberately NOT used for HaikuPorts apps (those use the bridge, no re-serving).
The parser was verified against a real HPKR built by Haiku's `package_repo`
(fixture tests/fixtures/sample.hpkr); getting it right meant matching three
binary details from the Haiku source: attribute integers are big-endian, the
string table ends with a 0-byte terminator, and the attribute type enum is
INT=1/UINT=2/STRING=3/RAW=4 (not 0-based). Heap none/zlib/zstd are all handled
via the shared `app/hpkg_heap.decompress_heap` (also used by hvif.py). No sha256
(client verifies, like ombra).

**App icons extracted from hpkg, rendered with hvif2png, on-demand + capped.**
Haiku icons are HVIF (a vector format) in a BEOS:ICON attribute inside the hpkg;
browsers can't render HVIF. `app/hvif.py` fetches the hpkg, decompresses its
heap (zstd or zlib), locates the 'ncif' HVIF blob, and renders it to PNG with
Haiku's host-built `hvif2png` (compiles in WSL, needs libpng-dev). `/icon/{id}`
does this on first request and caches the PNG; it refuses packages over
`SPRITZ_MAX_HPKG_ICON_BYTES` (default 20MB, so e.g. blender's 53MB is skipped)
and 404s when the tool is absent. The frontend tries `/icon/{id}` and falls
back to a generated initial-on-gradient placeholder on 404. Verified end to end
against a real package (minecraft_installer from the lote repo). zstd needed the
`zstandard` Python package; hpkg heaps use it, HPKR repo catalogs used zlib.

## Open (resolve and record here)

- **HaikuDepot and duplicate packages across repos.** phoudoin was unsure
- **HaikuDepot and duplicate packages across repos.** phoudoin was unsure
  whether HaikuDepot cleanly handles the same package/version in multiple
  repos. Relevant once spritz coexists with haiku/haikuports. Verify.
- **Identity scheme for cichéto `id`.** Reverse-domain (global, dedup-friendly)
  vs bàcaro/name (simple, explicit provenance). Currently reverse-domain.
  Revisit if two bàcari publish the same app.
