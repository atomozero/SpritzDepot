"""Adversarial-input tests for the untrusted binary parsers and the ingest
trust boundary (audit critical #1-#4). All offline, throwaway DB.

Every malformed input must fail as a DOMAIN error (HpkrError/IconError/HeapError/
ValidationError), never an unhandled struct.error/IndexError/ZeroDivisionError/
RecursionError/MemoryError, and never hang or OOM.
"""
import os
import struct

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_parser_hardening.db"

import pathlib
pathlib.Path("test_parser_hardening.db").unlink(missing_ok=True)

from app import hpkr, hvif
from app.hpkg_heap import decompress_heap, HeapError, MAX_HEAP_UNCOMPRESSED


# ---------- Critical #1: decompression bomb + bad chunk size ----------

# uncompressed size beyond the cap -> HeapError, no allocation
try:
    decompress_heap(1, b"\x00" * 100, MAX_HEAP_UNCOMPRESSED + 1, 64 * 1024)
    raise SystemExit("FAIL: oversized heap accepted")
except HeapError:
    pass

# chunk_size = 0 would ZeroDivisionError on chunk_count -> must be HeapError
try:
    decompress_heap(1, b"\x00" * 100, 1024, 0)
    raise SystemExit("FAIL: zero chunk_size accepted")
except HeapError:
    pass

# negative-ish (huge) chunk_size rejected
try:
    decompress_heap(1, b"\x00" * 100, 1024, 999_999_999)
    raise SystemExit("FAIL: oversized chunk_size accepted")
except HeapError:
    pass

# a legitimately empty heap still works
assert decompress_heap(1, b"", 0, 64 * 1024) == b""
print("heap: bomb + bad chunk_size rejected, empty ok -> ok")


# ---------- Critical #2: leb128 / cstring over-read ----------

R = hpkr._Reader

# leb128 that runs off the end (all continuation bytes) -> HpkrError not IndexError
try:
    R(b"\x80\x80\x80").leb128()
    raise SystemExit("FAIL: unterminated leb128 accepted")
except hpkr.HpkrError:
    pass

# leb128 longer than 64 bits -> HpkrError not a giant bignum
try:
    R(b"\x80" * 12 + b"\x01").leb128()
    raise SystemExit("FAIL: overlong leb128 accepted")
except hpkr.HpkrError:
    pass

# cstring with no NUL terminator -> HpkrError not ValueError
try:
    R(b"abc").cstring()
    raise SystemExit("FAIL: unterminated cstring accepted")
except hpkr.HpkrError:
    pass

# a valid leb128 still decodes
assert R(b"\xac\x02").leb128() == 300
print("reader: leb128/cstring over-read -> HpkrError, valid still decodes -> ok")


# ---------- parse_catalog: any malformed catalog -> HpkrError, no crash/hang ----------

# empty / too-short / bad magic
for bad in [b"", b"hp", b"hpkr", b"hpkr" + b"\x00" * 10, b"notmagic" + b"\x00" * 60]:
    try:
        hpkr.parse_catalog(bad)
        raise SystemExit(f"FAIL: parse_catalog accepted {bad!r}")
    except hpkr.HpkrError:
        pass

# valid magic + a header that lies about packages_length (bigger than the heap)
# Build a minimal well-formed-magic header: >4sHHQHHIQQ then >IIQQQ
hdr = struct.pack(">4sHHQHHIQQ", b"hpkr", 40, 1, 0, 0,
                  0,       # heap_comp = none
                  65536,   # chunk_size
                  0,       # heap_comp_size = 0 (empty heap)
                  0)       # heap_uncomp_size = 0
tail = struct.pack(">IIQQQ", 0, 0,
                   2**40,   # packages_length: absurdly large
                   0, 0)
try:
    hpkr.parse_catalog(hdr + tail)
    raise SystemExit("FAIL: lying packages_length accepted")
except hpkr.HpkrError:
    pass
print("parse_catalog: truncated/bad-magic/lying-length -> HpkrError -> ok")


# ---------- _extract_hvif: truncated hpkg -> IconError not struct.error ----------

for bad in [b"", b"hp", b"hpkg", b"hpkg" + b"\x00" * 10]:
    try:
        hvif._extract_hvif(bad)
        raise SystemExit(f"FAIL: _extract_hvif accepted {bad!r}")
    except hvif.IconError:
        pass
print("_extract_hvif: truncated hpkg -> IconError -> ok")


# ---------- Critical #3: id path-traversal rejected at schema ----------

from app.schemas import Cicheto
from pydantic import ValidationError

_valid_channel = {"stable": {"kind": "hpkg",
                             "artifacts": {"x86_64": {"url": "https://x/a.hpkg",
                                                      "sha256": "0" * 64}}}}

def make(cid):
    return Cicheto(id=cid, name="X", summary="s", channels=_valid_channel)

for bad_id in ["../../etc/passwd", "..", "a/b", "a\\b", "UPPER.Case",
               "no-dot", "org.haiku/../x", ".leading", "trailing."]:
    try:
        make(bad_id)
        raise SystemExit(f"FAIL: bad id accepted: {bad_id!r}")
    except ValidationError:
        pass

# a real reverse-domain id is accepted
assert make("org.haiku.genio").id == "org.haiku.genio"
assert make("com.atomozero.teslaviewer").id == "com.atomozero.teslaviewer"
print("schema: path-traversal ids rejected, reverse-domain accepted -> ok")

# oversized fields rejected
try:
    Cicheto(id="org.x.y", name="X", summary="z" * 3000, channels=_valid_channel)
    raise SystemExit("FAIL: oversized summary accepted")
except ValidationError:
    pass
print("schema: oversized summary rejected -> ok")


# ---------- Critical #4: cross-bàcaro id collision refused at ingest ----------

from app.db import init_db, engine
from sqlmodel import Session
from app.models import CichetoRow
from app.ingest import ingest_directory
import tempfile

init_db()
# Pre-seed an app owned by bàcaro "vepro"
with Session(engine) as s:
    for r in s.exec(__import__("sqlmodel").select(CichetoRow)).all():
        s.delete(r)
    s.commit()
    s.merge(CichetoRow(id="org.haiku.genio", name="Genio", bacaro="vepro",
                       channels="stable", raw={"id": "org.haiku.genio", "name": "Genio"}))
    s.commit()

# A malicious bàcaro "evil" tries to publish the same id
tmp = tempfile.mkdtemp(prefix="evil-bacaro-")
pathlib.Path(tmp, "hijack.yaml").write_text(
    "cicheto: 1\nid: org.haiku.genio\nname: NotGenio\nsummary: pwned\n"
    "channels:\n  stable:\n    kind: hpkg\n    artifacts:\n"
    "      x86_64:\n        url: https://evil/x.hpkg\n        sha256: \"" + "0"*64 + "\"\n")

result = ingest_directory(pathlib.Path(tmp), "evil", prune=False)
assert result["ingested"] == [], f"hijack was ingested: {result}"
assert any("already owned by" in f["error"] for f in result["failed"]), result

# the original row is untouched
with Session(engine) as s:
    row = s.get(CichetoRow, "org.haiku.genio")
    assert row.bacaro == "vepro" and row.name == "Genio", "row was hijacked"
print("ingest: cross-bàcaro id collision refused, owner untouched -> ok")

import shutil
shutil.rmtree(tmp, ignore_errors=True)
pathlib.Path("test_parser_hardening.db").unlink(missing_ok=True)
print("\nPASS: parser + ingest hardening")
