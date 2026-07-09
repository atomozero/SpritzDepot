"""build_subrepo prunes stale hpkg from packages/, and _slug is collision-free
(audit high). Unit-level: stubs the native package_repo tool so it runs anywhere.
"""
import os
import subprocess
import tempfile
from pathlib import Path

os.environ.setdefault("SPRITZ_ENV", "dev")
os.environ.setdefault("SPRITZ_SECRET", "x")
os.environ.setdefault("SPRITZ_ADMIN_TOKEN", "t")

from app import repo_proxy
from app.main import _slug


# ---------- _slug is collision-free and stable ----------
assert _slug("x86_64") == "x86_64"           # clean input unchanged
assert _slug("vepro") == "vepro"
a, b = _slug("Foo Bar"), _slug("Foo/Bar")    # both lossy, must differ
assert a != b, f"slug collision: {a} == {b}"
assert _slug("Foo Bar") == a, "slug not stable"
print("slug: clean stays readable, lossy inputs distinct + stable -> ok")


# ---------- build_subrepo prunes stale files ----------
# Stub the pieces that need the native tool / real hpkg parsing.
_orig_tool = repo_proxy._tool_path
_orig_meta = repo_proxy.read_package_meta
_orig_canon = repo_proxy.canonical_filename
_orig_run = repo_proxy.subprocess.run


class _Meta:
    def __init__(self, name): self.name = name; self.vendor = "V"; self.architecture = "x86_64"

repo_proxy._tool_path = lambda: "/bin/true"
# the "canonical filename" is just the source file's own name for this test
repo_proxy.read_package_meta = lambda p: _Meta(Path(p).stem)
repo_proxy.canonical_filename = lambda meta: f"{meta.name}.hpkg"
# package_repo create is stubbed: write the "repo" catalog next to the repo.info
# it is handed (cmd = [tool, "create", <info_path>, *packages]), like the real tool.
def _fake_run(cmd, **k):
    info_path = Path(cmd[2])
    (info_path.parent / "repo").write_bytes(b"hpkr-stub")
    return subprocess.CompletedProcess(cmd, 0, "", "")
repo_proxy.subprocess.run = _fake_run

try:
    tmp = Path(tempfile.mkdtemp(prefix="subrepo-"))
    out = tmp / "current"
    pkgs_src = tmp / "src"
    pkgs_src.mkdir()
    # two real inputs for this build
    keep = pkgs_src / "keep.hpkg"; keep.write_bytes(b"a")
    keep2 = pkgs_src / "keep2.hpkg"; keep2.write_bytes(b"b")

    # a stale file from a "previous build" already sitting in packages/
    (out / "packages").mkdir(parents=True)
    stale = out / "packages" / "stale.hpkg"
    stale.write_bytes(b"old")
    assert stale.exists()

    repo_proxy.build_subrepo([keep, keep2], "V", "x86_64", out, "https://x/repo")

    names = sorted(p.name for p in (out / "packages").iterdir() if p.is_file())
    assert "stale.hpkg" not in names, f"stale file not pruned: {names}"
    assert "keep.hpkg" in names and "keep2.hpkg" in names, names
    print("build_subrepo: stale hpkg pruned, current set kept -> ok")
finally:
    repo_proxy._tool_path = _orig_tool
    repo_proxy.read_package_meta = _orig_meta
    repo_proxy.canonical_filename = _orig_canon
    repo_proxy.subprocess.run = _orig_run
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print("\nPASS: repo-proxy slug + prune")
