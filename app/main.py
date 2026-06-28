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

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, EmailStr, Field as PField
from sqlmodel import Session, select
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware

from . import config, repo_proxy
from .auth import (MIN_PASSWORD_LENGTH, current_user, hash_password, make_token,
                   verify_password)
from .config import ADMIN_TOKEN, check_prod_config
from .db import get_session, init_db
from .ingest import ingest_git
from .models import CichetoRow, InstallState, User

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

@app.get("/search")
def search(q: str = Query("", description="free-text query"),
           session: Session = Depends(get_session)):
    stmt = select(CichetoRow)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            (CichetoRow.name.like(like))
            | (CichetoRow.summary.like(like))
            | (CichetoRow.categories.like(like))
        )
    rows = session.exec(stmt.limit(50)).all()
    return [
        {"id": r.id, "name": r.name, "summary": r.summary,
         "bacaro": r.bacaro, "channels": r.channels.split(",") if r.channels else [],
         "haikuports": r.haikuports}
        for r in rows
    ]


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
    """What the Haiku daemon calls: id + channel (+ arch) -> install info."""
    row = session.get(CichetoRow, cicheto_id)
    if not row:
        raise HTTPException(404, "Cichéto not found")
    channels = row.raw.get("channels", {})
    ch = channels.get(channel)
    if not ch:
        raise HTTPException(404, f"Channel '{channel}' not available")

    artifacts = ch.get("artifacts", {})
    if arch:
        art = artifacts.get(arch)
        if not art:
            raise HTTPException(404, f"No artifact for arch '{arch}'")
        artifacts = {arch: art}

    return {
        "id": row.id,
        "channel": channel,
        "kind": ch.get("kind", "hpkg"),
        "version": ch.get("version"),
        "artifacts": artifacts,        # arch -> {url, sha256}
        "requires": ch.get("requires", []),
        "bridge": row.raw.get("bridge"),
    }


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
    return [{"cicheto": r.cicheto_id, "channel": r.channel,
             "arch": r.arch, "state": r.state} for r in rows]


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
        out.append({
            "cicheto": r.cicheto_id, "channel": r.channel, "arch": r.arch,
            "kind": ch.get("kind", "hpkg"),
            "artifacts": ch.get("artifacts", {}),
            "requires": ch.get("requires", []),
        })
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


@app.get("/")
def root():
    return {"service": "spritz registry", "version": "0.1.0", "docs": "/docs"}
