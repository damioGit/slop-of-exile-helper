"""The repo is public: no tokens, session cookies, passwords, e-mail addresses or home-folder paths in tracked files."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "GitHub token": r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}",
    "Anthropic / OpenAI key": r"(?<![A-Za-z0-9_-])sk-(ant-)?[A-Za-z0-9_-]{20,}",
    "AWS key": r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}",
    "PoE session cookie": r"POESESSID\s*[=:]\s*['\"]?[0-9a-f]{16,}",
    "password": r"(?i)(password|passwd|haslo|hasło)\s*[=:]\s*['\"][^'\"]{4,}['\"]",
    "e-mail": r"[A-Za-z0-9._%+-]+@(gmail|outlook|hotmail|yahoo|wp|o2|onet|interia)\.[a-z]{2,}",
    "home folder": r"[A-Za-z]:[\\/]+Users[\\/]+(?!<|\{|%|USER|\$)[A-Za-z0-9._-]+",
}


@pytest.mark.skipif(not shutil.which("git"), reason="git not installed")
def test_tracked_files_have_no_secrets():
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    found = []
    for name in filter(None, files):
        p = ROOT / name
        if not p.is_file() or p.suffix in (".png", ".ico", ".lnk", ".zst"):
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for what, rx in PATTERNS.items():
            for m in re.finditer(rx, text):
                found.append(f"{name}: {what}: {m.group(0)[:40]}")
    assert not found, "\n".join(found)
