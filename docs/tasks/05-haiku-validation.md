# Task 05: validation on a real Haiku machine

Everything in this repo is built and tested in WSL. A few things can only be
confirmed on Haiku itself (HaikuDepot, WebPositive, packagefs, the `spritz://`
scheme). This is the checklist to run when a Haiku machine or VM is available.
Record results in `docs/DECISIONS.md`.

Assumes the spritz server is reachable from the Haiku machine at some
`BASE_URL` (e.g. `http://<dev-ip>:8000`). Run the server with
`SPRITZ_PUBLIC_BASE_URL` set to that same URL so the generated `repo.info`
advertises a reachable address.

## 1. Repo-proxy in HaikuDepot (the highest-value check)

The repo-proxy is verified end to end off-Haiku, but never consumed by a real
HaikuDepot. This is the one that matters most.

Prereq: build at least one stable sub-repo. With `package_repo` configured on
the server and a stable cichéto whose hpkg URL is reachable:

```
# on the server: build the sub-repos
curl -X POST -H "X-Admin-Token: $SPRITZ_ADMIN_TOKEN" $BASE_URL/repo/build
# note the printed sub-repo URL, e.g.
#   $BASE_URL/repo/<vendor>/<arch>/current
```

On Haiku:

```
# add the repo by its base URL
pkgman add-repo $BASE_URL/repo/<vendor>/<arch>/current
pkgman refresh
pkgman search <packagename>      # the app should appear
pkgman install <packagename>     # should download via the proxy and install
```

Check, and record:
- [ ] `repo.info` is accepted (fields parse: name, identifier, baseurl, vendor,
      priority, architecture).
- [ ] The HPKR catalog lists the package(s).
- [ ] The package downloads through the proxy URL (`.../packages/<file>`) and
      installs; dependencies resolve against haiku/haikuports.
- [ ] Add the same URL in the HaikuDepot GUI (Repositories) and confirm it shows
      there too.
- [ ] Tamper check: corrupt a cached hpkg on the server, confirm the install
      fails the integrity check rather than installing garbage.

## 2. Frontend in WebPositive

```
# point WebPositive at the server
open $BASE_URL
```

- [ ] Home and search render and are usable (layout, fonts, buttons).
- [ ] An app page renders: bridge note, channels, install section.
- [ ] `/publish` and `/library-page` render and their forms work (paste token,
      submit). Note any JS that WebPositive cannot run.
- [ ] No mixed-content surprises if the server is https.

## 3. The degrading button + spritz:// scheme

Needs the native daemon (task 04) at least stubbed: the `/ping` endpoint and the
`spritz://` handler registered.

- [ ] With the daemon NOT running: the app page shows the fallback (add-repo /
      get-spritz), no one-click button. This is the default and must always work.
- [ ] With the daemon running and answering `GET http://127.0.0.1:4242/ping`:
      the page adds the "Installa con un clic" button. Confirm WebPositive
      allows the localhost probe from the served page (mixed-content rules).
- [ ] Clicking the one-click button hands `spritz://install/<id>?channel=<ch>`
      to the daemon and starts an install.
- [ ] If 4242 is wrong for the real daemon, update `PROBE_URL` in
      `app/static/install-button.js` and re-check.

## 4. Install flows (with the daemon)

- [ ] Stable: `spritz://install/<id>?channel=stable` -> resolve -> sha256
      verified -> installed.
- [ ] ombra: `spritz://install/<id>?channel=ombra` -> resolves the latest GitHub
      release -> hash verified-and-logged -> installed.
- [ ] Remote queue: queue an install from the browser (`POST /library/{id}`),
      confirm the daemon polls `/library/pending`, installs, and
      `POST /library/{id}/installed` flips `/library` to "installed".

## Notes to capture

For each failure, record the exact error and the Haiku/HaikuDepot version. The
known unknowns going in: whether `package_repo`'s output is accepted as-is by
the running HaikuDepot version, how WebPositive treats the localhost probe from
an https page, and whether duplicate packages across repos (spritz + haikuports)
are handled cleanly (the open question in DECISIONS).
