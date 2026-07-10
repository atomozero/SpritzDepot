"""Heap decompression hardening: a hostile hpkg/hpkr must not OOM the server.

A malicious author or a compromised third-party repo controls the heap bytes and
the header fields that describe them. The parser downloads and decompresses these
automatically (repo import, resolve, icon extraction), so a decompression bomb
here is a remote DoS. These tests guard the caps that stop it, and confirm a
legitimate heap still round-trips.

Run: python -m tests.test_hpkg_heap
"""
import struct
import zlib

from app.hpkg_heap import decompress_heap, HeapError, MAX_HEAP_UNCOMPRESSED

CHUNK = 64 * 1024


# 1. zlib bomb: a tiny compressed blob that inflates far past its declared size
#    must be refused, not expanded. (Regression for the missing zlib output cap.)
bomb = zlib.compress(b"\x00" * (200 * 1024 * 1024), 9)
try:
    decompress_heap(1, bomb, uncompressed_size=1024, chunk_size=CHUNK)
    raise SystemExit("FAIL: zlib bomb was not blocked")
except HeapError:
    pass
print("zlib bomb blocked      -> ok")


# 2. The uncompressed-size cap itself still rejects an oversized declaration.
try:
    decompress_heap(1, b"x", uncompressed_size=MAX_HEAP_UNCOMPRESSED + 1, chunk_size=CHUNK)
    raise SystemExit("FAIL: oversized uncompressed_size was not blocked")
except HeapError:
    pass
print("size cap enforced      -> ok")


# 3. A legitimate multi-chunk zlib heap must still decompress exactly.
c0 = zlib.compress(b"A" * CHUNK, 6)
c1 = zlib.compress(b"B" * 100, 6)
table = struct.pack(">H", len(c0) - 1)          # first chunk comp size - 1
raw = c0 + c1 + table
out = decompress_heap(1, raw, uncompressed_size=CHUNK + 100, chunk_size=CHUNK)
assert out == b"A" * CHUNK + b"B" * 100, "legit multi-chunk heap did not round-trip"
print("legit heap round-trip  -> ok")


# 4. A chunk that decompresses to fewer bytes than declared must be rejected
#    (the single-chunk return path must not skip the size check).
short = zlib.compress(b"AB", 6)                  # 2 bytes, but we claim 1000
try:
    decompress_heap(1, short, uncompressed_size=1000, chunk_size=CHUNK)
    raise SystemExit("FAIL: under-sized chunk was not blocked")
except HeapError:
    pass
print("undersized chunk block -> ok")


print("\nPASS: hpkg heap hardening")
