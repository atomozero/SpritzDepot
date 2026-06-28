"""Ingest a bàcaro into the cache.

A bàcaro is a git repo (or a local directory for testing) containing
*.yaml / *.yml cichéto files. This module clones/pulls it, validates
every file against the Cicheto schema, and upserts the valid ones into
the DB cache. Invalid files are reported and skipped — the cache never
holds malformed manifests.

Source of truth = the git repo. The DB = a rebuildable projection.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import yaml
from pydantic import ValidationError
from sqlmodel import Session

from . import config
from .db import engine
from .models import CichetoRow
from .schemas import Cicheto

# Caps so a malicious bàcaro cannot hang the clone or fill the disk.
CLONE_TIMEOUT_SECONDS = 60
MAX_REPO_BYTES = 50 * 1024 * 1024   # 50 MB of cichéti is already absurd
MAX_FILE_COUNT = 5000


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
        # A bare path (no scheme) or file:// — local. Dev only.
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
    Raises IngestError on timeout or if the cloned tree exceeds the caps."""
    _validate_git_url(git_url)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", git_url, str(dest)],
            check=True, capture_output=True, text=True,
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise IngestError(f"clone timed out after {CLONE_TIMEOUT_SECONDS}s")

    size, count = _dir_size_and_count(dest)
    if size > MAX_REPO_BYTES:
        raise IngestError(f"bàcaro too large ({size} bytes > {MAX_REPO_BYTES})")
    if count > MAX_FILE_COUNT:
        raise IngestError(f"bàcaro has too many files ({count} > {MAX_FILE_COUNT})")
    return dest


def _parse_file(path: Path) -> Cicheto:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Cicheto.model_validate(data)


def ingest_directory(root: Path, bacaro_slug: str) -> dict:
    """Walk a directory of cichéti and upsert them. Returns a small report."""
    ok, failed = [], []
    files = list(root.rglob("*.yaml")) + list(root.rglob("*.yml"))

    with Session(engine) as session:
        for f in files:
            try:
                c = _parse_file(f)
            except (ValidationError, yaml.YAMLError) as e:
                failed.append({"file": str(f.name), "error": str(e)[:200]})
                continue

            row = CichetoRow(
                id=c.id,
                name=c.name,
                summary=c.summary,
                bacaro=(c.packager.bacaro if c.packager else bacaro_slug),
                categories=",".join(c.categories),
                haikuports=(c.bridge.haikuports if c.bridge else None),
                channels=",".join(c.channels.keys()),
                raw=c.model_dump(mode="json"),
            )
            session.merge(row)  # upsert by primary key
            ok.append(c.id)
        session.commit()

    return {"bacaro": bacaro_slug, "ingested": ok, "failed": failed}


def ingest_git(git_url: str, bacaro_slug: str) -> dict:
    """Clone a remote bàcaro and ingest it."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = _clone_or_pull(git_url, Path(tmp) / "bacaro")
        return ingest_directory(repo, bacaro_slug)
