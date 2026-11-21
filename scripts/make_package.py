"""Zip of the app to give to another player: dist/slop-of-exile-helper-<date>-<commit>.zip

Only files tracked by git at HEAD (no data/, vendor/, .venv/, nobody's build or login), without the
author's own desktop shortcut. The receiver unzips it and runs instaluj.bat.
Usage: python scripts/make_package.py   (commit first: uncommitted changes are not in the zip)
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = ("Slop of Exile Helper.lnk", ".claude/", "docs/")
TOP = "slop-of-exile-helper"


def main() -> Path:
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("Uwaga: masz niezatwierdzone zmiany; paczka ma stan z ostatniego commita.", file=sys.stderr)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.strip()
    tar = subprocess.run(["git", "archive", "--format=zip", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    out = ROOT / "dist" / f"{TOP}-{time.strftime('%Y%m%d')}-{commit}.zip"
    out.parent.mkdir(exist_ok=True)
    n = 0
    with zipfile.ZipFile(io.BytesIO(tar)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            if info.is_dir() or info.filename.startswith(SKIP):
                continue
            dst.writestr(f"{TOP}/{info.filename}", src.read(info))
            n += 1
        dst.writestr(f"{TOP}/VERSION.txt", f"{commit} {time.strftime('%Y-%m-%d')}\n")
    print(f"{out}  ({n} plików, {out.stat().st_size // 1024} KB)")
    return out


if __name__ == "__main__":
    main()
