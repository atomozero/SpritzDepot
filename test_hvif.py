"""Icon extraction test: hpkg -> HVIF -> PNG.

Uses a tiny real hpkg fixture (minecraft_installer, 5 KB, from the lote repo).
The HVIF extraction (zstd heap decompress + locate the 'ncif' blob) is verified
unconditionally. The PNG rendering needs Haiku's host-built hvif2png; if
SPRITZ_HVIF2PNG_BIN is not set, that part is skipped (printed), so the test
still passes in a plain environment.
"""
import os

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

from pathlib import Path
from app import hvif
from app.hpkg_heap import decompress_heap, HeapError

# Shared heap decompression: none / zlib / zstd / unsupported.
import zlib as _zlib
assert decompress_heap(0, b"hello world", 5) == b"hello"
assert decompress_heap(1, _zlib.compress(b"abc" * 10), 30) == b"abc" * 10
import zstandard as _zstd
assert decompress_heap(2, _zstd.ZstdCompressor().compress(b"xyz" * 10), 30) == b"xyz" * 10
try:
    decompress_heap(9, b"", 0)
    raise SystemExit("FAIL: unsupported compression accepted")
except HeapError:
    pass
print("heap decompress    -> ok (none/zlib/zstd/unsupported)")

FIXTURE = (Path(__file__).parent / "tests" / "fixtures"
           / "minecraft_installer-1.3.2-1-x86_64.hpkg")

data = FIXTURE.read_bytes()
assert data[:4] == b"hpkg", "fixture is not an hpkg"

# HVIF extraction works regardless of the render tool.
hvif_blob = hvif._extract_hvif(data)
assert hvif_blob[:4] == b"ncif", f"expected HVIF magic, got {hvif_blob[:4]!r}"
print("extract HVIF       -> ok (ncif blob found)")

# no-icon / bad input is reported, not crashed
try:
    hvif._extract_hvif(b"not an hpkg at all")
    raise SystemExit("FAIL: bad input accepted")
except hvif.IconError:
    print("bad hpkg rejected  -> ok")

# Rendering: only if the tool is configured.
if hvif.tool_available():
    png = hvif._render_png(hvif_blob, 64)
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    assert len(png) > 100
    print("render PNG         -> ok", len(png), "bytes")
else:
    print("render PNG         -> skipped (set SPRITZ_HVIF2PNG_BIN to test)")

print("\nPASS: HVIF extraction" +
      ("" if hvif.tool_available() else " (render skipped)"))
