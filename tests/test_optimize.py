"""Optimizers: objective, stat weights, supports (process pool), tree, improvement plan."""
import pytest

from soe.advisor.session import Session
from soe.optimize.objective import Objective
from soe.optimize.plan import improvement_plan
from soe.optimize.stat_weights import stat_weights
from soe.optimize.supports import candidates, optimize_supports
from soe.optimize.tree import optimize_tree


@pytest.fixture(scope="module")
def s(kb_path, spirit_walker_code):
    sess = Session(kb_path)
    sess.pool_workers = 6
    sess.load(spirit_walker_code, "sw")
    yield sess
    sess.close_pool()


BASE = {"CombinedDPS": 100.0, "TotalEHP": 1000.0, "FireResist": 75, "ColdResist": 60, "LightningResist": 75,
        "ChaosResist": 0, "Str": 50, "ReqStr": 40, "Dex": 50, "ReqDex": 0, "Int": 50, "ReqInt": 0,
        "SpiritUnreserved": 5}


def test_objective():
    o = Objective()
    assert o.score(BASE, BASE) == 0
    assert o.score({**BASE, "CombinedDPS": 110.0}, BASE) == pytest.approx(9.53, abs=0.01)
    dmg_only = Objective(damage=1, survive=0)
    assert dmg_only.score({**BASE, "TotalEHP": 2000.0}, BASE) == 0
    # losing resistance below what you had costs; going from 60 to 55 cold costs 5 * 2
    assert o.penalty({**BASE, "ColdResist": 55}, BASE) == 10
    assert o.penalty({**BASE, "FireResist": 80}, BASE) == 0
    assert o.penalty({**BASE, "ReqStr": 60}, BASE) == o.attr_penalty
    assert o.penalty({**BASE, "SpiritUnreserved": -1}, BASE) == o.spirit_penalty


def test_stat_weights(s):
    r = stat_weights(s.pob, s.base, only_useful=False)
    by = {w["stat"]: w for w in r["weights"]}
    assert r["carrier_slot"] == "Amulet" and not r["not_understood_by_pob"]
    assert by["20% increased Critical Hit Chance"]["dps_pct"] > 1
    assert by["5% increased maximum Life"]["ehp_pct"] > 1
    assert by["+10% Fire Resistance"]["score"] == 0  # already over cap
    assert by["+1 Level of all Spell Skills"]["dps_pct"] == 0  # attack build
    assert s.pob.summary() == s.base


def test_support_candidates_respect_rules(s):
    g = next(g for g in s.pob.groups() if g["main"])
    slot = next(x for x in g["gems"] if x["name"] == "Salvo")
    c = candidates(s.kb, "Twister", g["gems"], slot)
    assert "Salvo" not in c and "Rakiata's Flow" not in c  # already in the group
    assert "Elemental Armament II" in c


def test_optimize_supports(s):
    r = optimize_supports(s)
    assert r["skill"] == "Twister" and r["evaluated"] > 100
    assert r["current_supports"]["Rakiata's Flow"]["dps_pct"] < -30  # core support: removing it hurts
    assert r["current_supports"]["Salvo"]["dps_pct"] == 0  # PoB does not model it
    combo = r["best_combination"]
    assert combo and combo["dps_pct"] > 20
    replaced = {x["replace"] for x in combo["swaps"]}
    assert "Rakiata's Flow" not in replaced
    assert len({x["with"] for x in combo["swaps"]}) == len(combo["swaps"])
    assert s.pob.summary() == s.base


def test_optimize_tree(s):
    r = optimize_tree(s, Objective(), max_moves=3)
    assert r["moves"] and r["total"]["score"] > 5
    assert r["points"]["after"] <= max(r["points"]["before"], r["points"]["available"])
    assert r["moves"][0]["add"] == "Stand and Deliver"
    assert s.pob.summary() == s.base
    # applying the steps reproduces the result
    res = s.try_changes(r["apply_steps"])
    assert res["changes"]["CombinedDPS"][3] == pytest.approx(r["total"]["dps_pct"], abs=0.1)


def test_improvement_plan(s):
    r = improvement_plan(s, tree_moves=2)
    kinds = {x["kind"] for x in r["top_changes"]}
    assert {"gem_swap", "respec"} <= kinds
    whats = [x["what"] for x in r["top_changes"]]
    assert len(whats) == len(set(whats))
    assert r["all_together"]["dps_pct"] > max(x["dps_pct"] for x in r["top_changes"])
    assert r["gear_stat_priorities"]
    assert s.pob.summary() == s.base
