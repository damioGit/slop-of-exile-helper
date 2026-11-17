import os
import tempfile
from pathlib import Path

import pytest

BUILDS = Path(__file__).parent / "builds"

# tests never call poe.ninja: prices come from an empty offline cache unless a test builds its own
os.environ["SOE_PRICES_OFFLINE"] = "1"
os.environ["SOE_PRICES_DIR"] = tempfile.mkdtemp(prefix="soe-prices-")
os.environ["SOE_LEAGUE"] = "Test League"
# nor poe2db: saved pages in data/poe2db are used when present, else PoB data with equal weights
os.environ["SOE_POE2DB"] = "offline"


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
