"""Size-bounded on-disk media cache (extracted icons + proxied screenshots).

Both /icon and /screenshot write PNGs under UPLOAD_DIR. Without a bound, an
attacker enumerating ids could fill the disk until writes (and SQLite) fail,
taking the registry down. write_capped() enforces a total-byte ceiling: before
writing, if the cache would exceed config.MAX_CACHE_BYTES it evicts the
least-recently-used files (by mtime) until there is room.

The eviction is best-effort and coarse (whole-directory scan); the cache is not
hot enough for that to matter, and the correctness that matters is the ceiling,
not microsecond accuracy. A single object larger than the whole budget is still
written (we don't want to silently drop a legitimate icon), but that is bounded
elsewhere by the per-fetch caps.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import config

# Marker suffix for negative-cache entries (icon misses); they are tiny and must
# not be evicted preferentially or counted as reclaimable payload.
_MISS_SUFFIX = ".none"


def _cache_root() -> Path:
    return Path(config.UPLOAD_DIR)


def _iter_cache_files():
    """Yield (path, size, mtime) for every real payload file under the cache
    (icons/ and screenshots/), skipping negative-cache markers."""
    root = _cache_root()
    for sub in ("icons", "screenshots"):
        d = root / sub
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if not p.is_file() or p.name.endswith(_MISS_SUFFIX):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            yield p, st.st_size, st.st_mtime


def current_size() -> int:
    """Total bytes of cached payload files."""
    return sum(size for _, size, _ in _iter_cache_files())


def evict_to_fit(incoming: int) -> None:
    """Evict least-recently-used cache files until current + incoming fits within
    config.MAX_CACHE_BYTES. No-op if it already fits."""
    budget = config.MAX_CACHE_BYTES
    files = list(_iter_cache_files())
    total = sum(size for _, size, _ in files)
    if total + incoming <= budget:
        return
    # oldest first (smallest mtime)
    files.sort(key=lambda t: t[2])
    for path, size, _ in files:
        if total + incoming <= budget:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            continue


def write_capped(dest: Path, data: bytes) -> None:
    """Evict if needed, then write `data` to `dest` (creating parents)."""
    evict_to_fit(len(data))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
