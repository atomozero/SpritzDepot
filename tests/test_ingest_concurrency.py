"""Ingest is serialized per bàcaro slug, and a clone is verified complete before
a destructive prune (audit high). Throwaway DB, offline (local git).
"""
import os
import pathlib
import subprocess
import tempfile
import threading

os.environ["SPRITZ_ENV"] = "dev"
os.environ["SPRITZ_SECRET"] = "x"
os.environ["SPRITZ_ADMIN_TOKEN"] = "t"
os.environ["SPRITZ_DB_URL"] = "sqlite:///./test_ingest_concurrency.db"
for s in ("", "-wal", "-shm"):
    pathlib.Path("test_ingest_concurrency.db" + s).unlink(missing_ok=True)

from pathlib import Path
from sqlmodel import Session, select

from app.db import init_db, engine
from app.ingest import ingest_directory, _clone_or_pull, IngestError
from app.models import CichetoRow

init_db()

_CICH = ('cicheto: 1\nid: {id}\nname: N\nsummary: s\nchannels:\n  stable:\n'
         '    kind: hpkg\n    artifacts:\n      x86_64:\n        url: https://x/a.hpkg\n'
         '        sha256: "' + "0" * 64 + '"\n')


def _dir(app_id):
    d = Path(tempfile.mkdtemp())
    (d / "x.yaml").write_text(_CICH.format(id=app_id))
    return d


# --- serialized ingest: two concurrent crawls of the same slug don't corrupt ---
d1, d2 = _dir("org.a.one"), _dir("org.a.two")
threads = [threading.Thread(target=ingest_directory, args=(d, "sameslug", True))
           for d in (d1, d2)]
for t in threads:
    t.start()
for t in threads:
    t.join()
with Session(engine) as s:
    ids = sorted(r.id for r in s.exec(
        select(CichetoRow).where(CichetoRow.bacaro == "sameslug")).all())
# The lock serializes them, so the result is deterministic (last crawl wins under
# prune) and there is no lost-update / crash. Exactly one survives.
assert len(ids) == 1, f"expected 1 serialized row, got {ids}"
print("ingest serialized per slug: no race corruption -> ok")


# --- clone completeness: a non-git directory is rejected, not silently pruned ---
_env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

# a valid local repo clones fine through the hardened path
src = Path(tempfile.mkdtemp())
subprocess.run(["git", "init", "-q", str(src)], env=_env, check=True)
(src / "a.yaml").write_text(_CICH.format(id="org.ok.app"))
subprocess.run(["git", "-C", str(src), "add", "."], env=_env, check=True)
subprocess.run(["git", "-C", str(src), "commit", "-qm", "i"], env=_env, check=True)
dest = Path(tempfile.mkdtemp()) / "clone"
_clone_or_pull(str(src), dest)
assert (dest / "a.yaml").exists(), "valid clone should produce files"
print("hardened clone of a valid local repo -> ok")

# a plain (non-git) directory as the URL fails the clone, not a silent partial
plain = Path(tempfile.mkdtemp())
(plain / "a.yaml").write_text(_CICH.format(id="org.bad.app"))
try:
    _clone_or_pull(str(plain), Path(tempfile.mkdtemp()) / "c2")
    raise SystemExit("FAIL: cloning a non-git dir was accepted")
except IngestError:
    print("clone of a non-git dir -> IngestError (no silent partial) -> ok")

for s in ("", "-wal", "-shm"):
    pathlib.Path("test_ingest_concurrency.db" + s).unlink(missing_ok=True)
print("\nPASS: ingest concurrency + clone check")
