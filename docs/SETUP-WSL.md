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

## 2. Build the Haiku host tools (`package`, `package_repo`)

This gates the repo-proxy layer (`docs/tasks/01-repo-proxy.md`). The HPKR
catalog is a Haiku-specific binary format produced by the `package_repo` tool.
We generate it on the Linux/WSL side, no Haiku machine in the loop.

**Confirmed working** on Debian 12 / WSL2 with gcc 12. Procedure:

```bash
# prerequisites (Debian/Ubuntu)
sudo apt-get install -y bison flex texinfo zstd nasm xorriso mtools \
    gettext autoconf automake   # zlib + zstd dev headers also required

# 1. build Haiku's own jam (the stock jam misbehaves on Haiku jamfiles)
git clone --depth 1 https://github.com/haiku/buildtools.git
( cd buildtools/jam && make )            # produces ./jam0
export PATH="$PWD/buildtools/jam:$PATH"   # or copy jam0 -> ~/bin/jam

# 2. Haiku source (shallow; ~300 MB)
git clone --depth 1 https://github.com/haiku/haiku.git
cd haiku

# 3. configure for host tools only (no cross-tools, no OS image)
./configure --host-only

# 4. build the host tools we use
jam -q '<build>package'
jam -q '<build>package_repo'
jam -q '<build>hvif2png'      # needs libpng-dev; renders Haiku HVIF icons to PNG
# binaries land under:
#   generated/objects/linux/x86_64/release/tools/package/package
#   generated/objects/linux/x86_64/release/tools/package_repo/package_repo
#   generated/objects/linux/x86_64/release/tools/hvif2png/hvif2png
# run them with LD_LIBRARY_PATH=generated/objects/linux/lib
```

`hvif2png` powers `/icon/{id}` (icon extraction from hpkg); point
`SPRITZ_HVIF2PNG_BIN` at it. It is optional: without it the frontend just uses
the generated placeholder.

**One source fix is needed** under gcc 12: `src/kits/storage/sniffer/
RPattern.cpp` uses `offsetof` without including `<cstddef>`, which is a fatal
error on modern gcc. Add `#include <cstddef>` at the top of that file before
step 4. (Upstreamable; trivial.)

Findings recorded in `docs/DECISIONS.md`: the tools build off-Haiku (no VM
needed for the build step), and `package_repo` enforces a strict vendor-match
(every package's vendor must equal the repo's vendor, no override), which
forces a per-vendor sub-repo layout in the proxy.

## 3. Reset

The dev DB is `spritz.db` (SQLite, gitignored). Delete it to start clean,
then re-run `python seed.py`.

## Note on the native daemon

The native Haiku client/daemon cannot run in WSL (it needs BeAPI and
packagefs). WSL covers the registry server, the repo-proxy layer, and the
web frontend. The daemon is developed and tested on a Haiku machine or VM.
