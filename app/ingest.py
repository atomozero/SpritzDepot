"""Ingest a bàcaro into the cache.

A bàcaro is a git repo (or a local directory for testing) containing
*.yaml / *.yml cichéto files. This module clones/pulls it, validates
every file against the Cicheto schema, and upserts the valid ones into
the DB cache. Invalid files are reported and skipped, so the cache never
holds malformed manifests.

Source of truth = the git repo. The DB = a rebuildable projection.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import ValidationError
from sqlmodel import Session, select

from . import config
from .db import engine
from .models import CichetoRow, dedup_key_for_name
from .schemas import Cicheto

# Per-bàcaro ingest lock. Two concurrent crawls of the same slug (retry, double
# click, two admins) each compute their prune set from a stale read, so one
# commit can delete rows the other just inserted - the projection silently loses
# apps. Serializing per slug makes ingest single-flight per tap. In-process only
# (single-worker); a multi-worker prod deploy would need an advisory DB lock.
_ingest_locks: dict = defaultdict(threading.Lock)
_ingest_locks_guard = threading.Lock()


def _slug_lock(slug: str) -> threading.Lock:
    with _ingest_locks_guard:
        return _ingest_locks[slug]

# Caps so a malicious bàcaro cannot hang the clone or fill the disk.
CLONE_TIMEOUT_SECONDS = 60
MAX_REPO_BYTES = 50 * 1024 * 1024   # 50 MB of cichéti is already absurd
MAX_FILE_COUNT = 5000
# A single cichéto is a small YAML file. Cap per-file bytes BEFORE parsing so a
# tiny-on-disk alias bomb (YAML anchors/aliases expand at parse time, so the
# 50 MB repo cap doesn't catch it) can't OOM the ingest worker. 256 KB is plenty
# for any real manifest.
MAX_YAML_BYTES = 256 * 1024


class IngestError(ValueError):
    """A bàcaro that is rejected before/while cloning (bad URL, too big)."""


def _validate_git_url(git_url: str) -> None:
    """Reject dangerous git sources. https is always allowed; local paths and
    file:// are allowed only in dev (tests and local bàcari use them). No
    ssh/git/ftp to arbitrary hosts, ever."""
    parsed = urlparse(git_url)
    scheme = parsed.scheme.lower()

    if scheme == "https":
        return
    if scheme in ("", "file"):
        # A bare path (no scheme) or file:// (local). Dev only.
        if config.IS_PROD:
            raise IngestError("local/file bàcaro URLs are not allowed in prod")
        return
    raise IngestError(f"unsupported git URL scheme '{scheme or '?'}'; use https")


def _dir_size_and_count(path: Path) -> tuple[int, int]:
    total, count = 0, 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            count += 1
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total, count


def _clone_or_pull(git_url: str, dest: Path) -> Path:
    """Shallow-clone a bàcaro repo into dest, with a timeout. Returns the path.
    Raises IngestError on timeout, if the clone is incomplete, or if the cloned
    tree exceeds the caps."""
    _validate_git_url(git_url)
    # Hardened clone of an untrusted URL:
    #  -c core.symlinks=false     write symlinks as plain files (no path escape)
    #  --no-recurse-submodules    don't fetch attacker-declared submodules
    #  --                         stop option parsing so a URL like
    #                             "--upload-pack=..." can't inject a git flag
    # In prod, _validate_git_url already forces https, so also forbid the file://
    # transport for defense in depth. In dev, local file paths are a legitimate
    # test/dev case, so we leave the file transport enabled there.
    cmd = ["git", "-c", "core.symlinks=false"]
    if config.IS_PROD:
        cmd += ["-c", "protocol.file.allow=never"]
    cmd += ["clone", "--depth", "1", "--no-recurse-submodules", "--", git_url,
            str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True,
                       timeout=CLONE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise IngestError(f"clone timed out after {CLONE_TIMEOUT_SECONDS}s")
    except subprocess.CalledProcessError as e:
        raise IngestError(f"clone failed: {(e.stderr or e.stdout or '').strip()[:200]}")

    # Verify the clone actually completed: a partial/degraded checkout would make
    # the file list a subset of the real repo, and a destructive prune would then
    # delete every app whose id isn't in that subset. rev-parse HEAD succeeds only
    # on a complete clone with a checked-out commit.
    try:
        head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                              check=True, capture_output=True, text=True,
                              timeout=30)
        if not head.stdout.strip():
            raise IngestError("clone incomplete: no HEAD commit")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise IngestError("clone incomplete: could not resolve HEAD")

    size, count = _dir_size_and_count(dest)
    if size > MAX_REPO_BYTES:
        raise IngestError(f"bàcaro too large ({size} bytes > {MAX_REPO_BYTES})")
    if count > MAX_FILE_COUNT:
        raise IngestError(f"bàcaro has too many files ({count} > {MAX_FILE_COUNT})")
    return dest


class _NoAliasLoader(yaml.SafeLoader):
    """SafeLoader that refuses YAML aliases. safe_load blocks arbitrary object
    construction but still expands anchors/aliases, which is the billion-laughs
    amplification vector. A cichéto never needs aliases, so we reject them at
    compose time (an '*ref' raises instead of expanding)."""
    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise yaml.YAMLError("YAML aliases are not allowed in a cichéto")
        return super().compose_node(parent, index)


def _parse_file(path: Path) -> Cicheto:
    # Cap bytes before parsing: an alias bomb is tiny on disk but explodes at
    # parse time, so the repo-level size cap doesn't help.
    raw = path.read_bytes()
    if len(raw) > MAX_YAML_BYTES:
        raise IngestError(f"cichéto file too large ({len(raw)} > {MAX_YAML_BYTES} bytes)")
    data = yaml.load(raw.decode("utf-8"), Loader=_NoAliasLoader)
    return Cicheto.model_validate(data)


def ingest_directory(root: Path, bacaro_slug: str, prune: bool = True) -> dict:
    """Serialized entry point: hold the per-slug lock so two crawls of the same
    bàcaro can't race the prune. See _ingest_directory_locked for the work."""
    with _slug_lock(bacaro_slug):
        return _ingest_directory_locked(root, bacaro_slug, prune)


