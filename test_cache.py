"""Size-bounded media cache: eviction keeps the on-disk cache under the budget.

Offline, uses a temp UPLOAD_DIR so it never touches real cache files.
"""
import os
import tempfile
import time
from pathlib import Path

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

_tmp = tempfile.mkdtemp(prefix="spritz-cache-test-")
os.environ["SPRITZ_UPLOAD_DIR"] = _tmp
os.environ["SPRITZ_MAX_CACHE_BYTES"] = str(1000)  # tiny budget for the test

from app import cache, config

assert config.MAX_CACHE_BYTES == 1000, config.MAX_CACHE_BYTES
icons = Path(_tmp) / "icons"


def write(name, size, age_seconds=0):
    p = icons / name
    cache.write_capped(p, b"x" * size)
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(p, (past, past))
    return p


# --- fits under budget: nothing evicted ---
a = write("a.png", 300, age_seconds=100)   # oldest
b = write("b.png", 300, age_seconds=50)
assert a.is_file() and b.is_file()
assert cache.current_size() == 600
print("under budget: both kept -> ok")

# --- writing a third that would exceed 1000 evicts the LRU (a.png) ---
c = write("c.png", 500)                    # 600 + 500 = 1100 > 1000 -> evict oldest
assert c.is_file(), "new file must be written"
assert not a.is_file(), "LRU (a.png) should have been evicted"
assert b.is_file(), "b.png (newer) should survive"
assert cache.current_size() <= 1000, cache.current_size()
print("over budget: LRU evicted, cache within cap -> ok")

# --- negative-cache markers are not counted or evicted as payload ---
(icons / "miss.none").write_bytes(b"")
before = cache.current_size()
write("d.png", 400)
assert (icons / "miss.none").is_file(), "miss marker must not be evicted"
print("negative-cache markers preserved -> ok")

# cleanup
import shutil
shutil.rmtree(_tmp, ignore_errors=True)
print("\nPASS: bounded media cache")
