"""ombra channel resolver: follow an author's latest GitHub release.

ombra is the thing a static HPKR repo cannot do by nature (see DECISIONS): it
points at the author's newest release as it lands, instead of a pinned version.

Scope, deliberately narrow (DECISIONS, "ombra never builds packages here"):
  - Only releases that already ship a ready-made .hpkg asset are followed. We
    match assets by filename pattern and hand back their URLs. We never compile
    or package anything; that is build-farm territory, a later leg.
  - sha256 is NOT pre-computed for ombra. The schema and the project line are
    explicit: the native client verifies the hash at download time and logs the
    seen hash. So this resolver returns url + version only, no checksum.

Source of truth stays with the author's GitHub releases; we just resolve URLs.
"""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

GITHUB_API = "https://api.github.com"


class OmbraError(RuntimeError):
    """A github-latest channel that could not be resolved."""


@dataclass
class OmbraResult:
    repo: str
    version: Optional[str]
    # arch -> asset download URL (no sha256: verified by the client at download)
    artifacts: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _gh_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("SPRITZ_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def repo_from_homepage(homepage: Optional[str]) -> Optional[str]:
    """Derive "owner/name" from a github.com homepage URL, if it is one."""
    if not homepage:
        return None
    parsed = urlparse(homepage)
    if "github.com" not in (parsed.netloc or ""):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        name = parts[1]
        if name.endswith(".git"):
            name = name[:-4]
        return f"{parts[0]}/{name}"
    return None


def _pick_release(releases: list, prerelease: bool) -> Optional[dict]:
    """Pick the newest published release. If prerelease is False, skip
    prereleases and drafts. The API returns releases newest-first."""
    for rel in releases:
        if rel.get("draft"):
            continue
        if rel.get("prerelease") and not prerelease:
            continue
        return rel
    return None


def _match_assets(assets: list, pattern: str, arches: list) -> dict:
    """For each arch, find the first asset whose name matches the pattern with
    {arch} substituted. Returns arch -> download URL."""
    out: dict = {}
    for arch in arches:
        glob = pattern.replace("{arch}", arch)
        for asset in assets:
            name = asset.get("name", "")
            if fnmatch.fnmatch(name, glob):
                out[arch] = asset.get("browser_download_url")
                break
    return out


def resolve_github_latest(repo: str, match: str, arches: list,
                          prerelease: bool = False,
                          client: Optional[httpx.Client] = None) -> OmbraResult:
    """Resolve the latest release of `repo` to per-arch asset URLs.

    `match` is the asset filename pattern (with {arch}); `arches` the arches to
    look for. Returns an OmbraResult; raises OmbraError on API/repo problems.
    """
    if not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        raise OmbraError(f"invalid repo '{repo}', expected owner/name")
    if not match:
        raise OmbraError("github-latest channel needs a 'match' pattern")

    own = client or httpx.Client(timeout=20.0, follow_redirects=False)
    try:
        r = own.get(f"{GITHUB_API}/repos/{repo}/releases",
                    headers=_gh_headers(), params={"per_page": 30})
        if r.status_code == 404:
            raise OmbraError(f"repo or releases not found: {repo}")
        if r.status_code == 403 and "rate limit" in r.text.lower():
            raise OmbraError("GitHub rate limit hit; set SPRITZ_GITHUB_TOKEN")
        r.raise_for_status()
        releases = r.json()
    except httpx.HTTPError as e:
        raise OmbraError(f"GitHub API error for {repo}: {e}") from e
    finally:
        if client is None:
            own.close()

    if not isinstance(releases, list) or not releases:
        raise OmbraError(f"no releases for {repo}")

    rel = _pick_release(releases, prerelease)
    if rel is None:
        raise OmbraError(
            f"no suitable release for {repo} (prerelease={prerelease})")

    version = rel.get("tag_name") or rel.get("name") or ""
    # Tags often carry a leading "v" (v1.2.0); strip it so the UI, which
    # prefixes "v" itself, does not show "vv1.2.0".
    if version[:1] in ("v", "V") and version[1:2].isdigit():
        version = version[1:]
    artifacts = _match_assets(rel.get("assets", []), match, arches)
    result = OmbraResult(repo=repo, version=version, artifacts=artifacts)
    if not artifacts:
        result.notes.append(
            f"release {version} has no asset matching '{match}' for {arches}")
    return result
