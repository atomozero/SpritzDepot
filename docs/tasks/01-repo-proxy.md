# Task 01: repo-proxy layer (HaikuDepot-compatible)

**Why this is priority one:** it makes "add one URL in HaikuDepot, works
as-is, no new client" true. Lowest adoption cost of anything in the project.
This was the design phoudoin pushed toward in the forum thread, and Andrea
committed to it publicly.

## The constraint that shapes everything

Haiku's repo format does NOT support per-package arbitrary URLs. A repository
is a fixed structure under one `baseUrl`:

```
<baseUrl>/repo.info        # text: name, vendor, summary, priority, identifier (uuid), architecture, url
<baseUrl>/repo             # HPKR binary catalog of all packages
<baseUrl>/packages/<name>-<version>-<arch>.hpkg
```

HaikuDepot reads `repo.info` and the HPKR catalog, then fetches packages from
the `packages/` directory under the same baseUrl. GitHub release assets at
arbitrary hosts cannot be referenced directly.

This is now confirmed by authoritative sources, not just inferred: phoudoin
(HaikuPorts contributor and haiku-os.org moderator) stated it plainly in the
forum thread ("all packages exposed by the catalog of an HPKG repository are to
be accessible from the base repository URL + the package file name"), and
clasqm confirmed it from his own repo-hosting experience. The on-demand proxy
behavior phoudoin describes (serve base_url + filename, fetch from the external
URL behind the scenes, verify checksum, cache) is exactly the approach below.
Official format reference:
https://www.haiku-os.org/docs/develop/packages/Infrastructure.html

**Therefore spritz must serve the hpkg under its own baseUrl.** Do it as an
**on-demand proxy**, not a permanent mirror: on first request for a package,
fetch from the author URL in the cichéto, verify sha256, cache to disk, serve.
Source of truth stays with the author; we only proxy the bytes because the
format requires a single baseUrl. This preserves the "always point to the
author" principle.

## Spike: DONE (both unknowns resolved)

Full procedure and the result are in `docs/SETUP-WSL.md` step 2 and
`docs/DECISIONS.md`. Summary:

1. **Does `package_repo` build for Linux/WSL?** YES. `./configure --host-only`
   then `jam -q '<build>package_repo'` builds it on Debian 12 / WSL2 (one
   trivial source fix: add `#include <cstddef>` to `RPattern.cpp` for gcc 12).
   Verified end to end: built a test hpkg, ran `package_repo create` to produce
   the HPKR catalog, listed it back. **No Haiku VM needed for the build step.**

2. **Vendor-match: ENFORCED, no override.** `package_repo create` aborts the
   whole repo (`B_BAD_DATA`) if any package's vendor differs from the repo's
   vendor (`RepositoryWriterImpl.cpp:404-411`). So a single flat repo cannot
   hold many third-party authors. **Decision: per-vendor sub-repos** (option a):
   each vendor gets its own baseUrl + repo.info + HPKR, internally uniform. The
   override option (rewriting the author's vendor field) is rejected: it mutates
   the author's bytes and breaks any signature, against the project principle.

## Implementation: FIRST CUT DONE

Implemented in `app/repo_proxy.py` + routes in `app/main.py`, verified end to
end offline by `test_repo_proxy.py` (builds a real hpkg, serves it over HTTP,
drives build + the three serving routes, checks the served bytes match the
verified hpkg). What works now:

- `POST /repo/build` (admin): groups stable hpkg by the vendor read from each
  hpkg's own `.PackageInfo` (not the cichéto, which has no vendor), per arch;
  fetches each with sha256 verification; runs `package_repo create` per group.
- `GET /repo/{vendor}/{arch}/current/{repo.info,repo,packages/<file>}` serve the
  generated catalog and the staged hpkg (canonical name-version-arch.hpkg).
- Degrades to 503 when `package_repo` is not configured; rest of the server runs.

**Refinement vs the original "pure proxy" plan:** packages are fetched and kept
locally at build time, because `package_repo` must read every hpkg to compute
its checksum and attributes for the catalog. So it is effectively a
verified mirror-on-build, not a fetch-on-each-request proxy. The author URL
stays the source of truth and sha256 is enforced on fetch; we just cannot avoid
holding the bytes once the catalog references them. Acceptable, and more robust
(survives the author URL going down between rebuilds).

**Still TODO before calling task 01 complete:**

- **Persist a stable repo `identifier` UUID** per sub-repo (must stay constant
  across rebuilds/mirrors). Not yet emitted in `repo.info`.
- **Validate on a real Haiku machine/VM:** add the URL in HaikuDepot or
  `pkgman add-repo`, confirm it lists and installs. Done off-Haiku so far.
- **Auto-rebuild trigger** on ingest changes (currently manual via /repo/build).
- **Tamper test** as an automated case (sha256 mismatch path is coded but the
  test asserts only the happy path + traversal guard).

Scope: **stable channel, kind hpkg, sha256 present.** Nothing else goes in the
HaikuDepot-compatible repo (ombra is impossible here by nature, zip is not hpkg).

- **Group by (vendor, architecture), not just architecture** (forced by the
  vendor-match result). Each (vendor, arch) pair is one sub-repo with its own
  baseUrl. A user adds one URL per vendor they want, the same way HaikuPorts and
  BeSly are separate repos.
- Generate `repo.info` per sub-repo: stable `identifier` UUID (persist it, it
  must stay constant across rebuilds and mirrors), correct `architecture`, the
  vendor, and the spritz baseUrl for that sub-repo as `url`.
- Build the HPKR catalog with `package_repo create` over the set of stable hpkg
  for that (vendor, arch).
- Serve the baseUrl layout, one sub-repo per (vendor, arch). Suggested routes
  (FastAPI):
  - `GET /repo/{vendor}/{arch}/current/repo.info`
  - `GET /repo/{vendor}/{arch}/current/repo`
  - `GET /repo/{vendor}/{arch}/current/packages/{filename}` -> proxy+verify+cache
- Proxy endpoint: map filename back to its cichéto/artifact, fetch the author
  URL, verify sha256 against the cichéto, cache under a local packages dir,
  stream to the client. On hash mismatch: refuse and log loudly.
- Rebuild trigger: regenerate repo.info + HPKR whenever ingest changes the
  stable set. Keep it idempotent.

## Test

- Build a repo for `x86_64` from the sample bàcaro (extend the sample with a
  real small hpkg if needed for a true end-to-end).
- Validate the repo with a Haiku machine/VM: add the URL in HaikuDepot or
  `pkgman add-repo`, confirm the package lists and installs.
- Confirm sha256 verification rejects a tampered artifact.

## Out of scope here

ombra channel, zip/non-packaged sources, the remote browser queue. Those are
native-client territory and stay out of the HaikuDepot-compatible repo.

Note on ombra (raised by phoudoin): "follow the author's latest release"
splits in two. When the author publishes a ready-made .hpkg per release (e.g. a
GitHub release asset), spritz only has to track the new asset URL + checksum,
which is in reach. When the latest release is *source* that must be compiled
and packaged, that needs detect-change + auto-rebuild + auto-version
infrastructure, i.e. a build farm (what Haiku's and HaikuPorts' buildbots do).
The native client targets the first case; the build-farm case is explicitly a
later, separate leg (the future "services" leg: donations, paid apps, hpkg
build farm). Do not let ombra scope-creep into building packages here.
