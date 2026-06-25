# Running spritz in WSL

Tested target: WSL2 with Ubuntu, Python 3.11+.

## 1. Run the registry server

```bash
# from the repository root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python seed.py                 # populate the cache from sample-bacaro/
uvicorn app.main:app --reload  # serves on http://localhost:8000
```

After `source .venv/bin/activate`, the venv's `python` is on PATH. This box
has no bare `python3`-less `python`, so the venv activation matters: run the
commands below inside the activated venv.

Open `http://localhost:8000/docs` in your Windows browser. WSL2 forwards
localhost automatically, so the Windows browser reaches the WSL server with
no extra config. If it does not, find the WSL IP with `hostname -I` and use
that instead.

Run the end-to-end test (no network, in-process):

```bash
python test_flow.py
```

## 2. Spike: does `package_repo` build here?

This gates the repo-proxy layer (`docs/tasks/01-repo-proxy.md`). The HPKR
catalog is a Haiku-specific binary format produced by the `package_repo`
tool. We need it on the Linux/WSL side to generate repos without a Haiku
machine in the loop.

The tool lives in Haiku's source as a host build tool. Investigate building
just the host tools (`package`, `package_repo`) from the Haiku tree or
buildtools, for Linux. Steps to try and document the result of:

```bash
# clone shallow, do not build the whole OS, only the host tools
git clone --depth 1 https://github.com/haiku/haiku.git
# the package tools are under src/tools/ ; check the jam targets for
# host-side package_repo. Document whether it builds standalone on Linux.
```

If it does not build standalone, the fallback is a Haiku VM that runs the
repo-build step, or a from-scratch HPKR writer (large, avoid if possible).
Record the finding in `docs/DECISIONS.md`.

## 3. Reset

The dev DB is `spritz.db` (SQLite, gitignored). Delete it to start clean,
then re-run `python seed.py`.

## Note on the native daemon

The native Haiku client/daemon cannot run in WSL (it needs BeAPI and
packagefs). WSL covers the registry server, the repo-proxy layer, and the
web frontend. The daemon is developed and tested on a Haiku machine or VM.
