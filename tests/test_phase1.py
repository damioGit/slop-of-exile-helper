"""Phase 1: what-if, snapshot/rollback, gems, items, config, all-skill DPS, process pool."""
from pathlib import Path

import pytest

from soe.engine.pob import PoB
from soe.engine.pool import PoBPool

CODE = (Path(__file__).parent / "builds" / "spirit_walker.txt").read_text(encoding="utf-8")
WEAK_SPEAR = "Rarity: NORMAL\nSoaring Spear\n--\n"


@pytest.fixture(scope="module")
def pob():
    p = PoB()
    p.load_code(CODE)
    return p


@pytest.fixture(scope="module")
def base(pob):
    return pob.summary()


def twister_group(pob):
    return next(g for g in pob.groups() if "Twister" in g["skills"])


# ---- what-if ------------------------------------------------------------------
def test_whatif_does_not_change_build(pob, base):
    node = pob.reachable("Notable", 1)[0]
    pob.whatif(add_nodes=[node["id"]], with_path=True)
    pob.whatif(slot="Weapon 1")
    assert pob.summary() == base


def test_whatif_nothing_equals_base(pob, base):
    w = pob.whatif()
    for k in ("TotalDPS", "TotalEHP", "Life", "EnergyShield", "Evasion"):
        assert w[k] == pytest.approx(base[k])


def test_whatif_node_matches_real_allocation(pob):
    for node in pob.reachable("Notable", 5):
        w = pob.whatif(add_nodes=[node["id"]], with_path=True)
        assert w["points"] == node["cost"]
        with pob.trial():
            pob.alloc_node(node["id"])
            real = pob.summary()
        for k in ("TotalDPS", "TotalEHP", "Life", "EnergyShield", "Evasion", "Str", "Dex", "Int"):
            assert w[k] == pytest.approx(real[k], rel=1e-6), (node["name"], k)


def test_whatif_item_matches_real_equip(pob):
    w = pob.whatif(slot="Weapon 1", item_raw=WEAK_SPEAR)
    with pob.trial():
        pob.equip("Weapon 1", WEAK_SPEAR)
        real = pob.summary()
    assert w["TotalDPS"] == pytest.approx(real["TotalDPS"])
    assert 0 < w["TotalDPS"] < 100_000


def test_empty_active_weapon_kills_dps(pob, base):
    # this build uses the second weapon set; 'Weapon 1' must resolve to 'Weapon 1 Swap'
    assert pob.resolve_slot("Weapon 1") == "Weapon 1 Swap"
    assert pob.whatif(slot="Weapon 1")["TotalDPS"] == 0
    assert pob.whatif(slot="Weapon 1", exact_slot=True)["TotalDPS"] == pytest.approx(base["TotalDPS"])


def test_removing_ring_costs_dps(pob, base):
    assert pob.whatif(slot="Ring 2")["TotalDPS"] < base["TotalDPS"]


# ---- snapshot / trial ------------------------------------------------------------
def test_trial_rolls_back(pob, base):
    with pob.trial():
        pob.unequip("Weapon 1")
        assert pob.summary()["TotalDPS"] == 0
    assert pob.summary() == base


# ---- gems ----------------------------------------------------------------------------
def test_groups_and_gems(pob):
    g = twister_group(pob)
    names = [x["name"] for x in g["gems"]]
    assert names[0] == "Twister"
    assert all(x["valid"] for x in g["gems"])
    assert any(x["support"] for x in g["gems"])


def test_disable_support_lowers_dps(pob, base):
    g = twister_group(pob)
    sup = next(i for i, x in enumerate(g["gems"], 1) if x["support"])
    with pob.trial():
        assert pob.set_gem(g["index"], sup, enabled=False)
        assert pob.summary()["TotalDPS"] < base["TotalDPS"]
    assert pob.summary() == base


def test_gem_level_matters(pob, base):
    g = twister_group(pob)
    with pob.trial():
        pob.set_gem(g["index"], 1, level=1)
        assert pob.summary()["TotalDPS"] < base["TotalDPS"]


def test_swap_support(pob, base):
    g = twister_group(pob)
    sup = next(i for i, x in enumerate(g["gems"], 1) if x["support"])
    with pob.trial():
        assert pob.set_gem(g["index"], sup, name="Elemental Focus")
        names = [x["name"] for x in pob.groups()[g["index"] - 1]["gems"]]
        assert "Elemental Focus" in names
        assert pob.summary()["TotalDPS"] != base["TotalDPS"]


def test_invalid_gem_name_reported(pob):
    g = twister_group(pob)
    with pob.trial():
        assert not pob.set_gem(g["index"], 99, name="Definitely Not A Gem")


# ---- config ---------------------------------------------------------------------------
def test_config_boss_setting(pob, base):
    opts = {o["var"]: o for o in pob.config_options()}
    assert opts["enemyIsBoss"]["value"] == "Pinnacle"
    with pob.trial():
        pob.set_config("enemyIsBoss", "None")
        assert pob.summary()["TotalDPS"] > 0
        assert pob.summary()["TotalDPS"] != base["TotalDPS"]
    assert pob.summary() == base


# ---- all skills -----------------------------------------------------------------------
def test_all_skill_dps_matches_poe_ninja(pob, base):
    by_name = {}
    for d in pob.all_skill_dps():  # skills with stat sets / minion skills get one row each
        by_name.setdefault(d["base_name"], []).append(d)

    def near(name, key, value, rel):
        return any(d[key] == pytest.approx(value, rel=rel) for d in by_name[name])

    assert near("Twister", "TotalDPS", 197_000, 0.005)
    assert near("Whirling Slash", "TotalDPS", 8_000, 0.01)
    assert near("Wild Protector", "MinionDPS", 700, 0.05)
    assert pob.summary() == base  # main skill restored


# ---- pool -----------------------------------------------------------------------------
def test_pool_matches_single_instance(pob):
    nodes = [n["id"] for n in pob.reachable("Notable", 6)]
    expected = [pob.whatif(add_nodes=[n], with_path=True) for n in nodes]
    g = twister_group(pob)
    with pob.trial():
        pob.set_gem(g["index"], 1, level=1)
        expected_trial = pob.summary()
    jobs = [{"call": "whatif", "kwargs": {"add_nodes": [n], "with_path": True}} for n in nodes]
    jobs.append({"trial": [["set_gem", {"group": g["index"], "gem": 1, "level": 1}]]})
    jobs.append({"call": "no_such_method"})
    with PoBPool(CODE, workers=2) as pool:
        res = pool.run(jobs)
    assert [r["result"] for r in res[: len(nodes)]] == expected
    assert res[len(nodes)]["result"] == expected_trial
    assert not res[-1]["ok"] and "no_such_method" in res[-1]["error"]
