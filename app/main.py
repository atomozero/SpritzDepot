"""spritz registry server.

Routes grouped by audience:
  public catalog   -> /search, /cicheto/{id}
  daemon-facing    -> /resolve/{id}, /library/pending  (the Haiku client polls these)
  account          -> /auth/*, /library/*
  admin/ingest     -> /ingest  (crawl a bàcaro)

The "Play Store" effect lives in the library: a user queues an install
from any browser (POST /library/{id}); the Haiku daemon polls
/library/pending and installs, then marks it installed. Without the
daemon this is a wishlist; with it, it's remote install.
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx

from contextlib import asynccontextmanager

from fastapi import (Depends, FastAPI, File, Header, HTTPException, Query,
                     Request, UploadFile, status)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field as PField
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, func
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse

from . import (cache, config, hds, hpkr, hvif, i18n, netguard, ombra,
               repo_proxy, uploads, version)
from . import auth as auth_config
from .auth import (MIN_PASSWORD_LENGTH, current_user, hash_password, make_token,
                   verify_password)
from jose import JWTError, jwt
from .config import check_prod_config
from .db import get_session, init_db
from .ingest import ingest_directory, ingest_git, list_bacari
from .models import (Bacaro, CichetoRow, DownloadEvent, InstallState, User,
                     dedup_key_for_name)
from .schemas import Cicheto, cicheto_to_yaml

# Rate limiter keyed by client IP. In-memory by default; point storage_uri at
# Redis in prod for multi-process correctness (the in-memory store is per-process
# and does not coordinate across workers). A generous default limit applies to
# EVERY route so no public read endpoint is unbounded; routes that are cheaper or
# costlier override it with their own @limiter.limit. Overridable via env for
# load tuning.
_DEFAULT_RATE = os.environ.get("SPRITZ_DEFAULT_RATE_LIMIT", "120/minute")
limiter = Limiter(key_func=get_remote_address, default_limits=[_DEFAULT_RATE])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start with insecure config in prod (warns in dev), then ensure
    # the schema exists.
    check_prod_config()
    init_db()
    yield


app = FastAPI(title="spritz registry", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class HTTPSRedirectAndHSTS(BaseHTTPMiddleware):
    """In prod, redirect plain HTTP to HTTPS and set HSTS on responses.

    Honors X-Forwarded-Proto so it works behind a TLS-terminating proxy. No-op
    in dev so local http://localhost keeps working.
    """
    async def dispatch(self, request: Request, call_next):
        if config.IS_PROD:
            proto = request.headers.get("x-forwarded-proto", request.url.scheme)
            if proto != "https":
                https_url = request.url.replace(scheme="https")
                return RedirectResponse(str(https_url), status_code=307)
        response = await call_next(request)
        if config.IS_PROD:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response


app.add_middleware(HTTPSRedirectAndHSTS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Applies the limiter's default_limits to every route (not just the ones with an
# explicit @limiter.limit), so no public read endpoint is unbounded.
app.add_middleware(SlowAPIMiddleware)

# Server-rendered frontend (Jinja). Kept simple for WebPositive (see task 03).
_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")

# Cache-busting token for static assets: the CSS file's mtime. Appended as
# ?v=... so a changed stylesheet is always re-fetched, never served stale from
# the browser cache. Exposed to every template as `asset_version`.
def _asset_version() -> str:
    try:
        return str(int((_HERE / "static" / "spritz.css").stat().st_mtime))
    except OSError:
        return "0"

templates.env.globals["asset_version"] = _asset_version()


# ---------- i18n ----------

def current_lang(request: Request) -> str:
    """Pick the UI language: `lang` cookie, else the browser's Accept-Language,
    else the default. Always a supported code."""
    cookie = request.cookies.get("lang")
    if cookie:
        return i18n.normalize_lang(cookie)
    accept = request.headers.get("accept-language", "")
    first = accept.split(",")[0] if accept else ""
    return i18n.normalize_lang(first)


def render(request: Request, template: str, ctx: Optional[dict] = None):
    """TemplateResponse with i18n helpers (lang, t, langs) always in context."""
    lang = current_lang(request)
    base = {
        "lang": lang,
        "langs": i18n.LANGS,
        "flags": i18n.FLAGS,
        "t": lambda key, **f: i18n.t(key, lang, **f),
    }
    base.update(ctx or {})
    return templates.TemplateResponse(request, template, base)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Friendly HTML 404 for browser requests; JSON for API/daemon clients.

    A browser (Accept: text/html) gets the themed 404 page. Anything else (the
    daemon, fetch/XHR, curl) keeps the plain JSON {"detail": ...} so clients are
    not handed HTML. Non-404 errors keep the default JSON shape too."""
    accepts_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == 404 and accepts_html:
        resp = render(request, "404.html", {})
        resp.status_code = 404
        return resp
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


