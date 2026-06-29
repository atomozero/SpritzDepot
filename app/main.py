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

import secrets
from pathlib import Path
from typing import Optional

from fastapi import (Depends, FastAPI, File, Header, HTTPException, Query,
                     Request, UploadFile, status)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, Field as PField
from sqlmodel import Session, select
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, ombra, repo_proxy, uploads
from .auth import (MIN_PASSWORD_LENGTH, current_user, hash_password, make_token,
                   verify_password)
from .config import ADMIN_TOKEN, check_prod_config
from .db import get_session, init_db
from .ingest import ingest_git, list_bacari
from .models import CichetoRow, InstallState, User
from .schemas import Cicheto, cicheto_to_yaml

# Rate limiter keyed by client IP. In-memory by default; point storage_uri at
# Redis in prod for multi-process correctness.
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="spritz registry", version="0.1.0")
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

# Server-rendered frontend (Jinja). Kept simple for WebPositive (see task 03).
_HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(_HERE / "templates"))
app.mount("/static", StaticFiles(directory=str(_HERE / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    # Refuse to start with insecure config in prod (warns in dev).
    check_prod_config()
    init_db()


# ---------- admin guard ----------

def require_admin(x_admin_token: Optional[str] = Header(default=None)) -> None:
    """Gate admin-only endpoints behind a shared token.

    The token is read from SPRITZ_ADMIN_TOKEN (app.config). If it is unset,
    the endpoint is closed entirely (503) rather than open to anyone. The
    comparison is timing-safe.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Admin endpoint disabled: SPRITZ_ADMIN_TOKEN is not configured",
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or missing admin token",
            headers={"WWW-Authenticate": "X-Admin-Token"},
        )


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
    user = User(email=body.email, password_hash=hash_password(body.password))
    session.add(user)
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

def _search_rows(session: Session, q: str = "", category: str = "",
                 bacaro: str = "") -> list[dict]:
    """Shared search used by both the JSON API and the HTML home. Optional
    exact-match filters by category and bàcaro."""
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
    rows = session.exec(stmt.limit(50)).all()
    return [
        {"id": r.id, "name": r.name, "summary": r.summary,
         "bacaro": r.bacaro, "channels": r.channels.split(",") if r.channels else [],
         "haikuports": r.haikuports,
         "categories": r.categories.split(",") if r.categories else [],
         "icon": (r.raw or {}).get("icon")}
        for r in rows
    ]


@app.get("/search")
def search(q: str = Query("", description="free-text query"),
           category: str = Query(""), bacaro: str = Query(""),
           session: Session = Depends(get_session)):
    return _search_rows(session, q, category, bacaro)


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

@app.get("/resolve/{cicheto_id}")
def resolve(cicheto_id: str,
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
    if ch.get("source") == "github-latest":
        artifacts, version = _resolve_ombra(row.raw, ch, arch, notes)
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
        "artifacts": artifacts,        # arch -> {url[, sha256]}
        "requires": ch.get("requires", []),
        "bridge": row.raw.get("bridge"),
    }
    if notes:
        out["notes"] = notes
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
    existing = session.exec(
        select(InstallState).where(
            InstallState.user_id == user.id,
            InstallState.cicheto_id == cicheto_id,
        )
    ).first()
    if existing:
        existing.state = "pending"
        existing.channel = body.channel
        existing.arch = body.arch
        session.add(existing)
    else:
        session.add(InstallState(
            user_id=user.id, cicheto_id=cicheto_id,
            channel=body.channel, arch=body.arch, state="pending",
        ))
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
            continue
        ch = row.raw.get("channels", {}).get(r.channel, {})
        item = {
            "cicheto": r.cicheto_id, "channel": r.channel, "arch": r.arch,
            "kind": ch.get("kind", "hpkg"),
            "artifacts": ch.get("artifacts", {}),
            "requires": ch.get("requires", []),
        }
        # For an ombra (github-latest) item, resolve the live release URLs here
        # so the daemon gets everything in one poll. Best-effort: a resolve
        # failure (GitHub down, rate limit) leaves the item with empty artifacts
        # and a note, rather than failing the whole poll.
        if ch.get("source") == "github-latest":
            notes: list = []
            try:
                artifacts, version = _resolve_ombra(row.raw, ch, r.arch, notes)
                item["artifacts"] = artifacts
                item["version"] = version
            except HTTPException as e:
                notes.append(f"ombra resolve failed: {e.detail}")
            if notes:
                item["notes"] = notes
        out.append(item)
    return out


@app.post("/library/{cicheto_id}/installed")
def mark_installed(cicheto_id: str,
                   user: User = Depends(current_user),
                   session: Session = Depends(get_session)):
    """Daemon confirms an install landed."""
    row = session.exec(
        select(InstallState).where(
            InstallState.user_id == user.id,
            InstallState.cicheto_id == cicheto_id,
        )
    ).first()
    if not row:
        raise HTTPException(404, "Not in library")
    row.state = "installed"
    session.add(row)
    session.commit()
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
        raise HTTPException(400, f"Ingest failed: {e}")

    if rebuild:
        try:
            result = {**result, "repo": _rebuild_all_repos(session)}
        except repo_proxy.ToolUnavailable:
            result = {**result, "repo": {"skipped": "package_repo not configured"}}
    return result


@app.get("/bacari")
def bacari():
    """Known bàcari (taps) in the cache, with app counts and last ingest."""
    return list_bacari()


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
            dest = cache / f"{cid}-{arch}.hpkg"
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
         bacaro: str = Query(""), session: Session = Depends(get_session)):
    """Catalog home + search, optionally filtered by category or bàcaro."""
    results = _search_rows(session, q, category, bacaro)
    return templates.TemplateResponse(
        request, "home.html",
        {"q": q, "category": category, "bacaro": bacaro, "results": results}
    )


@app.get("/categories", response_class=HTMLResponse, include_in_schema=False)
def categories_page(request: Request, session: Session = Depends(get_session)):
    """Browse-by-category page."""
    cats = _category_counts(session)
    return templates.TemplateResponse(
        request, "categories.html", {"categories": cats}
    )


@app.get("/app/{cicheto_id}", response_class=HTMLResponse)
def app_page(request: Request, cicheto_id: str,
             session: Session = Depends(get_session)):
    """Full cichéto page with the degrading install button."""
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")
    app_data = row.raw
    # If a built stable sub-repo exists, hand the page its public URL so the
    # fallback button can point HaikuDepot at it.
    repo_base = _stable_repo_url_for(session, row)
    return templates.TemplateResponse(
        request, "app.html", {"app": app_data, "repo_base": repo_base}
    )


@app.get("/get-spritz", response_class=HTMLResponse)
def get_spritz(request: Request):
    """Placeholder bootstrap page for the native client (built later)."""
    return templates.TemplateResponse(request, "get_spritz.html", {})


@app.get("/library-page", response_class=HTMLResponse)
def library_page(request: Request):
    """'My apps' page: the user pastes their token; JS fetches /library and
    renders the list. Reuses the existing JWT auth (no cookies)."""
    return templates.TemplateResponse(request, "library.html", {})


@app.get("/publish", response_class=HTMLResponse)
def publish_page(request: Request):
    """Form for authors to build a cichéto YAML for their own bàcaro.

    The page does not write anything server-side: it produces a downloadable
    YAML the author commits to their git bàcaro. git stays the source of truth
    (the git + cache model), so this never becomes a second source of truth.
    Submission is authenticated so we know who built it, but the artifact is
    just a file.
    """
    return templates.TemplateResponse(request, "publish.html", {})


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
