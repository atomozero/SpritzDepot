"""Prefetch + cache the resolution of ombra (github-latest) channels.

ombra points at an author's newest GitHub release, so resolving it live means an
API call per /resolve, /library/pending and app-page view (slow; 60 req/h without
a token). This module resolves each ombra app once and persists the result in the
OmbraSnapshot table, so the read paths serve from the DB and only fall back to a
live resolve (refreshing the snapshot) when it is missing or stale.

Read model (chosen): snapshot-first, live-fallback. A fresh snapshot is served as
is; a missing/stale one triggers a live resolve that also writes the snapshot, so
correctness never depends on the crawler having run.

Everything here is best-effort and defensive: any GitHub failure is caught,
recorded on the snapshot's `error`, and never raised to the read path.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import httpx
from sqlmodel import Session, select

from . import ombra
from .models import CichetoRow, OmbraSnapshot

# How long a snapshot is considered fresh by the read paths. Longer than the
# in-process caches: an ombra 'latest' moving is rare, and a slightly stale badge
# or resolve is harmless (the client verifies the hash at download regardless).
DEFAULT_TTL = timedelta(hours=6)


@dataclass
class OmbraConfig:
    """The ombra channel config extracted from a cichéto, or None if the app has
    no resolvable ombra channel."""
    repo: str
    match: str
    prerelease: bool
    arches: list


def ombra_config(raw: dict) -> Optional[OmbraConfig]:
    """Pull the ombra channel config out of a cichéto's raw manifest. Returns
    None when there is no ombra channel, or it lacks a repo/match to resolve."""
    channels = (raw or {}).get("channels") or {}
    ch = channels.get("ombra") if isinstance(channels, dict) else None
    if not isinstance(ch, dict):
        return None
    repo = ch.get("repo") or ombra.repo_from_homepage((raw or {}).get("homepage"))
    match = ch.get("match")
    if not repo or not match:
        return None
    arches = list((ch.get("artifacts") or {}).keys()) or ["x86_64"]
    return OmbraConfig(repo=repo, match=match,
                       prerelease=bool(ch.get("prerelease", False)),
                       arches=arches)


def resolve_and_snapshot(session: Session, cicheto_id: str, raw: dict,
                         client: Optional[httpx.Client] = None) -> OmbraSnapshot:
    """Resolve one app's ombra channel live and upsert its snapshot. Never
    raises: a failure is stored on the snapshot's `error` with a null version, so
    the read path can decide to fall through to the stale/None result."""
    cfg = ombra_config(raw)
    snap = session.get(OmbraSnapshot, cicheto_id) or OmbraSnapshot(cicheto_id=cicheto_id)
    if cfg is None:
        # Not an ombra app (or unresolvable config): record and move on.
        snap.repo = ""
        snap.match = ""
        snap.version = None
        snap.artifacts = {}
        snap.error = "no resolvable ombra channel"
        snap.resolved_at = datetime.utcnow()
        session.add(snap)
        return snap

    snap.repo, snap.match, snap.prerelease = cfg.repo, cfg.match, cfg.prerelease
    try:
        res = ombra.resolve_github_latest(cfg.repo, cfg.match, cfg.arches,
                                          prerelease=cfg.prerelease, client=client)
        snap.version = res.version or None
        snap.artifacts = {a: {"url": url} for a, url in res.artifacts.items()}
        # A resolve that found the tag but no matching asset is a soft error: keep
        # the version (useful for the badge) but flag it so the admin sees it.
        snap.error = "; ".join(res.notes) if res.notes else None
    except Exception as e:  # OmbraError, httpx errors, anything: stay defensive
        snap.version = snap.version  # keep any previous version rather than wipe
        snap.error = str(e)
    snap.resolved_at = datetime.utcnow()
    session.add(snap)
    return snap


def read_snapshot(session: Session, cicheto_id: str, raw: dict,
                  ttl: timedelta = DEFAULT_TTL) -> Optional[OmbraSnapshot]:
    """Return a FRESH snapshot for this app, or None if it is missing, stale, or
    built from a different channel config than the app now declares (a re-ingest
    changed repo/match/prerelease). None means 'the caller should resolve live'.
    """
    snap = session.get(OmbraSnapshot, cicheto_id)
    if snap is None:
        return None
    cfg = ombra_config(raw)
    if cfg is None:
        return None
    # Config drift: the snapshot is for an outdated channel definition.
    if (snap.repo, snap.match, snap.prerelease) != (cfg.repo, cfg.match, cfg.prerelease):
        return None
    if datetime.utcnow() - snap.resolved_at > ttl:
        return None
    return snap


@dataclass
class CrawlResult:
    total: int = 0        # ombra apps seen
    resolved: int = 0     # resolved with at least a version
    errors: int = 0       # resolves that recorded an error


def iter_ombra_rows(session: Session):
    """Yield (id, raw) for every catalog app that declares an ombra channel.
    A cheap LIKE on the channels column narrows it before the JSON check."""
    rows = session.exec(
        select(CichetoRow).where(CichetoRow.channels.contains("ombra"))).all()
    for row in rows:
        if ombra_config(row.raw) is not None:
            yield row.id, row.raw


def crawl_ombra(session: Session,
                client: Optional[httpx.Client] = None) -> CrawlResult:
    """Resolve and snapshot every ombra app in the catalog. Commits once at the
    end. Returns a CrawlResult tally. Reuses a single HTTP client across apps."""
    own = client or httpx.Client(timeout=20.0, follow_redirects=True)
    result = CrawlResult()
    try:
        for cicheto_id, raw in iter_ombra_rows(session):
            result.total += 1
            snap = resolve_and_snapshot(session, cicheto_id, raw, client=own)
            if snap.error:
                result.errors += 1
            if snap.version:
                result.resolved += 1
        session.commit()
    finally:
        if client is None:
            own.close()
    return result
