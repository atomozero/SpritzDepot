"""Cichéto schema: the manifest format.

This is the contract a bàcaro (a git repo of YAML files) must satisfy.
The server parses each .yaml/.yml against these models; anything that
fails validation is rejected at ingest time, so the cache only ever
holds well-formed cichéti.

Deliberately NOT in here: trust tier and commercial fields (price,
licence endpoint). Those are assertions of the index, signed by spritz,
never editable inside the bàcaro repo. See the design notes.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class Kind(str, Enum):
    hpkg = "hpkg"   # native package, mounted by packagefs
    zip = "zip"     # unpacked into ~/config/non-packaged (the "cask" case)


class Author(BaseModel):
    """Who writes the software."""
    name: str
    contact: Optional[str] = None

    @field_validator("contact")
    @classmethod
    def _safe_contact(cls, v: Optional[str]) -> Optional[str]:
        """contact is shown as a clickable link, so only allow safe schemes
        (https/http/mailto). Reject javascript:, data:, etc. to prevent a
        malicious cichéto from injecting a script URL into an href."""
        if v is None:
            return v
        v = v.strip()
        low = v.lower()
        if low.startswith(("https://", "http://", "mailto:")):
            return v
        raise ValueError("contact must be an http(s) or mailto: URL")


class Packager(BaseModel):
    """Who maintains THIS cichéto. May differ from the author in 3rd-party bàcari."""
    name: str
    bacaro: str  # slug of the originating tap, e.g. "vepro"


class Bridge(BaseModel):
    """The anti-fragmentation field: declares the app also lives in HaikuPorts."""
    haikuports: Optional[str] = None        # package name there, if any
    prefer: Optional[str] = None            # hint: "stable" -> use the curated channel


class Artifact(BaseModel):
    """A single downloadable file for one architecture."""
    url: HttpUrl
    sha256: Optional[str] = None  # required for pinned channels, omitted for github-latest


class Channel(BaseModel):
    """A release stream: stable (pinned) or ombra (nightly), etc."""
    version: Optional[str] = None
    kind: Kind = Kind.hpkg
    # arch -> artifact. Keys like "x86_64", "x86_gcc2h".
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    # advisory pre-flight hints; real requires live inside the hpkg.
    requires: list[str] = Field(default_factory=list)
    # for auto-following channels:
    source: Optional[str] = None    # "github-latest" | "hpkr-repo" | "haikuports"
    repo: Optional[str] = None       # github "owner/name" (derived from homepage if absent)
    match: Optional[str] = None      # asset pattern, e.g. "genio-*-{arch}.hpkg"
    prerelease: bool = False
    # for source: hpkr-repo (a third-party Haiku repository, NOT HaikuPorts):
    repo_url: Optional[str] = None   # base URL serving repo.info, repo, packages/
    package: Optional[str] = None    # package name as it appears in that catalog


# The id is a reverse-domain string used BOTH as a DB primary key AND
# interpolated into cache filenames (e.g. f"{id}-{arch}.hpkg"). It must be
# strictly validated so a malicious bàcaro cannot smuggle path traversal
# (id: "../../etc/...") into an arbitrary file write, and cannot inject anything
# odd into the DB. Character set: lowercase alnum plus + . _ - (the '+' appears
# in real Haiku package names like libsigc++), at least two dot-joined labels.
# Path separators and '..' are excluded both by the charset and the explicit
# check in the validator below. A label cannot start/end with a separator.
_ID_RE = __import__("re").compile(
    r"^[a-z0-9+]+([._-][a-z0-9+]+)*\.[a-z0-9+]+([._-][a-z0-9+]+)*$")


class Cicheto(BaseModel):
    """The full manifest."""
    cicheto: int = 1                 # schema version
    id: str = Field(min_length=3, max_length=128)   # reverse-domain, e.g. org.haiku.genio
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=2000)
    # Long description (multiple paragraphs, blank-line separated). Shown on the
    # app page; the summary is the one-liner. Plain text, rendered escaped.
    description: str = Field(default="", max_length=20000)
    homepage: Optional[HttpUrl] = None
    license: Optional[str] = Field(default=None, max_length=200)
    categories: list[str] = Field(default_factory=list, max_length=64)
    icon: Optional[HttpUrl] = None
    # URL to a raw HVIF icon blob (the Haiku vector format, 'ncif' magic). spritz
    # serves it via /hvif/{id} and the frontend renders it to SVG client-side, so
    # an app that ships an .hvif (but no extractable hpkg icon, e.g. zip releases)
    # can still show its real vector icon. Takes precedence over hpkg extraction.
    hvif_url: Optional[HttpUrl] = None
    screenshots: list[HttpUrl] = Field(default_factory=list, max_length=32)

    author: Optional[Author] = None
    packager: Optional[Packager] = None
    bridge: Optional[Bridge] = None

    # At least one channel, keyed by channel name. min_length enforces it
    # (a cichéto with no channels is meaningless: nothing to install).
    channels: dict[str, Channel] = Field(min_length=1, max_length=32)

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("id")
    @classmethod
    def _safe_id(cls, v: str) -> str:
        if not _ID_RE.match(v):
            raise ValueError(
                "id must be a reverse-domain string (lowercase alnum labels "
                "joined by dots, e.g. org.haiku.genio); no path characters")
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("id must not contain path separators or '..'")
        return v


def cicheto_to_yaml(c: "Cicheto") -> str:
    """Serialize a validated cichéto to a clean YAML file, ready to drop into a
    bàcaro. Drops empty/false defaults so the file shows only what was set, and
    keeps a stable, human-readable key order."""
    data = c.model_dump(mode="json", exclude_none=True)

    # Strip empty collections/strings and the prerelease=false default for a tidy
    # file (only what was actually set shows up).
    def prune(obj):
        if isinstance(obj, dict):
            return {k: prune(v) for k, v in obj.items()
                    if not (v == [] or v == {} or v == ""
                            or (k == "prerelease" and v is False))}
        if isinstance(obj, list):
            return [prune(v) for v in obj]
        return obj

    data = prune(data)

    # Preferred top-level order; anything else trails in its existing order.
    order = ["cicheto", "id", "name", "summary", "description", "homepage",
             "license", "categories", "icon", "screenshots", "author",
             "packager", "bridge", "channels"]
    ordered = {k: data[k] for k in order if k in data}
    ordered.update({k: v for k, v in data.items() if k not in ordered})

    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True)
