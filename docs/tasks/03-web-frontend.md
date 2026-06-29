# Task 03: web frontend (the catalog)

The public face. This is the BeBits piece people will actually land on. It is
also the SEO funnel: someone searching "app X for Haiku" should arrive here.

## Status: FIRST CUT DONE (pending WebPositive check)

Server-rendered Jinja templates served by FastAPI, plain CSS, tiny vanilla JS.
Implemented:
- `GET /` home + search (reuses `_search_rows`, same query as `/search`).
- `GET /app/{id}` full cichéto page: bridge note, channels, author/packager,
  screenshots, and the degrading install button.
- `GET /get-spritz` bootstrap placeholder for the native client.
- `GET /publish` author form + `POST /publish` (authenticated) that validates
  the fields against the real `Cicheto` schema and returns a clean YAML to drop
  into the author's bàcaro git. Includes an icon URL field and a screenshots
  list: the cichéto `icon` and `screenshots` are links (shown on the app page;
  the icon also as a small icon in search results). As a convenience,
  `POST /upload/image` (authenticated) accepts an icon or screenshot, validates
  it by magic bytes, size-caps it (2MB icon / 5MB screenshot), stores it
  content-addressed, and returns a spritz-served `/assets/<hash>.ext` URL to
  paste in. The cichéto still references images by URL, so git stays canonical
  (see DECISIONS). Writes no cichéto server-side; the generated YAML round-trips
  through ingest. Auth is paste-the-bearer-token (reuses the existing JWT).
- `/static/spritz.css`, `/static/install-button.js`, `/static/publish.js`. The
  JSON service info moved from `/` to `/api`. Corporate navy/grey palette.
Covered by `test_frontend.py` (renders each page, checks the bridge badge/note,
the channels, the degrading script, and that templates carry no em dashes).

**The degrading button** is implemented as: the page renders the fallback by
default (add-repo for stable when a built repo exists, else a neutral note;
plus a get-spritz link), and `install-button.js` probes the native client on
`http://127.0.0.1:4242/ping` (XHR, 800ms timeout, old-JS friendly). On a hit it
prepends a `spritz://install/<id>?channel=<ch>` one-click button. On miss or
mixed-content block it silently stays on the fallback.

**Still TODO:** render-check in WebPositive (the one step that needs Haiku, not
WSL); confirm the localhost probe and the `spritz://` scheme behave there; the
optional logged-in "my apps" page; finalize the native client port/endpoint
(4242/ping is a placeholder to match whatever the daemon ends up exposing).

## Scope

A catalog UI over the existing registry API. No new backend logic, it consumes
`/search`, `/cicheto/{id}`, and the auth + library endpoints.

Pages:
- **Home / search**: search box, results list (name, summary, bàcaro, channels,
  a badge if a HaikuPorts bridge exists). Calls `GET /search?q=`.
  DONE: also filters by category and bàcaro (`?category=`, `?bacaro=`, exact
  match), category/bàcaro badges are clickable links, and a `/categories` page
  lists categories with counts (`GET /api/categories`).
- **App page**: full cichéto. Screenshots, channels (stable / ombra), author and
  packager, the bridge note ("also on HaikuPorts, use the curated version
  there") when present. Calls `GET /cicheto/{id}`.
- **Account** (optional, behind login): "my apps" / library. Calls `/library`.
  DONE: `GET /library-page` + `library.js` (paste-the-token, fetches `/library`,
  renders name + channel + arch + state). `/library` now also returns the app's
  display name, not just the id.

## The degrading install button (important)

The button adapts to whether the native client is present. Order of preference:

1. If the native client is detected -> `spritz://install/<id>?channel=<ch>`
   deep link. The client resolves dependencies and installs.
2. If not detected -> offer the right thing per channel:
   - stable hpkg: link to the repo-proxy URL with short instructions to add it
     in HaikuDepot, OR a direct hpkg download served with the correct MIME so
     Haiku opens its installer. (Task 01 provides the repo URL.)
   - plus a gentle "install spritz for automatic updates and one-click installs"
     pointing at the client bootstrap.

Client detection: prefer a local endpoint the client exposes (fetch with a
short timeout, like the Pippo pattern on localhost), fall back to the
custom-scheme timeout trick. Beware mixed-content: an HTTPS page calling
`http://localhost` is blocked by some browsers. Test in WebPositive (primary
target) and document what works.

## Stack

Keep it simple and Haiku-browser-friendly. WebPositive is the primary client,
so avoid heavy modern-JS that it cannot run. Server-rendered HTML (Jinja
templates served by FastAPI) or a very light JS frontend is preferable to a
heavy SPA. Confirm rendering in WebPositive, not just in Chrome.

## User-facing copy

All end-user strings in **Italian first** (Andrea writes the public copy),
English as a second pass. Hold the additive-to-HaikuPorts framing everywhere.
No em dashes.

## Test

- Search and app pages render correctly in WebPositive.
- The button shows the deep link when the client endpoint responds, and the
  fallback when it does not.
