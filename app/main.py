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

from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlmodel import Session, select

from .auth import current_user, hash_password, make_token, verify_password
from .db import get_session, init_db
from .ingest import ingest_git
from .models import CichetoRow, InstallState, User

app = FastAPI(title="spritz registry", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------- request/response bodies ----------

class RegisterBody(BaseModel):
    email: EmailStr
    password: str


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class QueueBody(BaseModel):
    channel: str = "stable"
    arch: Optional[str] = None


# ---------- auth ----------

@app.post("/auth/register", response_model=TokenOut)
def register(body: RegisterBody, session: Session = Depends(get_session)):
    exists = session.exec(select(User).where(User.email == body.email)).first()
    if exists:
        raise HTTPException(409, "Email already registered")
    user = User(email=body.email, password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    session.refresh(user)
    return TokenOut(access_token=make_token(user))


@app.post("/auth/login", response_model=TokenOut)
def login(body: LoginBody, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email)).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return TokenOut(access_token=make_token(user))


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


@app.post("/ingest")
def ingest(body: IngestBody):
    """Crawl a bàcaro git repo into the cache. (Add auth before exposing.)"""
    try:
        return ingest_git(body.git_url, body.bacaro)
    except Exception as e:
        raise HTTPException(400, f"Ingest failed: {e}")


@app.get("/")
def root():
    return {"service": "spritz registry", "version": "0.1.0", "docs": "/docs"}
