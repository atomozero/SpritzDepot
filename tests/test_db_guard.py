"""Shared test DB-safety guard.

Import this at the TOP of any test module, before importing app.db, to guarantee
the test runs against a throwaway SQLite file and can never touch the real
catalog (spritz.db). Also runnable on its own as a test that asserts the guard
works and that no test file writes to spritz.db by default.

    import test_db_guard  # noqa: F401  (must precede `from app.db import ...`)
"""
import os
import pathlib


def use_throwaway_db(name: str) -> str:
    """Point SPRITZ_DB_URL at ./<name>.db (a throwaway) unless the caller already
    set an explicit test DB. Refuses to run against the real spritz.db."""
    url = os.environ.get("SPRITZ_DB_URL")
    if url and "spritz.db" not in url:
        return url  # caller already chose a safe DB
    path = f"./{name}.db"
    os.environ["SPRITZ_DB_URL"] = f"sqlite:///{path}"
    for suffix in ("", "-wal", "-shm"):
        pathlib.Path(path[2:] + suffix).unlink(missing_ok=True)
    return os.environ["SPRITZ_DB_URL"]


def assert_safe() -> None:
    """Fail loudly if the active engine URL resolves to the real catalog."""
    from app.db import engine
    url = str(engine.url)
    assert "spritz.db" not in url, (
        f"TEST DANGER: engine points at the real catalog ({url}). "
        "Set SPRITZ_DB_URL to a throwaway before importing app.db.")


if __name__ == "__main__":
    # 1. the guard sets a throwaway when nothing is set
    os.environ.pop("SPRITZ_DB_URL", None)
    u = use_throwaway_db("test_db_guard")
    assert u == "sqlite:///./test_db_guard.db", u
    assert_safe()
    print("guard sets a throwaway DB when unset -> ok")

    # 2. the guard refuses to leave SPRITZ_DB_URL pointing at spritz.db
    os.environ["SPRITZ_DB_URL"] = "sqlite:///./spritz.db"
    u2 = use_throwaway_db("test_db_guard")
    assert "spritz.db" not in u2, u2
    print("guard overrides an unsafe spritz.db URL -> ok")

    # 3. static check: every test_*.py either sets SPRITZ_DB_URL or imports this
    #    guard, so none writes to the real catalog by default.
    import glob
    offenders = []
    # These read no DB / write no rows, so they are safe even without an override.
    _NO_DB = {"test_version.py", "test_hvif.py", "test_cache.py",
              "test_db_pragmas.py", "test_parser_hardening.py",
              "test_repo_proxy_prune.py", "test_db_guard.py",
              # driven by an outer harness that sets the DB (seed + explicit URL)
              "test_flow.py", "test_frontend.py", "test_security.py",
              "test_admin.py", "test_ops.py", "test_repo_proxy.py"}
    for f in sorted(glob.glob("test_*.py")):
        base = os.path.basename(f)
        if base in _NO_DB:
            continue
        src = open(f).read()
        if "SPRITZ_DB_URL" not in src and "test_db_guard" not in src:
            offenders.append(base)
    assert not offenders, f"these tests may touch spritz.db: {offenders}"
    print("no test writes to the real catalog by default -> ok")

    for s in ("", "-wal", "-shm"):
        pathlib.Path("test_db_guard.db" + s).unlink(missing_ok=True)
    print("\nPASS: test DB-safety guard")
