"""Crafting tab: the mod pool of a base, and craft routes for mods the player picks."""
import pytest

from soe.items.crafter import craft_bases, craft_pool, craft_routes
from soe.kb.query import KB


@pytest.fixture(scope="module")
def kb(kb_path):
    return KB(kb_path)


def _fam(pool, text, typ=None):
    return next(f for f in pool["families"] if text in f["text"] and (typ is None or f["type"] == typ))


def _want(f, min_level=0):
    return {"group": f["group"], "type": f["type"], "min_level": min_level}


def test_bases_and_pool(kb):
    rings = craft_bases(kb, "Ring")
    assert rings and all(b["type"] == "Ring" for b in rings)
    pool = craft_pool(kb, "Gold Ring", 82)
    cold = _fam(pool, "to Cold Resistance", "Suffix")
    assert cold["tiers"][0]["level"] >= cold["tiers"][-1]["level"]  # T1 = best
    assert any("Thawing" in e["name"] for e in cold["essences"])


def test_essence_only_mods_are_listed(kb):
    body = next(b for b in craft_bases(kb, "Body Armour"))
    pool = craft_pool(kb, body["name"], 82)
    pct = _fam(pool, "increased maximum Life", "Prefix")
    assert pct.get("essence_only") and any(e["perfect"] for e in pct["essences"])


def test_routes_rank_and_essence(kb):
    pool = craft_pool(kb, "Gold Ring", 82)
    wanted = [_want(_fam(pool, "to maximum Life", "Prefix")), _want(_fam(pool, "to Cold Resistance", "Suffix")),
              _want(_fam(pool, "to Lightning Resistance", "Suffix"))]
    r = craft_routes(kb, "Gold Ring", 82, wanted, sims=400)
    assert r["possible"]
    keys = {x["key"] for x in r["routes"]}
    assert {"random", "alchemy", "essence"} <= keys
    ess = next(x for x in r["routes"] if x["key"] == "essence")
    rnd = next(x for x in r["routes"] if x["key"] == "random")
    assert ess["chance_pct"] > rnd["chance_pct"]  # a guaranteed mod is more deterministic
    assert ess["at_least_pct"][1] == 100.0
    best = [x for x in r["routes"] if "najpewniejsza" in (x.get("badges") or [])]
    assert len(best) == 1 and best[0]["key"] != "chaos"
    for x in r["routes"]:
        assert 0 <= x["chance_pct"] <= 100 and x["steps"]
    # finishing on one base and farming cheap bases are compared too, with the cost of stopping at fewer mods
    assert any(x["key"].startswith("loop") for x in r["routes"]) and any(x["key"].startswith("farm") for x in r["routes"])
    real = {x["hits"]: x["expected_divine"] for x in r["realistic"]}
    assert set(real) == {1, 2, 3} and real[1] <= real[2] <= real[3]


def test_perfect_essence_route_for_essence_only_mod(kb):
    body = next(b for b in craft_bases(kb, "Body Armour"))
    pool = craft_pool(kb, body["name"], 82)
    wanted = [_want(_fam(pool, "increased maximum Life", "Prefix")), _want(_fam(pool, "to Cold Resistance", "Suffix"))]
    r = craft_routes(kb, body["name"], 82, wanted, sims=400)
    perf = next(x for x in r["routes"] if x["key"] == "perfect")
    assert perf["chance_pct"] > 0 and any(s["orb"].startswith("Perfect Essence") for s in perf["steps"])
    assert next(x for x in r["routes"] if x["key"] == "random")["chance_pct"] == 0  # it never rolls on its own


def test_impossible_picks(kb):
    pool = craft_pool(kb, "Gold Ring", 82)
    sufs = [f for f in pool["families"] if f["type"] == "Suffix"][:4]
    r = craft_routes(kb, "Gold Ring", 82, [_want(f) for f in sufs], sims=50)
    assert not r["possible"] and any("najwyżej 3" in p for p in r["problems"])
    life = _fam(pool, "to maximum Life", "Prefix")
    r = craft_routes(kb, "Gold Ring", 82, [_want(life, min_level=999)], sims=50)
    assert not r["possible"]
