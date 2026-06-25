"""Ingest a bàcaro into the cache.

A bàcaro is a git repo (or a local directory for testing) containing
*.yaml / *.yml cichéto files. This module clones/pulls it, validates
every file against the Cicheto schema, and upserts the valid ones into
the DB cache. Invalid files are reported and skipped — the cache never
holds malformed manifests.

Source of truth = the git repo. The DB = a rebuildable projection.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError
from sqlmodel import Session

from .db import engine
from .models import CichetoRow
from .schemas import Cicheto


def _clone_or_pull(git_url: str, dest: Path) -> Path:
    """Shallow-clone a bàcaro repo into dest. Returns the repo path."""
    subprocess.run(
        ["git", "clone", "--depth", "1", git_url, str(dest)],
        check=True, capture_output=True, text=True,
    )
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
