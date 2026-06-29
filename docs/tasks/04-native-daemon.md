# Task 04: native Haiku client / daemon (spec)

The Haiku-side leg. It cannot be built or tested in WSL (needs BeAPI and
packagefs), so this file is the contract the registry already serves, written
down so the daemon can be built against it without guessing. The registry side
of every endpoint here exists and is tested; the daemon is what consumes them.

## What the daemon is for

Three jobs the repo-proxy layer cannot do (a static HPKR repo is not enough):

1. Handle `spritz://` URLs from the browser (one-click install).
2. Follow the `ombra` channel (the author's latest release) and the non-hpkg
   sources, which HaikuDepot cannot.
3. Poll the user's remote install queue and install what lands there (the
   "Play Store" effect: queue from any browser, the machine installs).

Stable hpkg does NOT need the daemon: that is the repo-proxy layer, added as a
URL in HaikuDepot. Keep the line clean (see DECISIONS, the two-layer split).

## Contracts the registry already exposes

All JSON. Auth is a JWT bearer (`Authorization: Bearer <token>`) for the
per-user endpoints; the token comes from `/auth/login`. Base URL is the spritz
server.

### Resolve (what to download)

`GET /resolve/{id}?channel=<ch>&arch=<arch>` -> install info:

```json
{
  "id": "org.haiku.genio",
  "channel": "stable",
  "kind": "hpkg",
  "version": "3.2",
  "artifacts": { "x86_64": { "url": "...", "sha256": "..." } },
  "requires": ["lib:libgit2", "cmd:git"],
  "bridge": { "haikuports": "genio", "prefer": "stable" },
  "notes": ["..."]
}
```

- `stable`: `artifacts` carry `url` + `sha256`. The daemon MUST verify sha256.
- `ombra` (`source: github-latest`): the registry resolves the latest GitHub
  release live; `artifacts` carry `url` only, NO sha256. The daemon verifies the
  hash at download and logs the hash it saw (acceptable for nightlies only).
- `bridge.prefer == "stable"`: the app is also on HaikuPorts. The daemon should
  surface that and prefer the curated package when the user has not asked
  specifically for ombra.

### Install queue (the Play Store loop)

Per-user, bearer auth:

- `GET /library/pending` -> list of items the daemon should install:
  ```json
  [{ "cicheto": "org.haiku.genio", "channel": "stable", "arch": "x86_64",
     "kind": "hpkg", "artifacts": {...}, "requires": [...] }]
  ```
  IMPORTANT: for an `ombra` item this returns the cichéto's *static* artifacts
  (empty for github-latest), it does NOT resolve live. So for `channel == "ombra"`
  the daemon must call `/resolve/{id}?channel=ombra&arch=<arch>` to get the real
  URLs. For `stable` the artifacts here are already usable. (A future registry
  change could resolve ombra inside pending too; until then, resolve client-side.)
- `POST /library/{id}/installed` -> mark an item installed once it landed.
- `POST /library/{id}` (channel, arch in body) -> the web queues installs; the
  daemon does not call this, the browser does.

### Dependency resolution

`requires` is an advisory pre-flight hint only. The real dependencies live
inside the hpkg and are resolved by the system solver against the repos already
present (haiku, haikuports, and any added spritz repo-proxy URL). The daemon
installs the hpkg and lets packagefs + the solver do the rest. spritz does not
re-implement dependency solving (see the non-negotiable framing).

## The two interfaces the daemon must expose

### 1. `spritz://` URL handler

Registered so WebPositive (and others) can hand off deep links:

- `spritz://install/<id>?channel=<ch>` -> resolve, confirm with the user,
  install. `<id>` is the reverse-domain cichéto id; `<ch>` defaults to stable.

The web app builds exactly this link (`app/static/install-button.js`).

### 2. Local detection endpoint (for the degrading button)

The web page probes the daemon to decide whether to show the one-click button:

- `GET http://127.0.0.1:4242/ping` -> any `2xx` means "client present".

4242 is the current placeholder the frontend uses; if the daemon binds a
different port, update `PROBE_URL` in `app/static/install-button.js` to match.
Beware mixed content: an HTTPS page calling `http://127.0.0.1` is blocked by
some browsers; document what WebPositive actually allows. Keep the endpoint
trivial (a ping, no sensitive data, no auth needed for a pure liveness check).

## Install flow (end to end)

1. Browser: user clicks install -> `spritz://install/org.haiku.genio?channel=stable`.
2. Daemon: `GET /resolve/org.haiku.genio?channel=stable&arch=<this machine>`.
3. Daemon: download each artifact; verify sha256 (stable) or verify-and-log
   (ombra); refuse on mismatch.
4. Daemon: install via packagefs; the system solver pulls dependencies.
5. If the install came from the remote queue: `POST /library/{id}/installed`.

## Out of scope for the first daemon

Building packages from source (build-farm, a later leg), paid apps / donations
(the services leg), and the zip/non-packaged "cask" case beyond a basic unpack.
Start with: `spritz://` handler, the ping endpoint, resolve + verified install,
and the pending-queue poll.

## Verify (on a Haiku machine, see docs/tasks/05 checklist)

- `spritz://install/...` from WebPositive triggers the daemon and installs.
- A stable install verifies sha256 and refuses a tampered file.
- An ombra install resolves the latest release and verifies-and-logs the hash.
- Queue an install from the browser, confirm the daemon polls and installs it,
  and that `/library` then shows it as installed.