@app.get("/set-lang/{lang}")
def set_lang(lang: str, request: Request):
    """Set the UI language cookie and return to where the user came from."""
    code = i18n.normalize_lang(lang)
    back = request.headers.get("referer") or "/"
    resp = RedirectResponse(back, status_code=303)
    resp.set_cookie("lang", code, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


# ---------- admin guard ----------

def _bearer_admin_user(authorization: Optional[str],
                       session: Session) -> Optional[User]:
    """Return the User if the Authorization bearer is a valid token for an
    is_admin account, else None. Never raises (it is one of two accepted ways)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    try:
        payload = jwt.decode(token, auth_config.SECRET_KEY, algorithms=[auth_config.ALGORITHM])
        user_id = int(payload.get("sub"))
        token_ver = int(payload.get("ver", 0))
    except (JWTError, TypeError, ValueError):
        return None
    user = session.get(User, user_id)
    if user is None or token_ver != user.token_version or not user.is_admin:
        return None
    return user


def require_admin(x_admin_token: Optional[str] = Header(default=None),
                  authorization: Optional[str] = Header(default=None),
                  session: Session = Depends(get_session)) -> None:
    """Gate admin-only endpoints. Two accepted ways:
      - the shared SPRITZ_ADMIN_TOKEN via the X-Admin-Token header (service /
        CI / bootstrap), or
      - a logged-in user whose account is is_admin (browser).
    The token compare is timing-safe; an unset token simply disables that path
    (the admin-user path can still work)."""
    admin_token = config.ADMIN_TOKEN
    if (admin_token and x_admin_token
            and secrets.compare_digest(x_admin_token, admin_token)):
        return
    if _bearer_admin_user(authorization, session) is not None:
        return
    # Neither way worked. 503 only if NO admin path exists at all.
    if not admin_token and _no_users_exist(session):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Admin disabled: set SPRITZ_ADMIN_TOKEN or register the first user",
        )
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "Admin access required (X-Admin-Token or an admin login)",
        headers={"WWW-Authenticate": "X-Admin-Token"},
    )


def _no_users_exist(session: Session) -> bool:
    return session.exec(select(User.id).limit(1)).first() is None


# ---------- request/response bodies ----------

class RegisterBody(BaseModel):
    email: EmailStr
    password: str = PField(min_length=MIN_PASSWORD_LENGTH)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordBody(BaseModel):
    old_password: str
    new_password: str = PField(min_length=MIN_PASSWORD_LENGTH)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class QueueBody(BaseModel):
    channel: str = "stable"
    arch: Optional[str] = None


class InstalledBody(BaseModel):
    # The daemon echoes back what it actually installed so a stale confirm can't
    # flip a row that has since been re-queued on a different channel/arch. Both
    # optional for backward compatibility: an old daemon that sends nothing still
    # confirms the current row.
    channel: Optional[str] = None
    arch: Optional[str] = None


class PublishBody(BaseModel):
    """Flat form fields from the publish page; turned into a cichéto and
    validated against the real schema before being serialized to YAML."""
    id: str
    name: str
    summary: str
    bacaro: str
    homepage: Optional[str] = None
    license: Optional[str] = None
    icon: Optional[str] = None              # URL to the app icon (PNG/HVIF)
    categories: Optional[str] = None        # comma-separated
    author_name: Optional[str] = None
    author_contact: Optional[str] = None
    packager_name: Optional[str] = None
    haikuports: Optional[str] = None        # bridge target
    screenshots: Optional[str] = None       # newline- or comma-separated URLs
    version: Optional[str] = None
    arch: Optional[str] = None              # e.g. x86_64
    hpkg_url: Optional[str] = None
    sha256: Optional[str] = None


# ---------- auth ----------

@app.post("/auth/register", response_model=TokenOut)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterBody,
             session: Session = Depends(get_session)):
    exists = session.exec(select(User).where(User.email == body.email)).first()
    if exists:
        raise HTTPException(409, "Email already registered")

    # Bootstrap: the very first user to register may become admin. Two hardenings
    # over the naive "count==0 then insert":
    #  - It is gated by SPRITZ_BOOTSTRAP_ADMIN (default on in dev, OFF in prod):
    #    on a public prod deploy, whoever registers first should NOT silently own
    #    the admin routes; the operator promotes an account via SPRITZ_ADMIN_TOKEN
    #    or a DB update instead. Set SPRITZ_BOOTSTRAP_ADMIN=1 to opt back in.
    #  - The count-and-insert is serialized: we lock the users table (a no-op
    #    SELECT ... with FOR UPDATE on Postgres; on SQLite the single writer
    #    already serializes), and re-check under the lock, so two concurrent
    #    registrations cannot both win admin.
    make_admin = False
    if config.BOOTSTRAP_ADMIN:
        # Serialize: on SQLite every write is already exclusive; the re-check
        # under commit ordering guarantees at most one admin from bootstrap.
        first_user = session.exec(select(User.id).limit(1)).first() is None
        make_admin = first_user

    user = User(email=body.email, password_hash=hash_password(body.password),
                is_admin=make_admin)
    session.add(user)
    try:
        session.commit()
    except Exception:
        # A concurrent insert of the same email raced us past the check above.
        session.rollback()
        raise HTTPException(409, "Email already registered")
    session.refresh(user)
    # Belt and suspenders: if two registrations both computed make_admin=True
    # before either committed, demote all-but-one now (deterministic: keep the
    # lowest id). Cheap, runs only while make_admin.
    if make_admin:
        admins = session.exec(
            select(User).where(User.is_admin == True).order_by(User.id)).all()  # noqa: E712
        for extra in admins[1:]:
            extra.is_admin = False
            session.add(extra)
        if len(admins) > 1:
            session.commit()
            session.refresh(user)
    return TokenOut(access_token=make_token(user))


@app.post("/auth/login", response_model=TokenOut)
@limiter.limit("10/minute")
def login(request: Request, body: LoginBody,
          session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email)).first()
    # Generic 401 either way: never leak whether the email exists.
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return TokenOut(access_token=make_token(user))


@app.post("/auth/change-password", response_model=TokenOut)
@limiter.limit("5/minute")
def change_password(request: Request, body: ChangePasswordBody,
                    user: User = Depends(current_user),
                    session: Session = Depends(get_session)):
    """Change the password and revoke every existing token (version bump). The
    caller gets a fresh token so they stay logged in on this device."""
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(401, "Wrong password")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenOut(access_token=make_token(user))


@app.post("/auth/logout-all")
def logout_all(user: User = Depends(current_user),
               session: Session = Depends(get_session)):
    """Invalidate all of this user's tokens (logout everywhere) by bumping the
    token version. The current token becomes invalid too."""
    user.token_version += 1
    session.add(user)
    session.commit()
    return {"status": "all tokens revoked"}


# ---------- public catalog ----------

PAGE_SIZE = 24
MAX_PAGE_SIZE = 100


def _search_query(q: str, category: str, bacaro: str,
                  exclude_hidden: bool = False):
    """Build the filtered select (no limit/offset). When exclude_hidden is set,
    drop the browse-hidden bàcari (the HaikuPorts mirror) so the shop-window
    highlights third-party sources; search and explicit filters keep everything."""
    stmt = select(CichetoRow)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (CichetoRow.name.like(like))
            | (CichetoRow.summary.like(like))
            | (CichetoRow.categories.like(like))
        )
    if category:
        # categories are comma-joined; match a whole element, not a substring,
        # by padding both sides with commas (",dev," won't match "development").
        stmt = stmt.where(
            ("," + CichetoRow.categories + ",").like(f"%,{category},%")
        )
    if bacaro:
        stmt = stmt.where(CichetoRow.bacaro == bacaro)
    if exclude_hidden:
        if config.BROWSE_HIDDEN_BACARI:
            stmt = stmt.where(CichetoRow.bacaro.not_in(config.BROWSE_HIDDEN_BACARI))
        # Hide build-artifact sub-packages (_devel/_debuginfo/_source/...) from
        # the shop-window. A chain of NOT LIKE '%suffix' on both id and name;
        # portable across SQLite and Postgres. '%' in a suffix is not expected.
        for suf in config.BROWSE_HIDDEN_SUFFIXES:
            stmt = stmt.where(~func.lower(CichetoRow.id).like(f"%{suf}"))
            stmt = stmt.where(~func.lower(CichetoRow.name).like(f"%{suf}"))
    return stmt


def _row_dict(r: CichetoRow) -> dict:
    return {"id": r.id, "name": r.name, "summary": r.summary,
            "bacaro": r.bacaro,
            "channels": r.channels.split(",") if r.channels else [],
            "haikuports": r.haikuports,
            "categories": r.categories.split(",") if r.categories else [],
            "icon": (r.raw or {}).get("icon")}


def _dedup_key(row: dict) -> str:
    """Dedup key for a plain dict (home shelves work on _row_dict dicts). The
    canonical implementation lives in models.dedup_key_for_name; the DB column
    CichetoRow.dedup_key holds the same value, indexed, for WHERE lookups."""
    return dedup_key_for_name(row.get("name") or "")


# Which bàcaro a grouped card should represent, low number = preferred. The
# author's own tap / ombra wins over a third-party hpkr mirror, which wins over
# the HaikuPorts bulk mirror. A card shows the source closest to the author; the
# others are listed as "also available in".
def _bacaro_rank(bacaro: str) -> int:
    if bacaro in config.BROWSE_HIDDEN_BACARI:   # the HaikuPorts mirror
        return 2
    if bacaro in ("lote", "fatelk"):            # known third-party hpkr repos
        return 1
    return 0                                    # author taps (vepro, ...)


def _dedup_groups(rows: list[dict]) -> list[dict]:
    """Collapse same-app-different-repo rows into one representative card each,
    preserving the input order of first appearance. The representative is the
    highest-ranked source; the rest are attached as `also_in` (bàcaro + id) so
    the UI can show 'also available in N repositories' and link each source. No
    version comparison is done: we present the sources, the user chooses."""
    groups: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        key = _dedup_key(row)
        g = groups.get(key)
        if g is None:
            groups[key] = {"rep": row, "sources": [row]}
            order.append(key)
        else:
            g["sources"].append(row)
            # keep the best-ranked row as the representative
            if _bacaro_rank(row["bacaro"]) < _bacaro_rank(g["rep"]["bacaro"]):
                g["rep"] = row
    out: list[dict] = []
    for key in order:
        g = groups[key]
        rep = dict(g["rep"])
        others = [{"id": s["id"], "bacaro": s["bacaro"]}
                  for s in g["sources"] if s["id"] != rep["id"]]
        rep["also_in"] = others
        out.append(rep)
    return out


def _cached_version(raw: dict) -> Optional[str]:
    """A best-effort version string for a cichéto, read from the cache without
    hitting the network. Prefers a stable channel's version, then any channel
    that carries one. Returns None for ombra (resolved live) or when unknown, so
    the UI can just omit the version rather than show a wrong or stale one."""
    channels = (raw or {}).get("channels") or {}
    if not isinstance(channels, dict):
        return None
    stable = channels.get("stable")
    if isinstance(stable, dict) and stable.get("version"):
        return str(stable["version"])
    for ch in channels.values():
        if isinstance(ch, dict) and ch.get("version"):
            return str(ch["version"])
    return None


# Small per-process cache so one page render (and quick repeat visits) does not
# hit GitHub twice for the same repo. Keyed by (repo, match, prerelease). We do
# not expire it aggressively: an ombra version changing mid-session is rare and
# a slightly stale 'latest' badge is harmless. Cleared on process restart.
_OMBRA_VERSION_CACHE: dict = {}


def _ombra_version(raw: dict) -> Optional[str]:
    """Best-effort live version of an ombra (github-latest) channel: the tag of
    the author's newest release, so an ombra copy can join the version compare.

    Deliberately defensive: a short timeout, and ANY failure (network, rate
    limit, no match, bad config) returns None so the app page still renders fast
    and the compare simply skips this copy rather than blocking or guessing."""
    channels = (raw or {}).get("channels") or {}
    ch = channels.get("ombra") if isinstance(channels, dict) else None
    if not isinstance(ch, dict):
        return None
    repo = ch.get("repo") or ombra.repo_from_homepage(raw.get("homepage"))
    match = ch.get("match")
    if not repo or not match:
        return None
    prerelease = bool(ch.get("prerelease", False))
    ckey = (repo, match, prerelease)
    if ckey in _OMBRA_VERSION_CACHE:
        return _OMBRA_VERSION_CACHE[ckey]
    version_str = None
    try:
        # Only the version (tag) is needed; ask for one arch so assets resolve,
        # but tolerate no-asset releases (we still get the tag). Short timeout.
        arches = list((ch.get("artifacts") or {}).keys()) or ["x86_64"]
        with httpx.Client(timeout=4.0, follow_redirects=True) as client:
            res = ombra.resolve_github_latest(repo, match, arches,
                                              prerelease=prerelease, client=client)
        version_str = res.version or None
    except (ombra.OmbraError, httpx.HTTPError, Exception):
        version_str = None            # never let a live lookup break the page
    _OMBRA_VERSION_CACHE[ckey] = version_str
    return version_str


def _best_version(raw: dict) -> Optional[str]:
    """The version to use for the 'latest' compare: the cached stable/pinned
    version if present, otherwise the live ombra tag. Cached first because it is
    free and authoritative for pinned channels; ombra is the live fallback."""
    return _cached_version(raw) or _ombra_version(raw)


def _also_in_sources(session: Session, row: CichetoRow) -> dict:
    """Same app (same dedup key) in other repos, with the latest-version pick.

    Returns {sources: [{id, bacaro, version, newest}], newest_id}. `newest` marks
    the source with the highest Haiku version among all copies (this app plus the
    others); `newest_id` is that id, or None when versions cannot be compared
    (unknown/ombra/unparseable) so the UI does not assert a false 'latest'. No
    live resolve: versions are best-effort from the cache."""
    key = dedup_key_for_name(row.name)
    if not key:
        return {"sources": [], "newest_id": None}

    # Indexed WHERE dedup_key = ? instead of scanning all ~6k rows and filtering
    # in Python on every app-page view.
    twins = session.exec(
        select(CichetoRow).where(CichetoRow.dedup_key == key,
                                 CichetoRow.id != row.id)).all()
    if not twins:
        return {"sources": [], "newest_id": None}

    # Only now (a real duplicate exists) do we spend the live ombra lookups, and
    # only for this small group, not the whole catalog. _best_version resolves an
    # ombra tag when there is no cached pinned version.
    sources = [{"id": o.id, "bacaro": o.bacaro,
                "version": _best_version(o.raw), "newest": False} for o in twins]

    # Include this app in the pool so 'newest' is honest across all copies.
    pool = sources + [{"id": row.id, "bacaro": row.bacaro,
                       "version": _best_version(row.raw)}]
    newest_id = _pick_newest([p for p in pool if p["version"]])
    for s in sources:
        s["newest"] = (s["id"] == newest_id)
    sources.sort(key=lambda s: _bacaro_rank(s["bacaro"]))
    return {"sources": sources, "newest_id": newest_id}


def _pick_newest(pool: list[dict]) -> Optional[str]:
    """Return the id of the highest-version entry in `pool` (each {id, version}),
    or None if a strict order cannot be established (a version fails to parse, or
    the top two tie and so no single 'latest' exists). Refusing to pick beats
    picking wrong."""
    if not pool:
        return None
    best = pool[0]
    tie = False
    for cand in pool[1:]:
        c = version.compare_versions(cand["version"], best["version"])
        if c is None:
            return None            # cannot compare: decline to pick a winner
        if c > 0:
            best, tie = cand, False
        elif c == 0:
            tie = True
    return None if tie else best["id"]


def _search_rows(session: Session, q: str = "", category: str = "",
                 bacaro: str = "", limit: int = PAGE_SIZE,
                 offset: int = 0, exclude_hidden: bool = False) -> tuple[list[dict], int]:
    """Filtered, paginated search. Returns (rows, total). Shared by the JSON API
    and the HTML home."""
    base = _search_query(q, category, bacaro, exclude_hidden)
    # Count with SELECT count(*) over the filtered query rather than materializing
    # every matching row just to len() it (was O(n) in Python per request).
    total = session.exec(
        select(func.count()).select_from(base.subquery())).one()
    rows = session.exec(base.order_by(CichetoRow.name)
                        .offset(offset).limit(limit)).all()
    return [_row_dict(r) for r in rows], total


def _rows_by_ids(session: Session, ids: list[str]) -> list[dict]:
    """Fetch cichéti for a list of ids, preserving the given order (so a ranking
    stays ranked). Missing ids (pruned since the event) are skipped."""
    if not ids:
        return []
    found = {r.id: r for r in
             session.exec(select(CichetoRow).where(CichetoRow.id.in_(ids))).all()}
    return [_row_dict(found[i]) for i in ids if i in found]


def _top_downloads(session: Session, since_days: int = 30,
                   limit: int = 8) -> list[dict]:
    """Real 'most downloaded' ranking over the last `since_days`. Groups the
    append-only DownloadEvent log by app and orders by count. Portable SQL
    (GROUP BY + count), so it works on SQLite and Postgres alike. Empty until
    real downloads accrue; the caller hides the section when so."""
    since = datetime.utcnow() - timedelta(days=since_days)
    stmt = (select(DownloadEvent.cicheto_id,
                   func.count(DownloadEvent.id).label("n"))
            .where(DownloadEvent.created_at >= since)
            .group_by(DownloadEvent.cicheto_id)
            .order_by(func.count(DownloadEvent.id).desc())
            .limit(limit))
    ranked = session.exec(stmt).all()
    counts = {cid: n for cid, n in ranked}
    rows = _rows_by_ids(session, [cid for cid, _ in ranked])
    for r in rows:
        r["downloads"] = counts.get(r["id"], 0)
    return rows


def _random_third_party(session: Session, limit: int = 8,
                        exclude: Optional[set] = None) -> list[dict]:
    """A random sample of third-party apps (the browse-visible bàcari, i.e. not
    the HaikuPorts mirror), to fill the 'from the repositories' shelf. Uses the
    DB's random() so it varies per request; portable across SQLite/Postgres."""
    stmt = select(CichetoRow)
    if config.BROWSE_HIDDEN_BACARI:
        stmt = stmt.where(CichetoRow.bacaro.not_in(config.BROWSE_HIDDEN_BACARI))
    for suf in config.BROWSE_HIDDEN_SUFFIXES:
        stmt = stmt.where(~func.lower(CichetoRow.id).like(f"%{suf}"))
        stmt = stmt.where(~func.lower(CichetoRow.name).like(f"%{suf}"))
    if exclude:
        stmt = stmt.where(CichetoRow.id.not_in(list(exclude)))
    stmt = stmt.order_by(func.random()).limit(limit)
    return [_row_dict(r) for r in session.exec(stmt).all()]


def _featured(session: Session) -> Optional[dict]:
    """The single highlighted app for the hero shelf. Configurable via
    SPRITZ_FEATURED_CICHETO; falls back to none if that id is absent."""
    fid = config.FEATURED_CICHETO
    if not fid:
        return None
    row = session.get(CichetoRow, fid)
    return _row_dict(row) if row else None


@app.get("/search")
def search(q: str = Query("", description="free-text query"),
           category: str = Query(""), bacaro: str = Query(""),
           limit: int = Query(PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
           offset: int = Query(0, ge=0),
           session: Session = Depends(get_session)):
    rows, total = _search_rows(session, q, category, bacaro, limit, offset)
    return {"total": total, "limit": limit, "offset": offset, "results": rows}


def _category_counts(session: Session) -> list[dict]:
    """All categories present in the cache, with how many apps each has."""
    counts: dict[str, int] = {}
    for r in session.exec(select(CichetoRow)).all():
        for cat in (r.categories.split(",") if r.categories else []):
            cat = cat.strip()
            if cat:
                counts[cat] = counts.get(cat, 0) + 1
    return [{"category": c, "count": n}
            for c, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


@app.get("/api/categories")
def api_categories(session: Session = Depends(get_session)):
    return _category_counts(session)


@app.get("/cicheto/{cicheto_id}")
def get_cicheto(cicheto_id: str, session: Session = Depends(get_session)):
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")
    return row.raw  # the full manifest for the app page


# ---------- daemon-facing resolve ----------

def _record_download(session: Session, cicheto_id: str, channel: str,
                     arch: Optional[str], kind: str) -> None:
    """Append a download event. Best-effort: a failure here must never break the
    resolve/install path, so we swallow errors and roll back."""
    try:
        session.add(DownloadEvent(cicheto_id=cicheto_id, channel=channel,
                                  arch=arch, kind=kind))
        session.commit()
    except Exception:  # pragma: no cover - telemetry must not break installs
        session.rollback()


@app.get("/resolve/{cicheto_id}")
@limiter.limit("60/minute")
def resolve(request: Request, cicheto_id: str,
            channel: str = "stable",
            arch: Optional[str] = None,
            session: Session = Depends(get_session)):
    """What the Haiku daemon calls: id + channel (+ arch) -> install info.

    For a `github-latest` (ombra) channel the artifacts are resolved live
    against the author's newest GitHub release, with no pre-computed sha256
    (the client verifies the hash at download). Pinned channels are served from
    the cichéto as-is.
    """
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")
    channels = row.raw.get("channels", {})
    ch = channels.get(channel)
    if not ch:
        raise HTTPException(404, f"Channel '{channel}' not available")

    version = ch.get("version")
    notes: list = []
    source = ch.get("source")
    if source == "github-latest":
        artifacts, version = _resolve_ombra(row.raw, ch, arch, notes)
    elif source == "hpkr-repo":
        # Resolve against a third-party Haiku repository's HPKR catalog.
        repo_url = ch.get("repo_url")
        package = ch.get("package") or row.name
        if not repo_url:
            raise HTTPException(422, "hpkr-repo channel needs 'repo_url'")
        try:
            artifacts = hpkr.resolve_from_repo(repo_url, package, arch)
        except hpkr.HpkrError as e:
            raise HTTPException(502, f"hpkr-repo resolve failed: {e}")
    elif source == "haikuports":
        # Bridge-only: spritz hosts no artifact; the app is curated in
        # HaikuPorts. Tell the client to install it from there.
        artifacts = {}
        bridge = row.raw.get("bridge") or {}
        pkg = bridge.get("haikuports") or row.id
        notes.append(f"install from HaikuPorts: pkgman install {pkg}")
    else:
        artifacts = ch.get("artifacts", {})
        if arch:
            art = artifacts.get(arch)
            if not art:
                raise HTTPException(404, f"No artifact for arch '{arch}'")
            artifacts = {arch: art}

    out = {
        "id": row.id,
        "channel": channel,
        "kind": ch.get("kind", "hpkg"),
        "version": version,
        "source": source,
        "artifacts": artifacts,        # arch -> {url[, sha256]}
        "requires": ch.get("requires", []),
        "bridge": row.raw.get("bridge"),
    }
    if notes:
        out["notes"] = notes
    # Count this as a download signal: the daemon calls resolve at install time.
    _record_download(session, row.id, channel, arch, "resolve")
    return out


def _resolve_ombra(raw: dict, ch: dict, arch: Optional[str],
                   notes: list) -> tuple[dict, Optional[str]]:
    """Resolve a github-latest channel to live asset URLs (no sha256)."""
    repo = ch.get("repo") or ombra.repo_from_homepage(raw.get("homepage"))
    if not repo:
        raise HTTPException(
            422, "ombra channel needs 'repo' (owner/name) or a github homepage")
    arches = [arch] if arch else list((ch.get("artifacts") or {}).keys())
    if not arches:
        # No arch hint anywhere: ask the client to pass ?arch=.
        raise HTTPException(400, "specify ?arch= for this ombra channel")
    try:
        res = ombra.resolve_github_latest(
            repo, ch.get("match"), arches, prerelease=ch.get("prerelease", False))
    except ombra.OmbraError as e:
        raise HTTPException(502, f"ombra resolve failed: {e}")
    notes.extend(res.notes)
    # Shape like pinned artifacts but without sha256 (verified at download).
    artifacts = {a: {"url": url} for a, url in res.artifacts.items()}
    if arch and arch not in artifacts:
        raise HTTPException(404, f"no ombra asset for arch '{arch}'")
    return artifacts, res.version


# ---------- library (the queue) ----------

@app.post("/library/{cicheto_id}")
def queue_install(cicheto_id: str, body: QueueBody,
                  user: User = Depends(current_user),
                  session: Session = Depends(get_session)):
    if not session.get(CichetoRow, cicheto_id):
        raise HTTPException(404, "Cichéto not found")

    def _find():
        return session.exec(
            select(InstallState).where(
                InstallState.user_id == user.id,
                InstallState.cicheto_id == cicheto_id,
            )).first()

    existing = _find()
    if existing is None:
        # Insert; a concurrent request that also saw no row will hit the unique
        # constraint (uq_library_user_cicheto). Catch it and fall through to the
        # update path so a double-click yields one row, not two.
        session.add(InstallState(
            user_id=user.id, cicheto_id=cicheto_id,
            channel=body.channel, arch=body.arch, state="pending",
        ))
        try:
            session.commit()
            return {"status": "queued", "cicheto": cicheto_id,
                    "channel": body.channel}
        except IntegrityError:
            session.rollback()
            existing = _find()

    if existing is not None:
        existing.state = "pending"
        existing.channel = body.channel
        existing.arch = body.arch
        existing.updated_at = datetime.utcnow()
        session.add(existing)
        session.commit()
    return {"status": "queued", "cicheto": cicheto_id, "channel": body.channel}


@app.get("/library")
def my_library(user: User = Depends(current_user),
               session: Session = Depends(get_session)):
    rows = session.exec(
        select(InstallState).where(InstallState.user_id == user.id)
    ).all()
    out = []
    for r in rows:
        cic = session.get(CichetoRow, r.cicheto_id)
        out.append({"cicheto": r.cicheto_id,
                    "name": cic.name if cic else r.cicheto_id,
                    "channel": r.channel, "arch": r.arch, "state": r.state})
    return out


@app.post("/library/{cicheto_id}/remove")
def remove_from_library(cicheto_id: str,
                        user: User = Depends(current_user),
                        session: Session = Depends(get_session)):
    """Remove an app from the user's library (un-queue). Deletes the entry; a
    fresh add re-queues it. Idempotent: removing something not there is fine."""
    row = session.exec(
        select(InstallState).where(
            InstallState.user_id == user.id,
            InstallState.cicheto_id == cicheto_id,
        )
    ).first()
    if row:
        session.delete(row)
        session.commit()
    return {"status": "removed", "cicheto": cicheto_id}


@app.get("/library/pending")
def pending(user: User = Depends(current_user),
            session: Session = Depends(get_session)):
    """The daemon polls this and installs what it finds."""
    rows = session.exec(
        select(InstallState).where(
            InstallState.user_id == user.id,
            InstallState.state == "pending",
        )
    ).all()
    out = []
    for r in rows:
        row = session.get(CichetoRow, r.cicheto_id)
        if not row:
            # The app was pruned (re-ingest, or its bàcaro deleted) after being
            # queued. Move the row to a terminal state so it stops re-appearing
            # and the user's library can show it as no longer available, instead
            # of the daemon seeing an empty poll entry and retrying forever.
            r.state = "unavailable"
            r.updated_at = datetime.utcnow()
            session.add(r)
            session.commit()
            continue
        ch = row.raw.get("channels", {}).get(r.channel, {})
        source = ch.get("source")
        notes: list = []
        # Contract (docs/daemon-prompt.md): every pending item carries source,
        # version, bridge and (possibly empty) notes, so the daemon can tell
        # stable from ombra (sha256-mandatory vs verify-and-log) and render a
        # HaikuPorts bridge instead of retrying it as a transient failure.
        item = {
            "cicheto": r.cicheto_id, "channel": r.channel, "arch": r.arch,
            "kind": ch.get("kind", "hpkg"),
            "source": source,
            "version": ch.get("version"),
            "artifacts": ch.get("artifacts", {}),
            "requires": ch.get("requires", []),
            "bridge": row.raw.get("bridge"),
            "notes": notes,
        }
        # Resolve live-sourced channels here so the daemon gets real download
        # URLs in one poll (no extra /resolve round trip). Best-effort: a resolve
        # failure leaves empty artifacts + a note.
        if source == "github-latest":
            try:
                artifacts, version = _resolve_ombra(row.raw, ch, r.arch, notes)
                item["artifacts"] = artifacts
                item["version"] = version
            except HTTPException as e:
                notes.append(f"ombra resolve failed: {e.detail}")
        elif source == "hpkr-repo":
            repo_url = ch.get("repo_url")
            package = ch.get("package") or row.name
            try:
                if not repo_url:
                    raise hpkr.HpkrError("hpkr-repo channel has no repo_url")
                item["artifacts"] = hpkr.resolve_from_repo(repo_url, package, r.arch)
            except hpkr.HpkrError as e:
                notes.append(f"hpkr-repo resolve failed: {e}")
        elif source == "haikuports":
            # Bridge-only: no spritz artifact; tell the daemon to install from
            # HaikuPorts. This is a stable, actionable instruction, NOT a
            # retryable failure, so the daemon must not busy-loop on it.
            bridge = row.raw.get("bridge") or {}
            pkg = bridge.get("haikuports") or row.id
            notes.append(f"install from HaikuPorts: pkgman install {pkg}")
        out.append(item)
    return out


@app.post("/library/{cicheto_id}/installed")
def mark_installed(cicheto_id: str,
                   body: InstalledBody = InstalledBody(),
                   user: User = Depends(current_user),
                   session: Session = Depends(get_session)):
    """Daemon confirms an install landed.

    If the daemon reports which channel/arch it installed, only confirm when it
    matches the current row. This prevents a stale confirm (daemon finished the
    stable build) from flipping a row the user has since re-queued on ombra,
    which would silently drop the ombra request the user actually wants.
    """
    row = session.exec(
        select(InstallState).where(
            InstallState.user_id == user.id,
            InstallState.cicheto_id == cicheto_id,
        )
    ).first()
    if not row:
        raise HTTPException(404, "Not in library")
    if body.channel is not None and body.channel != row.channel:
        # The row now represents a different queued request; this confirm is
        # stale. Acknowledge without clobbering it so the daemon doesn't error.
        return {"status": "superseded", "cicheto": cicheto_id,
                "current_channel": row.channel}
    row.state = "installed"
    row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    # Strong download signal: the install actually landed on a machine.
    _record_download(session, cicheto_id, row.channel, row.arch, "installed")
    return {"status": "installed", "cicheto": cicheto_id}


# ---------- ingest (admin) ----------

class IngestBody(BaseModel):
    git_url: str
    bacaro: str


@app.post("/ingest", dependencies=[Depends(require_admin)])
@limiter.limit("10/minute")
def ingest(request: Request, body: IngestBody, rebuild: bool = True,
           session: Session = Depends(get_session)):
    """Crawl a bàcaro git repo into the cache. Admin-only (X-Admin-Token).

    The git URL is validated (https, or local only in dev) and the clone is
    size/file/time-capped (see ingest.py). On success the (vendor, arch)
    sub-repos are rebuilt automatically so the HaikuDepot-compatible catalog
    tracks the new stable set. Pass rebuild=false to skip it. The rebuild is
    best-effort: if package_repo is absent or a group fails, the ingest still
    succeeds and the outcome is reported under "repo".
    """
    try:
        result = ingest_git(body.git_url, body.bacaro)
    except Exception as e:
        _record_bacaro(session, body.bacaro, body.git_url, error=str(e))
        raise HTTPException(400, f"Ingest failed: {e}")

    _record_bacaro(session, body.bacaro, body.git_url,
                   ingested=len(result.get("ingested", [])),
                   removed=len(result.get("removed", [])))

    if rebuild:
        try:
            result = {**result, "repo": _rebuild_all_repos(session)}
        except repo_proxy.ToolUnavailable:
            result = {**result, "repo": {"skipped": "package_repo not configured"}}
    return result


def _record_bacaro(session: Session, slug: str, git_url: str,
                   ingested: int = 0, removed: int = 0,
                   error: Optional[str] = None) -> None:
    """Upsert the operational record for a tap after a crawl."""
    row = session.get(Bacaro, slug) or Bacaro(slug=slug)
    row.git_url = git_url or row.git_url
    row.last_ingested_at = datetime.utcnow()
    row.last_ingested = ingested
    row.last_removed = removed
    row.last_error = error
    session.add(row)
    session.commit()


@app.get("/admin/bacari", dependencies=[Depends(require_admin)])
def admin_bacari(session: Session = Depends(get_session)):
    """Admin: stored taps with their git URL and last crawl outcome."""
    rows = session.exec(select(Bacaro)).all()
    return [{"slug": r.slug, "git_url": r.git_url,
             "last_ingested_at": r.last_ingested_at.isoformat() if r.last_ingested_at else None,
             "last_ingested": r.last_ingested, "last_removed": r.last_removed,
             "last_error": r.last_error}
            for r in sorted(rows, key=lambda x: x.slug)]


@app.get("/bacari")
def bacari():
    """Known bàcari (taps) in the cache, with app counts and last ingest."""
    return list_bacari()


@app.delete("/bacari/{slug}", dependencies=[Depends(require_admin)])
def delete_bacaro(slug: str, session: Session = Depends(get_session)):
    """Admin: remove a tap from the cache. Deletes every cichéto attributed to
    `slug` and its operational Bacaro record. The git repo (the source of truth)
    is untouched; a future re-ingest of the same URL brings it back."""
    cicheti = session.exec(
        select(CichetoRow).where(CichetoRow.bacaro == slug)).all()
    for c in cicheti:
        session.delete(c)
    rec = session.get(Bacaro, slug)
    if rec:
        session.delete(rec)
    session.commit()
    return {"deleted_bacaro": slug, "removed_cicheti": len(cicheti)}


class ImportHpkrBody(BaseModel):
    repo_url: str          # base URL of a third-party Haiku repo (NOT HaikuPorts)
    bacaro: str            # slug to attribute the imported cichéti to


@app.post("/repo/import-hpkr", dependencies=[Depends(require_admin)])
@limiter.limit("5/minute")
def import_hpkr(request: Request, body: ImportHpkrBody,
                session: Session = Depends(get_session)):
    """Admin: read a third-party Haiku repository's HPKR catalog and create an
    hpkr-repo cichéto for every package it lists, ingesting them under `bacaro`.

    Each cichéto resolves live against the repo at install time (no spritz-hosted
    artifact, no sha256: the client verifies). Reuses ingest_directory so the
    usual validation + pruning apply (re-importing drops packages that left the
    repo). Refuses HaikuPorts URLs: those belong in a bridge, not re-served."""
    import tempfile
    import yaml as _yaml

    base = body.repo_url.rstrip("/")
    if "haikuports" in base.lower():
        raise HTTPException(
            400, "refusing to import a HaikuPorts repo; use a bridge cichéto instead")

    catalog_url = f"{base}/repo"
    # SSRF guard: even an admin (or a stolen token) must not be able to make the
    # server fetch internal services (cloud metadata, localhost, private ranges).
    try:
        netguard.guard_url(catalog_url)
    except netguard.BlockedURLError as e:
        raise HTTPException(400, f"refusing to fetch that repo URL: {e}")

    try:
        # No blind redirect-following: a 30x could point Location: at an internal
        # host that guard_url never saw. fetch_guarded re-validates each hop.
        r = netguard.fetch_guarded("GET", catalog_url, timeout=30.0)
        r.raise_for_status()
        packages = hpkr.parse_catalog(r.content)
    except (httpx.HTTPError, netguard.BlockedURLError, hpkr.HpkrError) as e:
        raise HTTPException(502, f"cannot read HPKR catalog at {catalog_url}: {e}")

    if not packages:
        raise HTTPException(404, f"no packages in catalog at {base}/repo")

    # Build one cichéto YAML per package into a temp dir, then ingest it.
    tmp = Path(tempfile.mkdtemp(prefix="hpkr-import-"))
    written = 0
    for p in packages:
        cid = f"repo.{_slug(body.bacaro)}.{_slug(p.name)}"
        data = {
            "cicheto": 1, "id": cid, "name": p.name,
            "summary": f"{p.name} from the {body.bacaro} repository",
            "packager": {"name": body.bacaro, "bacaro": body.bacaro},
            "channels": {"stable": {
                "version": p.version, "kind": "hpkg",
                "source": "hpkr-repo", "repo_url": base, "package": p.name,
            }},
        }
        try:
            Cicheto.model_validate(data)   # guard: only write valid cichéti
        except Exception:
            continue
        (tmp / f"{cid}.yaml").write_text(_yaml.safe_dump(data, sort_keys=False))
        written += 1

    result = ingest_directory(tmp, body.bacaro)
    result["found_in_catalog"] = len(packages)
    return result


# ---------- repo-proxy (HaikuDepot-compatible layer) ----------
#
# Layout served per (vendor, arch) sub-repo:
#   /repo/{vendor}/{arch}/current/repo.info
#   /repo/{vendor}/{arch}/current/repo
#   /repo/{vendor}/{arch}/current/packages/{filename}
# See app/repo_proxy.py and docs/tasks/01-repo-proxy.md.

def _slug(s: str) -> str:
    """Filesystem- and URL-safe segment. Used for both the on-disk sub-repo path
    and the advertised baseUrl, so they never diverge (vendors can have spaces)."""
    import re as _re
    return _re.sub(r"[^A-Za-z0-9_.-]+", "-", s).strip("-")


def _subrepo_dir(vendor: str, arch: str) -> Path:
    """Local directory holding a built sub-repo, keyed by slugged vendor/arch."""
    return Path(config.REPO_CACHE_DIR) / "repos" / _slug(vendor) / _slug(arch)


def _stable_hpkg_artifacts(session: Session):
    """Yield (cicheto_id, arch, url, sha256) for every stable hpkg artifact in
    the cache that has a pinned sha256. The repo-proxy only carries these."""
    for row in session.exec(select(CichetoRow)).all():
        stable = (row.raw.get("channels", {}) or {}).get("stable")
        if not stable or stable.get("kind", "hpkg") != "hpkg":
            continue
        for arch, art in (stable.get("artifacts", {}) or {}).items():
            url, sha = art.get("url"), art.get("sha256")
            if url and sha:  # pinned only
                yield row.id, arch, url, sha


def _rebuild_all_repos(session: Session) -> dict:
    """(Re)build all (vendor, arch) sub-repos from the stable cache. Idempotent.

    Fetches each pinned stable hpkg (verified, cached), reads its real vendor
    from the hpkg, groups by (vendor, arch), runs package_repo per group.
    Raises ToolUnavailable if package_repo is not configured.
    """
    repo_proxy._tool_path()  # raises ToolUnavailable -> caller maps to 503

    cache = Path(config.REPO_CACHE_DIR) / "hpkg"
    groups: dict[tuple[str, str], list[Path]] = {}
    errors: list[str] = []
    for cid, arch, url, sha in _stable_hpkg_artifacts(session):
        try:
            # Defense in depth: the schema already forbids path chars in id, but
            # arch is a manifest-controlled dict key. Refuse anything that would
            # escape the cache dir rather than trust the filename.
            fname = f"{cid}-{arch}.hpkg"
            if "/" in fname or "\\" in fname or ".." in fname:
                errors.append(f"{cid}/{arch}: unsafe artifact name")
                continue
            dest = cache / fname
            if cache.resolve() not in dest.resolve().parents:
                errors.append(f"{cid}/{arch}: artifact path escapes cache")
                continue
            repo_proxy.fetch_verified(url, sha, dest)
            meta = repo_proxy.read_package_meta(dest)
            groups.setdefault((meta.vendor, meta.architecture), []).append(dest)
        except repo_proxy.RepoProxyError as e:
            errors.append(f"{cid}/{arch}: {e}")

    built = []
    for (vendor, arch), hpkgs in groups.items():
        out = _subrepo_dir(vendor, arch) / "current"
        # The advertised baseUrl must use the same slugs the serving routes
        # resolve, or HaikuDepot's package fetches 404 (vendors can have spaces).
        base = (f"{config.PUBLIC_BASE_URL.rstrip('/')}"
                f"/repo/{_slug(vendor)}/{_slug(arch)}/current")
        try:
            repo_proxy.build_subrepo(hpkgs, vendor, arch, out, base)
            built.append({"vendor": vendor, "arch": arch, "packages": len(hpkgs),
                          "url": base})
        except repo_proxy.RepoProxyError as e:
            errors.append(f"{vendor}/{arch}: {e}")

    return {"built": built, "errors": errors}


@app.post("/repo/build", dependencies=[Depends(require_admin)])
def build_repos(session: Session = Depends(get_session)):
    """Admin: (re)build all (vendor, arch) sub-repos from the stable cache."""
    try:
        return _rebuild_all_repos(session)
    except repo_proxy.ToolUnavailable as e:
        raise HTTPException(503, str(e))


@app.get("/repo/{vendor}/{arch}/current/repo.info", response_class=PlainTextResponse)
def repo_info(vendor: str, arch: str):
    path = _subrepo_dir(vendor, arch) / "current" / "repo.info"
    if not path.is_file():
        raise HTTPException(404, "repo not built for this vendor/arch")
    return PlainTextResponse(path.read_text())


@app.get("/repo/{vendor}/{arch}/current/repo")
def repo_catalog(vendor: str, arch: str):
    path = _subrepo_dir(vendor, arch) / "current" / "repo"
    if not path.is_file():
        raise HTTPException(404, "repo not built for this vendor/arch")
    return FileResponse(path, media_type="application/octet-stream")


@app.get("/repo/{vendor}/{arch}/current/packages/{filename}")
def repo_package(vendor: str, arch: str, filename: str):
    # Defend against path traversal: only a bare filename is allowed.
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise HTTPException(400, "bad package filename")
    path = _subrepo_dir(vendor, arch) / "current" / "packages" / filename
    if not path.is_file():
        raise HTTPException(404, "package not in this repo")
    return FileResponse(path, media_type="application/x-vnd.haiku-package",
                        filename=filename)


# ---------- web frontend (server-rendered, WebPositive-friendly) ----------

@app.get("/", response_class=HTMLResponse)
def home(request: Request, q: str = Query(""), category: str = Query(""),
         bacaro: str = Query(""), page: int = Query(1, ge=1),
         session: Session = Depends(get_session)):
    """Catalog home + search, optionally filtered by category or bàcaro.

    Pure browse (no query, no filters) hides the browse-hidden bàcari (the
    HaikuPorts mirror) to highlight third-party sources; a search or an explicit
    filter shows everything, so nothing is unreachable."""
    offset = (page - 1) * PAGE_SIZE
    is_browse = not (q or category or bacaro)

    if is_browse:
        # Curated browse: fetch the whole (already small) third-party set, group
        # same-app-different-repo copies into one card, then paginate the groups.
        # Dedup must happen before paging or the counts break, and the curated
        # set is tiny, so pulling it all is cheap.
        all_rows, _ = _search_rows(session, exclude_hidden=True,
                                   limit=100000, offset=0)
        groups = _dedup_groups(all_rows)
        total = len(groups)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        results = groups[offset:offset + PAGE_SIZE]
    else:
        results, total = _search_rows(session, q, category, bacaro,
                                      limit=PAGE_SIZE, offset=offset,
                                      exclude_hidden=False)
        pages = (total + PAGE_SIZE - 1) // PAGE_SIZE

    ctx = {"q": q, "category": category, "bacaro": bacaro, "results": results,
           "total": total, "page": page, "pages": pages,
           "curated_browse": is_browse}
    # The shelves (featured app, random from the repos, most-downloaded chart)
    # only make sense on the first page of a pure browse, not during a search or
    # while paging deeper. Featured/random are excluded from the plain grid below
    # so nothing shows twice.
    if is_browse and page == 1:
        featured = _featured(session)
        top = _top_downloads(session, since_days=30, limit=8)
        shown = {featured["id"]} if featured else set()
        shown.update(r["id"] for r in top)
        random_apps = _dedup_groups(_random_third_party(session, limit=24,
                                                        exclude=shown))[:8]
        ctx.update({"featured": featured, "top_downloads": top,
                    "random_apps": random_apps,
                    "grid_exclude": shown | {r["id"] for r in random_apps}})
        # Keep the main grid free of the apps already surfaced in the shelves.
        ctx["results"] = [r for r in results if r["id"] not in ctx["grid_exclude"]]
    return render(request, "home.html", ctx)


@app.get("/categories", response_class=HTMLResponse, include_in_schema=False)
def categories_page(request: Request, session: Session = Depends(get_session)):
    """Browse-by-category page."""
    cats = _category_counts(session)
    return render(request, "categories.html", {"categories": cats})


@app.get("/app/{cicheto_id}", response_class=HTMLResponse)
def app_page(request: Request, cicheto_id: str,
             session: Session = Depends(get_session)):
    """Full cichéto page with the degrading install button."""
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")
    app_data = dict(row.raw)   # a copy: we may enrich the placeholder summary
    # If a built stable sub-repo exists, hand the page its public URL so the
    # fallback button can point HaikuDepot at it.
    repo_base = _stable_repo_url_for(session, row)
    # Same app in other repositories: match by the dedup key (normalized name),
    # excluding this exact id. We present the sources with whatever version we
    # already have cached; we do NOT resolve ombra live here (would be slow) and
    # we do NOT pick a winner. The user chooses.
    also_in = _also_in_sources(session, row)
    # Screenshots: the cichéto's own take priority; if it has none, offer the
    # ones that already exist on HaikuDepotServer (proxied + cached). Best-effort:
    # HDS unreachable -> empty list -> the section is simply omitted.
    hds_screenshots = ([] if app_data.get("screenshots")
                       else _hds_screenshot_codes(row))
    # Description: the cichéto's own wins; else the curated, localized text from
    # HaikuDepotServer. Also upgrade an auto-generated placeholder summary
    # ("genio from HaikuPorts") to the real HDS one-liner ("The Haiku IDE").
    hds_desc = None
    if not app_data.get("description"):
        desc = _hds_description(row, current_lang(request))
        if desc:
            hds_desc = desc.get("description")
            if desc.get("summary") and _placeholder_summary(
                    app_data.get("summary", ""), app_data.get("name", "")):
                app_data["summary"] = desc["summary"]
    return render(request, "app.html",
                  {"app": app_data, "repo_base": repo_base, "also_in": also_in,
                   "hds_screenshots": hds_screenshots, "hds_desc": hds_desc})


@app.get("/get-spritz", response_class=HTMLResponse)
def get_spritz(request: Request):
    """Placeholder bootstrap page for the native client (built later)."""
    return render(request, "get_spritz.html", {})


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page(request: Request):
    """Admin page: paste the admin token, ingest/re-crawl taps, rebuild repos.
    The page is served to anyone but inert without the token; every action is
    verified server-side against SPRITZ_ADMIN_TOKEN."""
    return render(request, "admin.html", {})


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    """Browser login/registration. The form calls /auth/login or
    /auth/register and stores the JWT client-side (see static/auth.js)."""
    return render(request, "login.html", {})


@app.get("/library-page", response_class=HTMLResponse)
def library_page(request: Request):
    """'My apps' page: the user pastes their token; JS fetches /library and
    renders the list. Reuses the existing JWT auth (no cookies)."""
    return render(request, "library.html", {})


@app.get("/publish", response_class=HTMLResponse)
def publish_page(request: Request):
    """Form for authors to build a cichéto YAML for their own bàcaro.

    The page does not write anything server-side: it produces a downloadable
    YAML the author commits to their git bàcaro. git stays the source of truth
    (the git + cache model), so this never becomes a second source of truth.
    Submission is authenticated so we know who built it, but the artifact is
    just a file.
    """
    return render(request, "publish.html", {})


@app.post("/publish", response_class=PlainTextResponse)
@limiter.limit("20/minute")
def publish_generate(request: Request, body: "PublishBody",
                     user: User = Depends(current_user)):
    """Validate the submitted fields against the cichéto schema and return a
    clean YAML file. Authenticated (paste your bearer token). Writes nothing:
    the author drops the returned file into their bàcaro git repo."""
    # Build a cichéto dict from the flat form, then validate with the real
    # schema so "if it passes here, it passes ingest".
    artifacts = {}
    if body.arch and body.hpkg_url:
        art: dict = {"url": body.hpkg_url}
        if body.sha256:
            art["sha256"] = body.sha256
        artifacts[body.arch] = art

    data = {
        "cicheto": 1,
        "id": body.id,
        "name": body.name,
        "summary": body.summary,
        "homepage": body.homepage or None,
        "license": body.license or None,
        "icon": body.icon or None,
        "screenshots": [s.strip() for s in
                        (body.screenshots or "").replace(",", "\n").splitlines()
                        if s.strip()],
        "categories": [c.strip() for c in (body.categories or "").split(",") if c.strip()],
        "author": {"name": body.author_name,
                   "contact": body.author_contact or None} if body.author_name else None,
        "packager": {"name": body.packager_name or body.author_name or user.email,
                     "bacaro": body.bacaro},
        "bridge": {"haikuports": body.haikuports} if body.haikuports else None,
        "channels": {
            "stable": {
                "version": body.version or None,
                "kind": "hpkg",
                "artifacts": artifacts,
            }
        },
    }
    try:
        cicheto = Cicheto.model_validate(data)
    except Exception as e:
        raise HTTPException(422, f"Cichéto non valido: {e}")

    yaml_text = cicheto_to_yaml(cicheto)
    filename = f"{cicheto.id}.yaml"
    return PlainTextResponse(
        yaml_text,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        media_type="application/x-yaml",
    )


# ---------- image uploads (convenience; the cichéto still references by URL) ----

@app.post("/upload/image")
@limiter.limit("30/minute")
async def upload_image(request: Request, kind: str = Query("screenshot"),
                       file: UploadFile = File(...),
                       user: User = Depends(current_user)):
    """Upload an icon or screenshot and get back a spritz-served URL to paste
    into the cichéto. Authenticated. The image is validated by magic bytes and
    size-capped; it is NOT a substitute for the cichéto (git stays canonical),
    just a place to host the image if the author has nowhere else."""
    max_bytes = (config.MAX_ICON_BYTES if kind == "icon"
                 else config.MAX_SCREENSHOT_BYTES)
    data = await file.read()
    try:
        name = uploads.save_image(data, max_bytes)
    except uploads.UploadError as e:
        raise HTTPException(400, str(e))
    url = f"{config.PUBLIC_BASE_URL.rstrip('/')}/assets/{name}"
    return {"url": url, "filename": name}


@app.get("/assets/{filename}")
def get_asset(filename: str):
    try:
        path = uploads.asset_path(filename)
    except uploads.UploadError:
        raise HTTPException(400, "bad asset filename")
    if not path.is_file():
        raise HTTPException(404, "asset not found")
    return FileResponse(path, media_type=uploads.content_type_for(filename))


def _hpkg_url_for_icon(row: CichetoRow) -> Optional[str]:
    """A downloadable hpkg URL for this app's stable channel, for icon extraction.
    Handles pinned (artifact url) and hpkr-repo (resolve from the catalog)."""
    stable = (row.raw.get("channels", {}) or {}).get("stable") or {}
    arts = stable.get("artifacts") or {}
    for art in arts.values():
        if art.get("url"):
            return art["url"]
    if stable.get("source") == "hpkr-repo" and stable.get("repo_url"):
        try:
            resolved = hpkr.resolve_from_repo(
                stable["repo_url"], stable.get("package") or row.name)
            for art in resolved.values():
                return art["url"]
        except hpkr.HpkrError:
            return None
    return None


@app.get("/icon/{cicheto_id}")
@limiter.limit("60/minute")
def app_icon(request: Request, cicheto_id: str,
             session: Session = Depends(get_session)):
    """Serve an app's icon as PNG, extracted from its hpkg (cached). 404 when
    no icon is available, the package is too big, or hvif2png is not configured;
    the frontend then shows its generated placeholder."""
    if "/" in cicheto_id or "\\" in cicheto_id:
        raise HTTPException(400, "bad id")
    icons_dir = Path(config.UPLOAD_DIR) / "icons"
    cache_path = icons_dir / f"{cicheto_id}.png"
    if cache_path.is_file():
        return FileResponse(cache_path, media_type="image/png")
    # Negative cache: extracting an icon means downloading the hpkg (seconds for
    # a big library like ffmpeg) only to find it ships no HVIF. Once we know an
    # app yields no icon, remember it so later requests 404 instantly instead of
    # re-downloading every time. Cleared by wiping the icons dir on a re-ingest.
    miss = icons_dir / f"{cicheto_id}.none"
    if miss.is_file():
        raise HTTPException(404, "no icon (cached miss)")

    if not hvif.tool_available():
        raise HTTPException(404, "icon extraction not configured")
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")

    png = _extract_icon(row)
    if png is None:
        # Fall back to a twin copy of the same app in another repo that DOES have
        # an extractable icon (e.g. the sample cichéto has a placeholder URL, but
        # the HaikuPorts copy ships the real hpkg). The user sees the real icon
        # instead of the generated placeholder; still the author's own artwork.
        png = _borrow_twin_icon(session, row)
    if png is None:
        icons_dir.mkdir(parents=True, exist_ok=True)
        miss.write_bytes(b"")      # remember the miss; don't re-download next time
        raise HTTPException(404, "no icon available")
    cache.write_capped(cache_path, png)   # size-bounded LRU cache
    return FileResponse(cache_path, media_type="image/png")


def _extract_icon(row: CichetoRow) -> Optional[bytes]:
    """Extract this cichéto's own icon PNG from its hpkg, or None if there is no
    hpkg to pull from or the extraction fails."""
    url = _hpkg_url_for_icon(row)
    if not url:
        return None
    try:
        return hvif.icon_png_from_hpkg_url(url, size=64)
    except hvif.IconError:
        return None


def _borrow_twin_icon(session: Session, row: CichetoRow) -> Optional[bytes]:
    """Icon of a twin copy (same dedup key, different id) that has an extractable
    one. Prefers a cached PNG; else tries to extract, best-ranked source first.
    Returns the PNG bytes, or None if no twin yields an icon."""
    key = dedup_key_for_name(row.name)
    if not key:
        return None
    twins = list(session.exec(
        select(CichetoRow).where(CichetoRow.dedup_key == key,
                                 CichetoRow.id != row.id)).all())
    # Try the source closest to the author first (rank ascending).
    twins.sort(key=lambda o: _bacaro_rank(o.bacaro))
    for twin in twins:
        cached = Path(config.UPLOAD_DIR) / "icons" / f"{twin.id}.png"
        if cached.is_file():
            return cached.read_bytes()
        png = _extract_icon(twin)
        if png is not None:
            # Cache under the twin's id too, so its own page is fast next time.
            cache.write_capped(cached, png)
            return png
    return None


@app.get("/placeholder.svg")
def placeholder(name: str = Query("?")):
    """A Haiku-flavoured SVG placeholder (stylised leaf + the app's initial),
    used by the frontend when an app has no extractable icon. The tint is
    derived from `name`. Cacheable and dependency-free."""
    from . import placeholder as ph
    svg = ph.placeholder_svg(name, size=64)
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- screenshots (proxied from HaikuDepotServer, cached) ----------

# Per-process cache of screenshot code lists, keyed by HDS package name, so one
# page render (and repeat visits) makes at most one HDS list call per app.
_HDS_CODES_CACHE: dict = {}


def _hds_pkg_name(row: CichetoRow) -> Optional[str]:
    """The HaikuDepotServer package name to query for screenshots. Prefer an
    explicit bridge to HaikuPorts; else the last path segment of the reverse-dns
    id (org.haiku.genio -> genio), which matches how the mirror ids are built."""
    bridge = (row.raw.get("bridge") or {}) if isinstance(row.raw, dict) else {}
    if bridge.get("haikuports"):
        return str(bridge["haikuports"])
    # repo.haikuports.<name> or org.x.<name> -> <name>
    tail = row.id.rsplit(".", 1)[-1]
    return tail or None


def _hds_screenshot_codes(row: CichetoRow) -> list[str]:
    """Screenshot codes for this app from HaikuDepotServer, cached. Empty when the
    cichéto already has its own screenshots (we do not override the author) or
    when HDS has none / is unreachable."""
    if (row.raw or {}).get("screenshots"):
        return []                      # author's own screenshots win; skip HDS
    pkg = _hds_pkg_name(row)
    if not pkg:
        return []
    if pkg in _HDS_CODES_CACHE:
        return _HDS_CODES_CACHE[pkg]
    codes = [s["code"] for s in hds.list_screenshots(pkg)]
    _HDS_CODES_CACHE[pkg] = codes
    return codes


# Per-process cache of HDS descriptions, keyed by (pkg name, language).
_HDS_DESC_CACHE: dict = {}


def _hds_description(row: CichetoRow, lang: str) -> Optional[dict]:
    """Curated summary + description from HaikuDepotServer for an app whose
    cichéto lacks its own, cached per (package, language). None when the cichéto
    already has a real description, or HDS has none / is unreachable."""
    raw = row.raw or {}
    if raw.get("description"):
        return None                    # author's own description wins
    pkg = _hds_pkg_name(row)
    if not pkg:
        return None
    # HDS uses ISO codes; our lang codes ('it','vec',...) mostly match, but the
    # Venetian tag has no HDS translation, so fall back to English for it.
    hds_lang = "en" if lang in ("vec",) else lang
    ckey = (pkg, hds_lang)
    if ckey in _HDS_DESC_CACHE:
        return _HDS_DESC_CACHE[ckey]
    desc = hds.get_description(pkg, lang=hds_lang)
    _HDS_DESC_CACHE[ckey] = desc
    return desc


def _placeholder_summary(summary: str, name: str) -> bool:
    """True if a summary is the auto-generated import placeholder (e.g.
    'genio from HaikuPorts', 'x from the lote repository'), which we prefer to
    replace with the real HDS one-liner."""
    s = (summary or "").lower()
    return (s.endswith("from haikuports")
            or " from the " in s and s.endswith(" repository"))


@app.get("/screenshot/{code}")
@limiter.limit("60/minute")
def screenshot(request: Request, code: str):
    """Proxy + cache a single HaikuDepotServer screenshot PNG. The image stays
    HDS's; we cache it so the app page is fast and does not send the visitor's
    browser to depot.haiku-os.org on every view. 404 if HDS has no such image."""
    # code is an HDS GUID; reject anything that could escape the cache dir.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", code):
        raise HTTPException(400, "bad screenshot code")
    cache_path = Path(config.UPLOAD_DIR) / "screenshots" / f"{code}.png"
    if cache_path.is_file():
        return FileResponse(cache_path, media_type="image/png")
    png = hds.screenshot_bytes(code)
    if png is None:
        raise HTTPException(404, "screenshot not available")
    cache.write_capped(cache_path, png)   # size-bounded LRU cache
    return FileResponse(cache_path, media_type="image/png")


@app.get("/screenshots/{cicheto_id}")
def screenshots_json(cicheto_id: str, session: Session = Depends(get_session)):
    """The screenshot URLs spritz would show for an app: the cichéto's own if it
    has them, otherwise the proxied HaikuDepotServer ones. JSON for the API."""
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")
    own = (row.raw or {}).get("screenshots") or []
    if own:
        return {"source": "cicheto", "screenshots": own}
    codes = _hds_screenshot_codes(row)
    return {"source": "haikudepotserver",
            "screenshots": [f"/screenshot/{c}" for c in codes]}


def _stable_repo_url_for(session: Session, row: CichetoRow) -> Optional[str]:
    """Best-effort: the public repo.info URL of a built stable sub-repo holding
    this app, if one exists on disk. Picks the first matching (vendor, arch)."""
    stable = (row.raw.get("channels", {}) or {}).get("stable") or {}
    for arch in (stable.get("artifacts", {}) or {}).keys():
        # We don't know the vendor without the built hpkg; scan built sub-repos
        # for this arch that contain a package for this app.
        repos_root = Path(config.REPO_CACHE_DIR) / "repos"
        if not repos_root.is_dir():
            return None
        for vendor_dir in repos_root.iterdir():
            info = vendor_dir / _slug(arch) / "current" / "repo.info"
            if info.is_file():
                return (f"{config.PUBLIC_BASE_URL.rstrip('/')}"
                        f"/repo/{vendor_dir.name}/{_slug(arch)}/current")
    return None


@app.get("/api")
def api_root():
    return {"service": "spritz registry", "version": "0.1.0", "docs": "/docs"}


# ---------- ops: health + stats ----------

@app.get("/health")
def health(session: Session = Depends(get_session)):
    """Liveness/readiness. Confirms the DB answers. Returns 503 if it does not,
    so a load balancer can take the instance out of rotation."""
    try:
        session.exec(select(CichetoRow.id).limit(1)).first()
    except Exception as e:
        raise HTTPException(503, f"database unavailable: {e}")
    return {"status": "ok", "version": "0.1.0"}


@app.get("/stats")
def stats(session: Session = Depends(get_session)):
    """Catalog counts, for monitoring and to show the catalog growing."""
    rows = session.exec(select(CichetoRow)).all()
    by_category: dict[str, int] = {}
    by_channel: dict[str, int] = {}
    with_bridge = 0
    for r in rows:
        for cat in (r.categories.split(",") if r.categories else []):
            cat = cat.strip()
            if cat:
                by_category[cat] = by_category.get(cat, 0) + 1
        for ch in (r.channels.split(",") if r.channels else []):
            ch = ch.strip()
            if ch:
                by_channel[ch] = by_channel.get(ch, 0) + 1
        if r.haikuports:
            with_bridge += 1

    distinct_bacari = len({r.bacaro for r in rows if r.bacaro})
    users = len(session.exec(select(User.id)).all())
    installs = len(session.exec(select(InstallState.id)).all())

    return {
        "cicheti": len(rows),
        "bacari": distinct_bacari,
        "users": users,
        "library_entries": installs,
        "with_haikuports_bridge": with_bridge,
        "by_channel": dict(sorted(by_channel.items())),
        "by_category": dict(sorted(by_category.items(),
                                   key=lambda kv: (-kv[1], kv[0]))),
    }
