"""Ingest DoS/trust bounds: per-file YAML byte cap, alias-bomb rejection, and
symlink skip (audit high). Offline, throwaway DB.
"""
import os
import pathlib
import tempfile

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_ingest_hardening.db"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_ingest_hardening.db" + s).unlink(missing_ok=True)

import yaml
from pathlib import Path

from app.db import init_db
from app.ingest import _parse_file, ingest_directory, IngestError, MAX_YAML_BYTES

init_db()

_VALID = ('cicheto: 1\nid: org.x.app\nname: App\nsummary: s\nchannels:\n  stable:\n'
          '    kind: hpkg\n    artifacts:\n      x86_64:\n        url: https://x/a.hpkg\n'
          '        sha256: "' + "0" * 64 + '"\n')

d = Path(tempfile.mkdtemp())

# valid parses
f = d / "ok.yaml"
f.write_text(_VALID)
assert _parse_file(f).id == "org.x.app"
print("valid cichéto parses -> ok")

# oversized rejected before parse
big = d / "big.yaml"
big.write_text(_VALID + "\n# " + "x" * MAX_YAML_BYTES)
try:
    _parse_file(big)
    raise SystemExit("FAIL: oversized file accepted")
except IngestError:
    print("oversized file -> IngestError (capped before parse) -> ok")

# YAML alias bomb rejected (anchors/aliases not allowed)
bomb = d / "bomb.yaml"
bomb.write_text("a: &x [1,2,3]\nb: [*x, *x, *x]\n" + _VALID)
try:
    _parse_file(bomb)
    raise SystemExit("FAIL: YAML alias accepted")
except yaml.YAMLError:
    print("YAML alias -> rejected -> ok")

# symlink pointing outside the tree is skipped, not read
sd = Path(tempfile.mkdtemp())
(sd / "real.yaml").write_text(_VALID.replace("org.x.app", "org.r.app"))
try:
    (sd / "evil.yaml").symlink_to("/etc/hostname")
    r = ingest_directory(sd, "t", prune=False)
    assert "org.r.app" in r["ingested"], r
    assert not any("evil" in str(x) for x in r["failed"]), "symlink was read"
    print("symlink skipped, real cichéto ingested -> ok")
except OSError:
    print("symlink test skipped (symlink creation not permitted here)")

for s in ("", "-wal", "-shm"):
    pathlib.Path("test_ingest_hardening.db" + s).unlink(missing_ok=True)
print("\nPASS: ingest DoS bounds")
