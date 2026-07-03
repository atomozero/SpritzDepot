"""Extract an app icon from a Haiku hpkg and render it to PNG.

Haiku icons are HVIF (a vector format) stored as a BEOS:ICON file attribute
inside the hpkg. Browsers cannot render HVIF, so we:
  1. fetch the hpkg (size-capped: an icon is not worth downloading 50 MB),
  2. decompress its heap (zstd or zlib, the two heap_compression values used),
  3. locate the HVIF blob by its 'ncif' magic,
  4. convert it to PNG with Haiku's host-built hvif2png tool.

Result is cached on disk (content of the source hpkg URL keyed by app id by the
caller). If hvif2png is not configured, or the hpkg is too big, or no icon is
found, the caller falls back to the generated placeholder.
"""
from __future__ import annotations

import os
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from . import config, netguard
from .hpkg_heap import HeapError, decompress_heap

HVIF_MAGIC = b"ncif"


class IconError(RuntimeError):
    """Icon could not be extracted/rendered (caller falls back to placeholder)."""


def tool_available() -> bool:
    b = config.HVIF2PNG_BIN
    return bool(b) and Path(b).is_file()


def _extract_hvif(hpkg: bytes) -> bytes:
    """Find the HVIF icon blob in an hpkg's decompressed heap."""
    if hpkg[:4] != b"hpkg":
        raise IconError("not an hpkg")
    # hpkg header: magic(4) header_size(2) version(2) total_size(8) minor(2)
    #   heap_compression(2) heap_chunk_size(4) heap_size_compressed(8)
    #   heap_size_uncompressed(8) ...
    (_magic, header_size, _ver, _total, _minor, heap_comp, chunk_size,
     heap_comp_size, heap_uncomp_size) = struct.unpack_from(">4sHHQHHIQQ", hpkg, 0)
    heap_raw = hpkg[header_size:header_size + heap_comp_size]
    try:
        heap = decompress_heap(heap_comp, heap_raw, heap_uncomp_size, chunk_size)
    except HeapError as e:
        raise IconError(str(e)) from e

    idx = heap.find(HVIF_MAGIC)
    if idx < 0:
        raise IconError("no HVIF icon in package")
    # We do not know the exact length from here, so hand hvif2png a generous
    # slice starting at the magic; the importer reads only what it needs and
    # ignores trailing bytes. Cap to keep it sane.
    return heap[idx:idx + 65536]


def _render_png(hvif: bytes, size: int = 64) -> bytes:
    tool = config.HVIF2PNG_BIN
    if not tool or not Path(tool).is_file():
        raise IconError("hvif2png not configured")
    env = dict(os.environ)
    t = Path(tool).resolve()
    for parent in t.parents:
        lib = parent / "lib"
        if (lib / "libbe_build.so").is_file():
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{lib}:{existing}" if existing else str(lib)
            break
    with tempfile.TemporaryDirectory() as td:
        hvif_path = Path(td) / "icon.hvif"
        png_path = Path(td) / "icon.png"
        hvif_path.write_bytes(hvif)
        proc = subprocess.run(
            [tool, "-s", str(size), "-i", str(hvif_path), "-o", str(png_path)],
            env=env, capture_output=True, text=True)
        if proc.returncode != 0 or not png_path.is_file():
            raise IconError(f"hvif2png failed: {proc.stderr or proc.stdout}")
        return png_path.read_bytes()


def icon_png_from_hpkg_url(url: str, size: int = 64,
                           client: Optional[httpx.Client] = None) -> bytes:
    """Download an hpkg (size-capped) and return its icon as PNG bytes.

    Raises IconError on any problem (too big, no icon, tool missing) so the
    caller can fall back to the placeholder.
    """
    if not tool_available():
        raise IconError("hvif2png not configured")

    def _read_capped(r) -> bytearray:
        r.raise_for_status()
        data = bytearray()
        for chunk in r.iter_bytes(1 << 16):
            data.extend(chunk)
            if len(data) > config.MAX_HPKG_FETCH_FOR_ICON:
                raise IconError(
                    f"hpkg exceeds icon-fetch cap "
                    f"({config.MAX_HPKG_FETCH_FOR_ICON} bytes)")
        return data

    try:
        if client is not None:
            # A caller-supplied client is a test double that never hits the
            # network; skip the (real) DNS/guard on its fake host. Production
            # fetches go through the guarded path below.
            with client.stream("GET", url) as r:
                data = _read_capped(r)
        else:
            # netguard.stream_guarded validates the URL and every redirect hop and
            # never blindly follows a 30x to an unvalidated (internal) host.
            with netguard.stream_guarded("GET", url, timeout=60.0) as r:
                data = _read_capped(r)
    except netguard.BlockedURLError as e:
        raise IconError(str(e)) from e
    except httpx.HTTPError as e:
        raise IconError(f"fetch failed: {e}") from e

    hvif = _extract_hvif(bytes(data))
    return _render_png(hvif, size)
