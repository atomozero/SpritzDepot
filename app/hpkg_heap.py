"""Shared heap decompression for the Haiku package formats (HPKG and HPKR).

Both formats store a compressed heap whose `heap_compression` field is one of:
  0 = none, 1 = zlib, 2 = zstd.

This was duplicated (and divergent) between hpkr.py and hvif.py; keep it in one
place so a repo or package using either compression is handled the same way.
"""
from __future__ import annotations

import zlib


class HeapError(RuntimeError):
    """Heap could not be decompressed (unsupported compression / corrupt data)."""


def decompress_heap(compression: int, raw: bytes, uncompressed_size: int) -> bytes:
    """Decompress a Haiku package heap. `compression` is the header field:
    0 none, 1 zlib, 2 zstd. Raises HeapError on anything unsupported/bad."""
    if compression == 0:
        return raw[:uncompressed_size]
    if compression == 1:
        try:
            return zlib.decompress(raw)
        except zlib.error as e:
            raise HeapError(f"zlib heap decompress failed: {e}") from e
    if compression == 2:
        try:
            import zstandard
        except ImportError as e:
            raise HeapError("zstandard not installed for zstd heap") from e
        dctx = zstandard.ZstdDecompressor()
        try:
            return dctx.decompress(raw, max_output_size=uncompressed_size)
        except zstandard.ZstdError:
            # Fall back to streaming for multi-frame / unknown-size heaps.
            import io
            return dctx.stream_reader(io.BytesIO(raw)).read()
    raise HeapError(f"unsupported heap compression {compression}")
