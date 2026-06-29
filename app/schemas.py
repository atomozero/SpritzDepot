"""Cichéto schema — the manifest format.

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
from pydantic import BaseModel, Field, HttpUrl


class Kind(str, Enum):
    hpkg = "hpkg"   # native package, mounted by packagefs
    zip = "zip"     # unpacked into ~/config/non-packaged (the "cask" case)


class Author(BaseModel):
    """Who writes the software."""
    name: str
    contact: Optional[str] = None


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
    source: Optional[str] = None    # e.g. "github-latest"
    match: Optional[str] = None      # asset pattern, e.g. "genio-*-{arch}.hpkg"
    prerelease: bool = False


class Cicheto(BaseModel):
    """The full manifest."""
    cicheto: int = 1                 # schema version
    id: str                          # reverse-domain, unique key, e.g. org.haiku.genio
    name: str
    summary: str
    homepage: Optional[HttpUrl] = None
    license: Optional[str] = None
    categories: list[str] = Field(default_factory=list)
    icon: Optional[HttpUrl] = None
    screenshots: list[HttpUrl] = Field(default_factory=list)

    author: Optional[Author] = None
    packager: Optional[Packager] = None
    bridge: Optional[Bridge] = None

    channels: dict[str, Channel]     # at least one, keyed by channel name

    class Config:
        use_enum_values = True


def cicheto_to_yaml(c: "Cicheto") -> str:
    """Serialize a validated cichéto to a clean YAML file, ready to drop into a
    bàcaro. Drops empty/false defaults so the file shows only what was set, and
    keeps a stable, human-readable key order."""
    data = c.model_dump(mode="json", exclude_none=True)

    # Strip empty collections and the prerelease=false default for a tidy file.
    def prune(obj):
        if isinstance(obj, dict):
            return {k: prune(v) for k, v in obj.items()
                    if not (v == [] or v == {} or (k == "prerelease" and v is False))}
        if isinstance(obj, list):
            return [prune(v) for v in obj]
        return obj

    data = prune(data)

    # Preferred top-level order; anything else trails in its existing order.
    order = ["cicheto", "id", "name", "summary", "homepage", "license",
             "categories", "icon", "screenshots", "author", "packager",
             "bridge", "channels"]
    ordered = {k: data[k] for k in order if k in data}
    ordered.update({k: v for k, v in data.items() if k not in ordered})

    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True)
