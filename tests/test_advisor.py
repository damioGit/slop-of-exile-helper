"""Advisor session logic and the MCP server over real stdio."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from soe.advisor.session import Session, diff, metric_key

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def s(kb_path, spirit_walker_code):
    sess = Session(kb_path)
    sess.load(spirit_walker_code, "sw")
    return sess


def test_diff_and_metrics():
    d = diff({"Life": 100, "Mana": 50}, {"Life": 150, "Mana": 50})
    assert d == {"Life": [100, 150, 50, 50.0]}
    assert metric_key("dps") == "CombinedDPS" and metric_key("TotalEHP") == "TotalEHP"
    with pytest.raises(ValueError):
        metric_key("nope")


def test_needs_build(kb_path):
    with pytest.raises(RuntimeError):
        Session(kb_path).overview()


def test_overview(s):
    ov = s.overview()
    assert ov["summary"]["main_skill"] == "Twister"
    assert ov["weapon_set"] == "second (swap)"
    assert ov["config"]["enemyIsBoss"] == "Pinnacle"
    names = {d["name"] for d in ov["skill_dps"]}
    assert {"Twister", "Whirling Slash", "Wild Protector"} <= names
    assert any(i["slot"] == "Weapon 1 Swap" for i in ov["items"])
    assert not any(i["slot"] == "Weapon 1" for i in ov["items"])  # inactive set hidden
    json.dumps(ov)


def test_resolve_node_by_name(s):
    nid = s.resolve_node("Stand and Deliver")
    assert s.pob.node_info(nid)["name"] == "Stand and Deliver"
    with pytest.raises(ValueError):
        s.resolve_node("No Such Node Anywhere")


def test_rank_matches_whatif(s):
    top = s.rank_passives("dps", max_cost=5, limit=5)
    assert top and top[0]["per_point"] >= top[-1]["per_point"]
    w = s.whatif_passives(add=[top[0]["id"]])
    assert w["points"] == top[0]["points"]
    assert w["changes"]["CombinedDPS"][2] == pytest.approx(top[0]["gain"], abs=0.01)


def test_whatif_item_and_unchanged_build(s):
    before = s.pob.summary()
    r = s.whatif_item("Ring 2")
    assert r["changes"]["CombinedDPS"][2] < 0
    assert s.pob.summary() == before


def test_try_changes_rolls_back(s):
    before = s.pob.summary()
    r = s.try_changes([{"op": "set_config", "var": "enemyIsBoss", "value": "None"}])
    assert r["changes"]["CombinedDPS"][2] < 0
    assert s.pob.summary() == before
    with pytest.raises(ValueError):
        s.try_changes([{"op": "rm -rf"}])
    assert s.pob.summary() == before


def test_apply_and_reset(s):
    base = s.base
    r = s.apply_changes([{"op": "alloc_node", "node": "Stand and Deliver"}])
    assert r["changes"]["CombinedDPS"][2] > 0 and r["build_code"]
    assert s.base != base
    assert s.reset() == base


def test_mcp_server_over_stdio(spirit_walker_code, kb_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run():
        params = StdioServerParameters(command=sys.executable, args=["-m", "soe.advisor.server"], cwd=str(ROOT),
                                       env={**os.environ, "SOE_KB": str(kb_path)})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as cs:
                await cs.initialize()
                names = {t.name for t in (await cs.list_tools()).tools}
                assert {"load_build", "build_overview", "try_changes", "rank_passives", "kb_gem"} <= names

                async def call(tool_name, **args):
                    res = await cs.call_tool(tool_name, args)
                    return json.loads("".join(c.text for c in res.content if hasattr(c, "text")))

                loaded = await call("load_build", build=spirit_walker_code)
                assert loaded["main_skill"] == "Twister"
                gem = await call("kb_gem", name="Twister")
                assert gem["name"] == "Twister"
                bad = await call("try_changes", steps=[{"op": "bogus"}])
                assert "error" in bad

    asyncio.run(run())
