"""Keeps the app's own code current from GitHub (the repo in UPDATE_SOURCE).

    python scripts/self_update.py           at launch (start.bat): pull new commits when the option is on
    python scripts/self_update.py --attach  at install (install.bat): turn an unzipped copy into a git checkout

Exit code 5 = the code changed (start.bat then starts again with the new files), 0 = nothing to do or not possible.
Never touches data/, vendor/ or .venv/ (gitignored), never overwrites local edits (pull only when the tracked files
are clean), and never waits for a login at launch (GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never).
A private repo needs access: the installer lets Git ask for a GitHub login once; after that it is remembered.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / "data" / "user" / "settings.json"
UPDATED = 5


def source() -> tuple[str, str] | None:
    f = ROOT / "UPDATE_SOURCE"
    if not f.exists():
        return None
    parts = f.read_text(encoding="utf-8").split()
    return (parts[0], parts[1] if len(parts) > 1 else "main") if parts else None


def auto_enabled() -> bool:
    try:
        return bool(json.loads(SETTINGS.read_text(encoding="utf-8")).get("auto_update_app", True))
    except (OSError, ValueError):
        return True


def git(*args, interactive=False, timeout=60) -> subprocess.CompletedProcess | None:
    if not shutil.which("git"):
        return None
    env = dict(os.environ)
    if not interactive:
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


def head() -> str | None:
    r = git("rev-parse", "HEAD")
    return r.stdout.strip() if r and r.returncode == 0 else None


def reinstall_if_needed(before: str | None):
    r = git("diff", "--name-only", f"{before}..HEAD") if before else None
    changed = r.stdout.split() if r and r.returncode == 0 else ["pyproject.toml"]
    if "pyproject.toml" in changed:
        print("New dependencies: installing...", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(ROOT)], capture_output=True)


def attach() -> int:
    """Installer: link this folder to the GitHub repo so later launches can update it."""
    src = source()
    if not src or (ROOT / ".git").exists():
        return 0
    url, branch = src
    print(f"Linking app updates to {url} ...", flush=True)
    git("init", "-q")
    git("remote", "add", "origin", url)
    r = git("fetch", "-q", "--depth", "50", "origin", branch, interactive=True, timeout=300)
    if not r or r.returncode != 0:
        shutil.rmtree(ROOT / ".git", ignore_errors=True)
        print("App updates unavailable: no access to the repository on GitHub (a private repository needs an\n"
              "invitation and a login). The app works normally; new versions come as a zip.", flush=True)
        return 0
    zipped = (ROOT / "VERSION.txt").read_text(encoding="utf-8").split()[0] if (ROOT / "VERSION.txt").exists() else None
    git("reset", "-q", "--hard", f"origin/{branch}")
    git("branch", "-q", "-M", branch)
    git("branch", "-q", f"--set-upstream-to=origin/{branch}", branch)
    known = zipped and git("cat-file", "-e", f"{zipped}^{{commit}}")
    reinstall_if_needed(zipped if known and known.returncode == 0 else None)  # only when pyproject.toml changed
    print("App updates: on (version " + (head() or "?")[:7] + ").", flush=True)
    return 0


def update() -> int:
    """Launch: pull when the option is on, the folder is a checkout and nothing local would be lost."""
    if os.environ.get("SOE_UPDATED") or not auto_enabled() or not (ROOT / ".git").exists():
        return 0
    if git("status", "--porcelain", "--untracked-files=no") is None:
        return 0
    if (git("status", "--porcelain", "--untracked-files=no").stdout or "").strip():
        return 0  # local edits (a developer's checkout): never pull over them
    f = git("fetch", "-q", timeout=20)
    if not f or f.returncode != 0:
        return 0  # offline or no access: start the version we have
    behind = git("rev-list", "--count", "HEAD..@{u}")
    if not behind or behind.returncode != 0 or behind.stdout.strip() in ("", "0"):
        return 0
    before = head()
    r = git("pull", "-q", "--ff-only", timeout=120)
    if not r or r.returncode != 0:
        return 0
    reinstall_if_needed(before)
    print(f"App updated ({behind.stdout.strip()} changes), starting the new version...", flush=True)
    return UPDATED


if __name__ == "__main__":
    sys.exit(attach() if "--attach" in sys.argv else update())