def _ingest_directory_locked(root: Path, bacaro_slug: str, prune: bool = True) -> dict:
    """Walk a directory of cichéti and upsert them, attributing them to
    `bacaro_slug`. With prune=True (default) also drop cichéti previously
    attributed to this bàcaro that did not appear this time, so the cache stays
    a faithful projection of the bàcaro (the git is the source of truth).

    Returns a small report: ingested, failed, removed.

    Note: rows are attributed to `bacaro_slug` (the crawl's tap), NOT to the
    cichéto's self-declared packager.bacaro. A cichéto cannot claim another
    tap's slug and so cannot cause another tap's rows to be pruned or hijacked.
    """
    ok, failed = [], []
    # Skip symlinks: a bàcaro could ship a symlink (e.g. evil.yaml -> /etc/passwd)
    # whose target lies outside the clone; reading it would pull host file content
    # into the parse/error path. Only ingest regular files.
    files = [f for f in (list(root.rglob("*.yaml")) + list(root.rglob("*.yml")))
             if not f.is_symlink() and f.is_file()]

    with Session(engine) as session:
        for f in files:
            try:
                c = _parse_file(f)
            except (ValidationError, yaml.YAMLError) as e:
                failed.append({"file": str(f.name), "error": str(e)[:200]})
                continue
            except Exception as e:  # noqa: BLE001 - one bad file must not abort the crawl
                # A non-UTF-8 file, a YAML alias bomb (MemoryError), deep nesting
                # (RecursionError), a broken symlink (OSError): skip it, don't let
                # a single crafted manifest deny service to every valid one.
                failed.append({"file": str(f.name), "error": f"{type(e).__name__}: {e}"[:200]})
                continue

            # Anti-hijack: the cache is keyed by id (primary key), so a merge from
            # bàcaro B with an id already owned by bàcaro A would overwrite A's
            # row (name, channels, download URLs) - a supply-chain takeover of a
            # known app. Refuse to cross bàcaro boundaries; the owner keeps its id.
            existing = session.get(CichetoRow, c.id)
            if existing is not None and existing.bacaro not in ("", bacaro_slug):
                failed.append({"file": str(f.name),
                               "error": f"id '{c.id}' already owned by bàcaro "
                                        f"'{existing.bacaro}'"})
                continue

            row = CichetoRow(
                id=c.id,
                name=c.name,
                dedup_key=dedup_key_for_name(c.name),
                summary=c.summary,
                bacaro=bacaro_slug,
                categories=",".join(c.categories),
                haikuports=(c.bridge.haikuports if c.bridge else None),
                channels=",".join(c.channels.keys()),
                raw=c.model_dump(mode="json"),
            )
            session.merge(row)  # upsert by primary key (same bàcaro only, per check above)
            ok.append(c.id)

        removed = []
        if prune:
            seen = set(ok)
            stale = session.exec(
                select(CichetoRow).where(CichetoRow.bacaro == bacaro_slug)
            ).all()
            for r in stale:
                if r.id not in seen:
                    session.delete(r)
                    removed.append(r.id)

        session.commit()

    return {"bacaro": bacaro_slug, "ingested": ok,
            "failed": failed, "removed": removed}


def list_bacari() -> list[dict]:
    """Known bàcari in the cache, with app counts and the most recent ingest
    time. A small projection over CichetoRow.bacaro."""
    with Session(engine) as session:
        rows = session.exec(select(CichetoRow)).all()
    agg: dict[str, dict] = {}
    for r in rows:
        b = r.bacaro or "(unknown)"
        a = agg.setdefault(b, {"bacaro": b, "count": 0, "last_ingest": None})
        a["count"] += 1
        ts = r.ingested_at.isoformat() if r.ingested_at else None
        if ts and (a["last_ingest"] is None or ts > a["last_ingest"]):
            a["last_ingest"] = ts
    return sorted(agg.values(), key=lambda d: d["bacaro"])


def ingest_git(git_url: str, bacaro_slug: str) -> dict:
    """Clone a remote bàcaro and ingest it."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _clone_or_pull(git_url, Path(tmp) / "bacaro")
        return ingest_directory(repo, bacaro_slug)
