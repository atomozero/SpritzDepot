# Prompt for the Haiku-side Claude (native client + store_server daemon)

Copy everything below the line into a fresh Claude session running on the Haiku
machine. It is self-contained: that instance has no access to the registry repo,
so every contract it needs is spelled out here.

---

You are building the **Haiku-native client** for **spritz**, a federated catalog
and installer for Haiku software. The web/registry side already exists and runs
(FastAPI, Python); your job is the Haiku-side leg in **C++ with the BeAPI**. You
cannot see the registry's source, so this prompt gives you every contract you
need. Do not invent endpoints or formats beyond what is written here; if a Haiku
API or the hpkg/packagefs behaviour is uncertain, say so and verify against the
Haiku headers, do not guess.

## What spritz is (framing — keep this in any user-facing text)

spritz is the rebuild of BeBits: a single searchable index of Haiku software
that points back to the original authors instead of re-hosting binaries. It is
**additive to HaikuPorts, never a rival or a fork**. Dependencies are resolved
by the system solver against the repos already present; spritz is a layer on
top. When an app also exists in HaikuPorts, the manifest declares a `bridge` and
the user is pointed to the curated version there. Do not write anything that
frames spritz as bypassing or replacing HaikuPorts.

## What you are building (two parts, one program is fine)

1. A **`spritz://` URL handler** so WebPositive (and others) can hand off deep
   links from the catalog website.
2. A **daemon (`store_server`)** that:
   - exposes a tiny local HTTP endpoint so the website can detect it is running,
   - polls the user's remote install queue and installs what lands there
     (the "Play Store" effect: the user queues an app from any browser, this
     daemon installs it),
   - resolves and installs apps via packagefs, letting the system solver pull
     dependencies.

Stable hpkg do NOT need this daemon (those are added as a normal repo URL in
HaikuDepot). You handle the rest: the `ombra` channel (an author's latest
release), `hpkr-repo` third-party packages, and the remote-queue install.

## The two local interfaces you must expose

### a) `spritz://` URL handler
Register the app to handle the `spritz` URL scheme. The one URL the website
produces is:
```
spritz://install/<id>?channel=<ch>
```
`<id>` is a reverse-domain cichéto id (e.g. `org.haiku.genio` or
`repo.lote.qupzilla`). `<ch>` defaults to `stable`. On receiving it: resolve,
confirm with the user, install.

### b) Liveness endpoint (so the website shows a one-click button)
The website probes the daemon to decide whether to offer the deep link:
```
GET http://127.0.0.1:4242/ping   ->  any 2xx means "client present"
```
Bind `127.0.0.1:4242`. Keep it trivial: a liveness ping, no sensitive data, no
auth needed. (If you must use a different port, that is fine, but 4242 is what
the website currently probes; note the change so the web side can be updated.)
Beware mixed content: an https web page calling http://127.0.0.1 is blocked by
some browsers — document what WebPositive actually allows.

## The registry HTTP API you consume

All JSON. Base URL is the spritz server (configurable; in dev
`http://localhost:8000`). The per-user endpoints need a JWT bearer:
`Authorization: Bearer <token>`, where the token comes from `POST /auth/login`
with `{"email":..., "password":...}` returning `{"access_token": "...",
"token_type": "bearer"}`. Tokens are short-lived (~2h); on a 401, re-login.

### Resolve what to download
```
GET /resolve/{id}?channel=<ch>&arch=<arch>
```
Returns:
```json
{
  "id": "org.haiku.genio",
  "channel": "stable",
  "kind": "hpkg",
  "version": "3.2",
  "source": null,
  "artifacts": { "x86_64": { "url": "https://...", "sha256": "..." } },
  "requires": ["lib:libgit2", "cmd:git"],
  "bridge": { "haikuports": "genio", "prefer": "stable" },
  "notes": ["..."]
}
```
Rules per `source`:
- **stable (pinned):** `artifacts[arch]` has `url` + `sha256`. You MUST verify
  the sha256 after download; refuse on mismatch.
- **ombra (`source: "github-latest"`):** resolved live to the author's newest
  GitHub release; `artifacts[arch]` has `url` only, NO sha256. Verify the hash
  at download time and log the hash you saw (acceptable for nightlies only).
- **hpkr-repo (`source: "hpkr-repo"`):** `artifacts[arch]` has `url` only
  (a third-party Haiku repo's package); same verify-and-log as ombra.
- **haikuports (`source: "haikuports"`):** `artifacts` is empty and `bridge`
  is set. Do NOT download. Tell the user to install from HaikuPorts (the
  `notes` field carries `pkgman install <pkg>`), and prefer that.

`requires` is an advisory pre-flight hint only. The real dependencies live
inside the hpkg and are resolved by the system solver against the repos already
present (haiku, haikuports, any added spritz repo). Do not re-implement
dependency solving: install the hpkg and let packagefs + the solver do the rest.

### The install queue (the Play Store loop)
Per-user, bearer auth:
```
GET  /library/pending
```
Returns the items to install:
```json
[{ "cicheto": "org.haiku.genio", "channel": "stable", "arch": "x86_64",
   "kind": "hpkg", "artifacts": {...}, "requires": [...], "version": "...",
   "notes": [...] }]
```
ombra items are already resolved live here (artifacts filled with the latest
URLs), so you do not need an extra /resolve call for them. If an item comes back
with empty `artifacts` and a `notes` entry, the live resolve failed upstream —
skip it and retry on the next poll, do not treat it as installable.
```
POST /library/{id}/installed     (bearer)  -> mark it installed once it landed
```
Poll `/library/pending` on a sensible interval (e.g. 30-60s), install each new
item, then POST `/library/{id}/installed`.

(The website is what calls `POST /library/{id}` to queue and
`POST /library/{id}/remove` to un-queue; you do not call those.)

## Install flow (end to end)
1. Browser → `spritz://install/org.haiku.genio?channel=stable`.
2. Daemon → `GET /resolve/org.haiku.genio?channel=stable&arch=<this machine>`.
3. Download each artifact; verify sha256 (stable) or verify-and-log (ombra /
   hpkr-repo); refuse on mismatch.
4. Install via packagefs; the system solver pulls dependencies.
5. If the install came from the remote queue: `POST /library/{id}/installed`.

Determine `<arch>` of the running machine (e.g. `x86_64`, `x86_gcc2h`).

## Haiku specifics to get right
- Register the `spritz://` scheme so WebPositive launches the app on such links.
- Install an hpkg the proper Haiku way (packagefs / the package kit), not by
  hand-copying files; let the dependency solver run.
- A small embedded HTTP server for `127.0.0.1:4242/ping` (BHttpServer or a
  minimal socket listener).
- HTTPS client for the registry and for downloading artifacts (verify TLS).
- Persist the user's login token securely; refresh on 401.

## Out of scope for the first version
Building packages from source (that is a build-farm, a later leg), paid apps /
donations, and the zip/non-packaged "cask" case beyond a basic unpack. Start
with: the `spritz://` handler, the `/ping` endpoint, resolve + verified install,
and the pending-queue poll.

## How to proceed
Propose the architecture and the module/file layout first (URL handler, daemon,
HTTP client, installer, local ping server, config/token storage), confirm the
Haiku APIs you will use, then implement. Keep user-facing strings consistent
with the additive-to-HaikuPorts framing. Ask before assuming any registry
behaviour not stated above.
