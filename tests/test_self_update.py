"""scripts/self_update.py on real local git repos (no network): pulls new commits, keeps local edits."""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "self_update.py"
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="git not installed")


def _load(root: Path):
    spec = importlib.util.spec_from_file_location("self_update_t", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.ROOT = root
    mod.SETTINGS = root / "data" / "user" / "settings.json"
    mod.reinstall_if_needed = lambda before: None  # no pip in tests
    return mod


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    monkeypatch.delenv("SOE_UPDATED", raising=False)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    (work / "a.txt").write_text("1")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "one")
    _git(work, "push", "-q", "origin", "HEAD:main")
    friend = tmp_path / "friend"
    _git(tmp_path, "clone", "-q", str(origin), str(friend))
    return work, friend


def test_pulls_new_commits(repos):
    work, friend = repos
    mod = _load(friend)
    assert mod.update() == 0  # nothing new yet
    (work / "a.txt").write_text("2")
    _git(work, "commit", "-q", "-am", "two")
    _git(work, "push", "-q", "origin", "HEAD:main")
    assert mod.update() == mod.UPDATED and (friend / "a.txt").read_text() == "2"


def test_keeps_local_edits_and_respects_the_switch(repos):
    work, friend = repos
    mod = _load(friend)
    (work / "a.txt").write_text("2")
    _git(work, "commit", "-q", "-am", "two")
    _git(work, "push", "-q", "origin", "HEAD:main")
    (friend / "a.txt").write_text("my edit")
    assert mod.update() == 0 and (friend / "a.txt").read_text() == "my edit"
    _git(friend, "checkout", "-q", "--", "a.txt")
    mod.SETTINGS.parent.mkdir(parents=True)
    mod.SETTINGS.write_text('{"auto_update_app": false}')
    assert mod.update() == 0 and (friend / "a.txt").read_text() == "1"
