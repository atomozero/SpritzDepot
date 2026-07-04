"""Shared heap decompression for the Haiku package formats (HPKG and HPKR).

The heap is a sequence of fixed-size chunks (`heap_chunk_size`, normally 64 KiB),
each compressed independently. `heap_compression` selects the codec:
  0 = none, 1 = zlib, 2 = zstd.

Layout of the compressed heap region (size = `heap_size_compressed` from the
header), per Haiku's PackageFileHeapReader:
  - the compressed chunks, back to back, then
  - a chunk-size table of (chunkCount - 1) big-endian uint16, where each stored
    value is (compressedChunkSize - 1). The last chunk's compressed size is
    implied (region end minus its offset). The table is omitted when there is
    no compression or only one chunk.

Decoding chunk by chunk is required: a naive whole-region inflate returns only
the first chunk, so anything past the first 64 KiB (icons, later packages) is
silently lost. This module does it correctly and is shared by hpkr.py/hvif.py.
"""
from __future__ import annotations

import struct
import zlib

DEFAULT_CHUNK_SIZE = 64 * 1024

# The decompressed size and chunk size are read from an attacker-controlled
# header (a malicious third-party repo picks them). Cap them so a decompression
# bomb (tiny compressed input claiming gigabytes uncompressed) cannot exhaust
# memory, and so a zero/absurd chunk size cannot divide-by-zero or explode the
# chunk count. 256 MiB comfortably covers any real Haiku package heap.
MAX_HEAP_UNCOMPRESSED = 256 * 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024


class HeapError(RuntimeError):
    """Heap could not be decompressed (unsupported compression / corrupt data)."""


def _inflate_chunk(compression: int, comp: bytes, uncompressed_size: int) -> bytes:
    """Decompress one chunk to exactly `uncompressed_size` bytes.

    A chunk may be stored uncompressed even in a compressed heap when
    compression did not help; in that case its bytes are passed through. We
    detect that by length (compressed == uncompressed)."""
    if compression == 0 or len(comp) == uncompressed_size:
        return comp
    if compression == 1:
        try:
            return zlib.decompress(comp)
        except zlib.error as e:
            raise HeapError(f"zlib chunk decompress failed: {e}") from e
    if compression == 2:
        try:
            import zstandard
        except ImportError as e:
            raise HeapError("zstandard not installed for zstd heap") from e
        try:
            return zstandard.ZstdDecompressor().decompress(
                comp, max_output_size=uncompressed_size)
        except zstandard.ZstdError as e:
            raise HeapError(f"zstd chunk decompress failed: {e}") from e
    raise HeapError(f"unsupported heap compression {compression}")


def decompress_heap(compression: int, raw: bytes, uncompressed_size: int,
                    chunk_size: int = DEFAULT_CHUNK_SIZE) -> bytes:
    """Decompress a whole Haiku package heap (all chunks).

    `raw` is the full compressed heap region (`heap_size_compressed` bytes,
    including the trailing chunk-size table). `chunk_size` is the header's
    `heap_chunk_size`. Raises HeapError on unsupported codecs or corrupt data.
    """
    # Reject attacker-controlled sizes before they drive any allocation, slice,
    # or division. chunk_size <= 0 would ZeroDivisionError on the chunk_count
    # below; an oversized uncompressed_size is a decompression bomb.
    if uncompressed_size < 0 or uncompressed_size > MAX_HEAP_UNCOMPRESSED:
        raise HeapError(
            f"heap uncompressed size {uncompressed_size} out of range "
            f"(max {MAX_HEAP_UNCOMPRESSED})")
    if chunk_size <= 0 or chunk_size > MAX_CHUNK_SIZE:
        raise HeapError(f"invalid heap chunk size {chunk_size}")

    if uncompressed_size == 0:
        return b""
    if compression == 0:
        return raw[:uncompressed_size]

    chunk_count = (uncompressed_size + chunk_size - 1) // chunk_size
    if chunk_count <= 1:
        # Single chunk: the whole region is one compressed blob, no size table.
        return _inflate_chunk(compression, raw, uncompressed_size)

    # The last (chunk_count - 1) * 2 bytes are the compressed-size table.
    table_size = (chunk_count - 1) * 2
    if len(raw) <= table_size:
        raise HeapError("compressed heap too small for its chunk-size table")
    data = raw[:len(raw) - table_size]
    table = raw[len(raw) - table_size:]

    # Compressed size of each of the first (chunk_count - 1) chunks. Stored
    # value is size-1, big-endian uint16.
    comp_sizes = [struct.unpack_from(">H", table, i * 2)[0] + 1
                  for i in range(chunk_count - 1)]

    out = bytearray()
    pos = 0
    for i in range(chunk_count):
        is_last = (i == chunk_count - 1)
        if is_last:
            comp = data[pos:]
            unc = uncompressed_size - i * chunk_size
        else:
            comp = data[pos:pos + comp_sizes[i]]
            unc = chunk_size
            pos += comp_sizes[i]
        out.extend(_inflate_chunk(compression, comp, unc))

    if len(out) != uncompressed_size:
        raise HeapError(
            f"heap size mismatch: got {len(out)}, expected {uncompressed_size}")
    return bytes(out)
