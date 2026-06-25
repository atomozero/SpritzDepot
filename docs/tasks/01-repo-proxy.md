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

**Therefore spritz must serve the hpkg under its own baseUrl.** Do it as an
**on-demand proxy**, not a permanent mirror: on first request for a package,
fetch from the author URL in the cichéto, verify sha256, cache to disk, serve.
Source of truth stays with the author; we only proxy the bytes because the
format requires a single baseUrl. This preserves the "always point to the
author" principle.

## Spike first (do these before writing the server side)

Two load-bearing unknowns. Resolve and record both in `docs/DECISIONS.md`
before building:

1. **Does `package_repo` build for Linux/WSL?** See `docs/SETUP-WSL.md` step 2.
   We need it to generate the HPKR catalog off-Haiku. If it does not build
   standalone, decide the fallback (Haiku VM in the loop vs from-scratch HPKR
   writer, strongly prefer the VM).

2. **Does the vendor-match requirement block heterogeneous author hpkg?**
   Older docs state every hpkg's internal `.PackageInfo` vendor must match the
   repo's vendor or the repo will not build. If `package_repo` still enforces
   uniform vendor, proxying many third-party authors' packages into one repo
   breaks. Verify against current `package_repo`. If it is enforced, options:
   one sub-repo per author/vendor, or a controlled override. Decide and record.

Do not skip the spike. If either answer is bad, the whole layer changes shape.

## Implementation (only after the spike passes)

Scope: **stable channel, kind hpkg, sha256 present.** Nothing else goes in the
HaikuDepot-compatible repo (ombra is impossible here by nature, zip is not hpkg).

- One repo per architecture (`x86_64`, `x86_gcc2h`, ...). Group cichéti by the
  arches present in their stable channel.
- Generate `repo.info` per arch: stable `identifier` UUID (persist it, it must
  stay constant across rebuilds and mirrors), correct `architecture`, the
  spritz baseUrl as `url`.
- Build the HPKR catalog with `package_repo` (or the VM fallback) over the set
  of stable hpkg for that arch.
- Serve the baseUrl layout. Suggested routes (FastAPI):
  - `GET /repo/{arch}/current/repo.info`
  - `GET /repo/{arch}/current/repo`
  - `GET /repo/{arch}/current/packages/{filename}` -> proxy + verify + cache
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
