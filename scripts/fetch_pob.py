"""Fetch Path of Building (PoE2) at the tag pinned in POB_VERSION into vendor/.

Shallow, blobless, sparse clone: only src/, runtime/ and spec/ (~430 MB instead of ~1.8 GB).
Usage: python scripts/fetch_pob.py [tag]   (tag overrides POB_VERSION, e.g. for launch day)
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2.git"
DEST = ROOT / "vendor" / "PathOfBuilding-PoE2"


def run(*args, cwd=None):
    print("+", " ".join(args))
    subprocess.run(args, cwd=cwd, check=True)


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else (ROOT / "POB_VERSION").read_text().strip()
    if DEST.exists():
        current = subprocess.run(["git", "describe", "--tags"], cwd=DEST, capture_output=True, text=True).stdout.strip()
        if current == tag:
            print(f"PoB {tag} already present")
            return
        shutil.rmtree(DEST)
    DEST.parent.mkdir(parents=True, exist_ok=True)
    run("git", "clone", "-q", "--depth", "1", "--branch", tag, "--filter=blob:none", "--sparse", REPO, str(DEST))
    run("git", "sparse-checkout", "set", "src", "runtime", "spec", cwd=DEST)
    print(f"PoB {tag} ready at {DEST}")


if __name__ == "__main__":
    main()
