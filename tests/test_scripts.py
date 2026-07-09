"""pytest entry point for CI.

The suite is a set of standalone scripts (module-level asserts, prints, and
`raise SystemExit(...)` for pass/fail/skip), historically run as
`python -m tests.test_x` from the repo root. Importing them all into one pytest
process would collide on module-level side effects (a shared spritz.db, mutated
os.environ, repeated init_db()).

So each script runs in its own subprocess, one parametrized pytest case per
file. That gives full isolation for free (fresh process, fresh env, fresh DB),
matches how the scripts already expect to run, and needs zero changes to them.

Each subprocess gets a unique throwaway SPRITZ_DB_URL under a tmp dir, so runs
are repeatable and never touch the developer's real spritz.db. test_db_guard's
use_throwaway_db() honors an externally-set SPRITZ_DB_URL, and the "outer
harness sets the DB" scripts (test_flow/frontend/security/...) rely on exactly
this.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

# Every test_*.py in tests/ is a runnable script, except this wrapper itself.
SCRIPTS = sorted(
    p.stem
    for p in TESTS_DIR.glob("test_*.py")
    if p.name != Path(__file__).name
)


@pytest.mark.parametrize("script", SCRIPTS)
def test_script(script, tmp_path):
    """Run one suite script as `python -m tests.<script>` in a subprocess."""
    env = dict(os.environ)
    # Fresh throwaway DB per script: repeatable, and never the real catalog.
    env["SPRITZ_DB_URL"] = f"sqlite:///{tmp_path / f'{script}.db'}"
    # Keep a script's own dev/secret defaults; only fill what it may need.
    env.setdefault("SPRITZ_ENV", "dev")

    proc = subprocess.run(
        [sys.executable, "-m", f"tests.{script}"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    output = proc.stdout + proc.stderr

    # Scripts skip cleanly by printing "SKIP" and exiting 0 (e.g. test_repo_proxy
    # when SPRITZ_PACKAGE_REPO_BIN is absent). Surface that as a pytest skip.
    if proc.returncode == 0 and "SKIP" in proc.stdout:
        pytest.skip(proc.stdout.strip().splitlines()[-1])

    assert proc.returncode == 0, (
        f"tests.{script} failed (exit {proc.returncode}):\n{output}"
    )
