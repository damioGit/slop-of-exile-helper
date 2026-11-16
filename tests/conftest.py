from pathlib import Path

import pytest

BUILDS = Path(__file__).parent / "builds"


@pytest.fixture(scope="session")
def kb_path(tmp_path_factory):
    """Knowledge base built once per test run into a temp file."""
    from soe.kb.build import build

    path = tmp_path_factory.mktemp("kb") / "kb.sqlite"
    info = build(path)
    assert info["gems"] > 500 and info["mods"] > 5000 and info["uniques"] > 300 and info["nodes"] > 3000
    return path


@pytest.fixture(scope="session")
def spirit_walker_code():
    return (BUILDS / "spirit_walker.txt").read_text(encoding="utf-8")
