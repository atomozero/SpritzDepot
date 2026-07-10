"""Minimal HPKR (Haiku Package Repository) catalog reader.

Reads a third-party repository's `repo` catalog and lists its packages, so a
cichéto can point at an existing Haiku repo (NOT HaikuPorts) and spritz can
resolve a package's download URL as `baseUrl + name-version-arch.hpkg`.

Scope and honesty:
  - Heap compression none / zlib / zstd is handled (shared with hvif.py via
    hpkg_heap.decompress_heap).
  - This is a *reader* for listing/resolving, not a full HPKG implementation.

Format reference (verified against haiku/docs/develop/packages/FileFormat.rst):
  header magic 'hpkr', a compressed heap, and a package-attributes section at
  the end of the heap encoded as nested TLV attributes with a string table.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import httpx

from . import netguard
from .hpkg_heap import HeapError, decompress_heap

HPKR_MAGIC = b"hpkr"

# A repository's HPKR catalog is small (a few MB even for HaikuPorts). Cap the
# download so a malicious/slow repo cannot exhaust memory or hang a worker.
MAX_CATALOG_BYTES = 64 * 1024 * 1024  # 64 MB

# Attribute tag bit layout (unsigned LEB128):
#   (encoding << 11) + (hasChildren << 10) + (dataType << 7) + id + 1
# A zero tag terminates a child list.
_ENCODING_SHIFT = 11
_HAS_CHILDREN_SHIFT = 10
_DATATYPE_SHIFT = 7
_ID_MASK = 0x7f
_DATATYPE_MASK = 0x7
_ENCODING_MASK = 0x3

# Data types (B_HPKG_ATTRIBUTE_TYPE_*, verified against HPKGDefs.h).
DT_INVALID = 0
DT_INT = 1
DT_UINT = 2
DT_STRING = 3
DT_RAW = 4

# String encodings.
ENC_STRING_INLINE = 0
ENC_STRING_TABLE = 1

# Int encodings (width in bytes: 1,2,4,8).
ENC_INT_8 = 0
ENC_INT_16 = 1
ENC_INT_32 = 2
ENC_INT_64 = 3

# Attribute IDs, read verbatim from haiku/headers/os/package/hpkg/
# PackageAttributes.h. (id, type) pairs:
ATTR_PACKAGE = 54              # STRING  "package"            (per-package container)
ATTR_PACKAGE_NAME = 15         # STRING  "package:name"
ATTR_PACKAGE_ARCHITECTURE = 21  # UINT   "package:architecture" (enum code)
ATTR_VERSION_MAJOR = 22        # STRING  "package:version.major"
ATTR_VERSION_MINOR = 23        # STRING  "package:version.minor"
ATTR_VERSION_MICRO = 24        # STRING  "package:version.micro"
ATTR_VERSION_REVISION = 25     # UINT    "package:version.revision"

# Architecture enum -> name, from BPackageInfo::kArchitectureNames.
ARCH_NAMES = ["any", "x86", "x86_gcc2", "source", "x86_64", "ppc", "arm",
              "m68k", "sparc", "arm64", "riscv64"]


class HpkrError(RuntimeError):
    """A catalog we cannot parse (bad magic, unsupported compression, truncated)."""


class CatalogTooLarge(HpkrError):
    """The repo catalog exceeded MAX_CATALOG_BYTES."""


def fetch_catalog(catalog_url: str, client=None) -> bytes:
    """Fetch a repo's HPKR catalog with the SSRF guard (every redirect hop) and a
    hard size cap, streaming so an oversized body is cut off early. A caller-
    supplied client (tests) is trusted but still guarded + capped."""
    def _read(r) -> bytes:
        r.raise_for_status()
        buf = bytearray()
        for chunk in r.iter_bytes(1 << 16):
            buf.extend(chunk)
            if len(buf) > MAX_CATALOG_BYTES:
                raise CatalogTooLarge(
                    f"catalog exceeds {MAX_CATALOG_BYTES} bytes: {catalog_url}")
        return bytes(buf)

    if client is not None:
        # A caller-supplied client is a test double that never touches the
        # network, so we don't DNS-resolve/guard its (often fake) host; the real
        # guarded path below is what protects production fetches.
        with client.stream("GET", catalog_url) as r:
            return _read(r)
    with netguard.stream_guarded("GET", catalog_url, timeout=20.0) as r:
        return _read(r)


@dataclass
class RepoPackage:
    name: str
    version: str
    architecture: str

    def filename(self) -> str:
        return f"{self.name}-{self.version}-{self.architecture}.hpkg"


# ---- low-level readers ----

class _Reader:
    """Cursor over a bytes buffer with LEB128 + fixed-width int helpers."""
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def u8(self) -> int:
        if self.pos >= len(self.data):
            raise HpkrError("unexpected end of catalog reading u8")
        b = self.data[self.pos]
        self.pos += 1
        return b

    def uint(self, width: int) -> int:
        # Attribute integers are big-endian (B_HOST_TO_BENDIAN in the writer).
        vals = {1: ">B", 2: ">H", 4: ">I", 8: ">Q"}
        fmt = vals[width]
        if self.pos + width > len(self.data):
            raise HpkrError("unexpected end of catalog reading uint")
        v = struct.unpack_from(fmt, self.data, self.pos)[0]
        self.pos += width
        return v

    def leb128(self) -> int:
        """Unsigned LEB128, bounded. A u64 needs at most 10 bytes; a run of
        continuation bytes past the buffer (or past 64 bits) is a crafted catalog,
        not valid data, so we raise instead of over-reading / building a bignum."""
        result = 0
        shift = 0
        while True:
            if self.pos >= len(self.data):
                raise HpkrError("unexpected end of catalog reading leb128")
            if shift >= 64:
                raise HpkrError("leb128 value too long (> 64 bits)")
            b = self.data[self.pos]
            self.pos += 1
            result |= (b & 0x7f) << shift
            if not (b & 0x80):
                break
            shift += 7
        return result

    def cstring(self) -> str:
        end = self.data.find(b"\x00", self.pos)
        if end == -1:
            raise HpkrError("unterminated string in catalog")
        s = self.data[self.pos:end].decode("utf-8", "replace")
        self.pos = end + 1
        return s




def _read_value(r: _Reader, data_type: int, encoding: int, strings: list):
    """Read one attribute value given its type + encoding."""
    if data_type == DT_STRING:
        if encoding == ENC_STRING_INLINE:
            return r.cstring()
        if encoding == ENC_STRING_TABLE:
            idx = r.leb128()
            return strings[idx] if idx < len(strings) else ""
        raise HpkrError(f"bad string encoding {encoding}")
    if data_type in (DT_INT, DT_UINT):
        width = {ENC_INT_8: 1, ENC_INT_16: 2, ENC_INT_32: 4, ENC_INT_64: 8}[encoding]
        return r.uint(width)
    if data_type == DT_RAW:
        # inline (enc 0): size then bytes; heap ref (enc 1): size + offset.
        if encoding == 0:
            size = r.leb128()
            if size < 0 or r.pos + size > len(r.data):
                raise HpkrError("raw value size out of range")
            v = r.data[r.pos:r.pos + size]
            r.pos += size
            return v
        size = r.leb128(); r.leb128()  # size, heap offset (skip, not needed here)
        return None
    raise HpkrError(f"unknown data type {data_type}")


# Haiku package attribute nesting is shallow (package -> version.major -> parts).
# Cap recursion so a crafted catalog that is a deep chain of has_children tags
# can't blow the Python/C stack (RecursionError). 64 is far beyond any real file.
_MAX_ATTR_DEPTH = 64


def _walk(r: _Reader, strings: list, on_package, depth: int = 0):
    """Walk attributes at the current nesting level until a zero tag. Calls
    on_package(attrs_dict) for each top-level 'package' attribute."""
    if depth > _MAX_ATTR_DEPTH:
        raise HpkrError("attribute nesting too deep")
    while not r.eof():
        tag = r.leb128()
        if tag == 0:
            return  # end of this child list
        tag -= 1
        attr_id = tag & _ID_MASK
        data_type = (tag >> _DATATYPE_SHIFT) & _DATATYPE_MASK
        has_children = (tag >> _HAS_CHILDREN_SHIFT) & 1
        encoding = (tag >> _ENCODING_SHIFT) & _ENCODING_MASK

        value = _read_value(r, data_type, encoding, strings)

        if attr_id == ATTR_PACKAGE:
            pkg: dict = {}
            if has_children:
                _collect_package(r, strings, pkg, depth + 1)
            on_package(pkg)
        elif has_children:
            # Descend but ignore (some other container); skip its children.
            _skip_children(r, strings, depth + 1)


_WANTED = {ATTR_PACKAGE_NAME, ATTR_PACKAGE_ARCHITECTURE, ATTR_VERSION_MAJOR,
           ATTR_VERSION_MINOR, ATTR_VERSION_MICRO, ATTR_VERSION_REVISION}


def _collect_package(r: _Reader, strings: list, pkg: dict, depth: int = 0):
    """Collect a 'package' container's attributes into pkg, until a zero tag.

    The version is nested: version.major carries minor/micro/revision as its
    children. We record the first occurrence of each wanted id (the top-level
    name/version.major plus the version sub-parts), and only descend into the
    version.major subtree; other children (e.g. provides/requires with their own
    version subtrees) are skipped so their version parts do not overwrite ours."""
    if depth > _MAX_ATTR_DEPTH:
        raise HpkrError("attribute nesting too deep")
    while not r.eof():
        tag = r.leb128()
        if tag == 0:
            return
        tag -= 1
        attr_id = tag & _ID_MASK
        data_type = (tag >> _DATATYPE_SHIFT) & _DATATYPE_MASK
        has_children = (tag >> _HAS_CHILDREN_SHIFT) & 1
        encoding = (tag >> _ENCODING_SHIFT) & _ENCODING_MASK
        value = _read_value(r, data_type, encoding, strings)

        if attr_id in _WANTED and attr_id not in pkg:
            pkg[attr_id] = value

        if has_children:
            # Only the top-level version.major subtree holds the version parts
            # we want; descend into it, skip everything else.
            if attr_id == ATTR_VERSION_MAJOR:
                _collect_package(r, strings, pkg, depth + 1)
            else:
                _skip_children(r, strings, depth + 1)


def _skip_children(r: _Reader, strings: list, depth: int = 0):
    """Consume a child list (and nested ones) without recording anything."""
    if depth > _MAX_ATTR_DEPTH:
        raise HpkrError("attribute nesting too deep")
    while not r.eof():
        tag = r.leb128()
        if tag == 0:
            return
        tag -= 1
        data_type = (tag >> _DATATYPE_SHIFT) & _DATATYPE_MASK
        has_children = (tag >> _HAS_CHILDREN_SHIFT) & 1
        encoding = (tag >> _ENCODING_SHIFT) & _ENCODING_MASK
        _read_value(r, data_type, encoding, strings)
        if has_children:
            _skip_children(r, strings, depth + 1)


def _compose_version(pkg: dict) -> str:
    major = pkg.get(ATTR_VERSION_MAJOR, "")
    minor = pkg.get(ATTR_VERSION_MINOR)
    micro = pkg.get(ATTR_VERSION_MICRO)
    revision = pkg.get(ATTR_VERSION_REVISION)
    v = str(major)
    if minor not in (None, ""):
        v += f".{minor}"
    if micro not in (None, ""):
        v += f".{micro}"
    if revision:
        v += f"-{revision}"
    return v


def parse_catalog(blob: bytes) -> list:
    """Parse an HPKR 'repo' catalog and return a list of RepoPackage.

    The catalog is untrusted (fetched from a third-party repo), so this wrapper
    turns ANY parser exception into HpkrError. The inner parser already raises
    HpkrError for the cases it validates, but a crafted catalog can still trigger
    struct.error (truncated header), RecursionError (deep nesting), MemoryError,
    etc.; callers only catch HpkrError, so without this a bad catalog would
    surface as an unhandled 500 / worker crash instead of a clean failure.
    """
    try:
        return _parse_catalog_inner(blob)
    except HpkrError:
        raise
    except Exception as e:  # noqa: BLE001 - untrusted input, fail as domain error
        raise HpkrError(f"malformed catalog: {type(e).__name__}: {e}") from e


def _parse_catalog_inner(blob: bytes) -> list:
    if len(blob) < 4 or blob[:4] != HPKR_MAGIC:
        raise HpkrError("not an HPKR file (bad magic)")
    # Bound the header reads: the two unpacks below need this many bytes.
    _need = struct.calcsize(">4sHHQHHIQQ") + struct.calcsize(">IIQQQ")
    if len(blob) < _need:
        raise HpkrError("catalog too small for its header")

    # Header (big-endian per the format's network order). Field offsets:
    # magic(4) header_size(2) version(2) total_size(8) minor(2)
    # heap_compression(2) heap_chunk_size(4) heap_size_compressed(8)
    # heap_size_uncompressed(8) info_length(4) reserved1(4)
    # packages_length(8) packages_strings_length(8) packages_strings_count(8)
    (magic, header_size, version, total_size, minor, heap_comp, chunk_size,
     heap_comp_size, heap_uncomp_size) = struct.unpack_from(">4sHHQHHIQQ", blob, 0)
    off = struct.calcsize(">4sHHQHHIQQ")
    info_length, reserved1, packages_length, strings_length, strings_count = \
        struct.unpack_from(">IIQQQ", blob, off)

    heap_raw = blob[header_size:header_size + heap_comp_size]
    try:
        heap = decompress_heap(heap_comp, heap_raw, heap_uncomp_size, chunk_size)
    except HeapError as e:
        raise HpkrError(str(e)) from e

    # The package-attributes section is at the end of the heap. Guard against a
    # lying packages_length: > len(heap) makes the slice start negative (Python
    # negative indexing) and mis-parses from an attacker-chosen offset.
    if packages_length > len(heap):
        raise HpkrError("packages_length exceeds heap size")
    pkg_section = heap[len(heap) - packages_length:]
    r = _Reader(pkg_section)

    # Strings table first: `strings_count` null-terminated strings, then a
    # single 0-byte terminator (an empty string can't be distinguished from the
    # end marker, per WriteCachedStrings). Consume that terminator before the
    # attributes begin.
    # strings_count is an unbounded u64 from the attacker-controlled header. Each
    # string is at least one byte (its null terminator), so more than
    # len(pkg_section) strings is impossible; cap it there before building the
    # list so a lie like 2**63 cannot drive a giant allocation / CPU burn.
    # cstring() still raises at EOF, this just refuses the count up front.
    if strings_count > len(pkg_section):
        raise HpkrError(
            f"strings_count {strings_count} exceeds section size {len(pkg_section)}")
    strings: list = [r.cstring() for _ in range(strings_count)]
    if not r.eof() and r.data[r.pos] == 0:
        r.pos += 1

    packages: list = []

    def on_package(pkg: dict):
        name = pkg.get(ATTR_PACKAGE_NAME)
        if not name:
            return
        arch_code = pkg.get(ATTR_PACKAGE_ARCHITECTURE, 0)
        arch = ARCH_NAMES[arch_code] if isinstance(arch_code, int) and arch_code < len(ARCH_NAMES) else "any"
        packages.append(RepoPackage(name=name, version=_compose_version(pkg),
                                    architecture=arch))

    _walk(r, strings, on_package)
    return packages


def resolve_from_repo(repo_url: str, package: str, arch: Optional[str] = None,
                      client: Optional[httpx.Client] = None) -> dict:
    """Given a third-party Haiku repository base URL and a package name, fetch
    its `repo` catalog, find the package, and return the download URL(s):
    `{arch: {"url": baseUrl + filename}}` (no sha256; the client verifies it,
    same as ombra). Raises HpkrError on fetch/parse problems or no match.

    `repo_url` is the base URL that also serves repo.info and the packages/
    directory (HaikuPorts is excluded by policy at the call site, not here)."""
    base = repo_url.rstrip("/")
    catalog_url = f"{base}/repo"
    try:
        blob = fetch_catalog(catalog_url, client=client)
    except netguard.BlockedURLError as e:
        raise HpkrError(str(e)) from e
    except httpx.HTTPError as e:
        raise HpkrError(f"cannot fetch catalog {catalog_url}: {e}") from e

    pkgs = [p for p in parse_catalog(blob) if p.name == package
            and (arch is None or p.architecture == arch)]
    if not pkgs:
        raise HpkrError(f"package '{package}' not found in {base}"
                        + (f" for arch {arch}" if arch else ""))
    return {p.architecture: {"url": f"{base}/packages/{p.filename()}"}
            for p in pkgs}
