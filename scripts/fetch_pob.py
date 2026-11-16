"""Fetch Path of Building (PoE2) at a tag into vendor/.

Shallow, blobless, sparse clone: only src/, runtime/ and spec/ (~430 MB instead of ~1.8 GB).
Usage: python scripts/fetch_pob.py [tag] [dest]   (tag defaults to POB_VERSION, dest to vendor/PathOfBuilding-PoE2)
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git"
DEST = ROOT / "vendor" / "PathOfBuilding-PoE2"


def run(*args, cwd=None):
    print("+", " ".join(str(a) for a in args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def _rm(path: Path):
    def onerror(func, p, _):  # git objects are read-only on Windows
        Path(p).chmod(stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=onerror) if sys.version_info >= (3, 12) else shutil.rmtree(path, onerror=onerror)


def current_tag(dest: Path = DEST) -> str | None:
    if not dest.exists():
        return None
    r = subprocess.run(["git", "describe", "--tags", "--exact-match"], cwd=dest, capture_output=True, text=True)
    return r.stdout.strip() or None


def fetch(tag: str, dest: Path = DEST) -> Path:
    if current_tag(dest) == tag:
        print(f"PoB {tag} already at {dest}")
        return dest
    tmp = dest.with_name(dest.name + ".new")
    if tmp.exists():
        _rm(tmp)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    run("git", "clone", "-q", "--depth", "1", "--branch", tag, "--filter=blob:none", "--sparse", REPO, str(tmp))
    run("git", "sparse-checkout", "set", "src", "runtime", "spec", cwd=tmp)
    # swap only after a complete download, keep the old one until then
    if dest.exists():
        old = dest.with_name(dest.name + ".old")
        if old.exists():
            _rm(old)
        dest.rename(old)
        tmp.rename(dest)
        _rm(old)
    else:
        tmp.rename(dest)
    print(f"PoB {tag} ready at {dest}")
    return dest


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "POB_VERSION").read_text().strip()
    dest = Path(sys.argv[2]) if len(sys.argv) > 2 else DEST
    fetch(tag, dest)


if __name__ == "__main__":
    main()
