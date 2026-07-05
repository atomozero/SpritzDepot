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
# unknown codec with comp len != uncompressed size (so it can't pass through)
try:
    decompress_heap(9, b"ab", 100)
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

# A hanging hvif2png must not hang the worker: subprocess.run gets a timeout,
# and a TimeoutExpired becomes an IconError (caller falls back to placeholder).
import subprocess as _sp
from app import config as _cfg
_saved_bin, _saved_run = _cfg.HVIF2PNG_BIN, hvif.subprocess.run
_cfg.HVIF2PNG_BIN = "/bin/true"  # exists, so the tool-configured guard passes
_seen = {}
def _hang(cmd, **k):
    _seen.update(k)
    raise _sp.TimeoutExpired(cmd, k.get("timeout"))
hvif.subprocess.run = _hang
try:
    hvif._render_png(hvif_blob, 64)
    raise SystemExit("FAIL: timeout not turned into IconError")
except hvif.IconError as e:
    assert "timed out" in str(e), e
    assert _seen.get("timeout") == hvif.HVIF2PNG_TIMEOUT, _seen
    print("render timeout     -> ok (subprocess timeout -> IconError)")
finally:
    _cfg.HVIF2PNG_BIN, hvif.subprocess.run = _saved_bin, _saved_run

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
