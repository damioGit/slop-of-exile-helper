"""Phase 5: uniques, crafting, combo engine."""
import pytest

from soe.advisor.session import Session
from soe.combo.mechanics import MECHANICS, classify, suggest_combos
from soe.items.craft import craft_odds, identify, ideal_item, mod_upgrades, pool_by_group, resolve_ranges
from soe.items.uniques import rank_uniques, try_unique
from soe.optimize.objective import Objective


@pytest.fixture(scope="module")
def s(kb_path, spirit_walker_code):
    sess = Session(kb_path)
    sess.pool_workers = 4
    sess.load(spirit_walker_code, "sw")
    yield sess
    sess.close_pool()


def test_kb_essences_and_pool(s):
    pool = s.kb.mod_pool("Gold Ring", 79)
    assert pool and all(m["type"] in ("Prefix", "Suffix") and m["level"] <= 79 for m in pool)
    assert not any("Energy Shield" in m["text"] and m["grp"].startswith("LocalIncreased") for m in pool)
    life = [m for m in s.kb.mods("maximum Life", slot="ring", affix_type="Prefix")]
    ess = s.kb.essences_for(life[0]["id"])
    assert isinstance(ess, list)


def test_resolve_ranges():
    assert resolve_ranges("+(10-20) to maximum Life") == "+20 to maximum Life"
    assert resolve_ranges("Adds (1-3) to (10-12) Fire", "mid") == "Adds 2 to 11 Fire"


def test_identify_tiers(s):
    g = pool_by_group(s.kb, "Gold Ring", 79)
    life = identify("+46 to maximum Life", g)
    assert life and life[0][:2] == ("Prefix", "IncreasedLife") and life[0][2] > 1
    rarity = identify("36% increased Rarity of Items found", g)  # boosted beyond normal tiers
    assert rarity and all(t == 0 for _, _, t in rarity)
    assert {a for a, _, _ in rarity} == {"Prefix", "Suffix"}


def test_try_unique(s):
    r = try_unique(s, "Andvarius")
    assert r["slot"] in ("Ring 1", "Ring 2") and r["replaces"]
    assert r["penalty"] > 0  # drops resistances below cap
    assert any("does not calculate" not in n or "Rarity" in n for n in r["notes"])
    assert s.pob.summary() == s.base
    with pytest.raises(ValueError):
        try_unique(s, "Definitely Not A Unique")


def test_rank_uniques(s):
    r = rank_uniques(s, "Ring 2", limit=5)
    assert r["checked"] > 10 and r["ranking"]
    scores = [x["score"] for x in r["ranking"]]
    assert scores == sorted(scores, reverse=True)
    assert rank_uniques(s, "Weapon 1")["base_type"] == "Spear"
    assert s.pob.summary() == s.base


def test_mod_upgrades_finds_cold_on_kraken_whorl(s):
    r = mod_upgrades(s, "Ring 2")
    assert not r["corrupted"]
    top = r["upgrades"][0]
    assert "Rarity" in top["replace"] and "Cold damage to Attacks" in top["with"] and top["dps_pct"] > 2
    # the fractured lightning line keeps its family: no second "Adds # Lightning damage to Attacks"
    assert not any("Lightning damage to Attacks" in u["with"] for u in r["upgrades"])
    assert "Adds 1 to 99 Lightning damage to Attacks" in r["not_changeable_or_unknown"]  # fractured


def test_movement_speed_is_valued(s):
    r = mod_upgrades(s, "Boots")
    assert all(u.get("move_speed_pct", 0) >= 0 for u in r["upgrades"])  # never trades speed away
    for u in r["upgrades"]:  # every suggestion is a gain at a realistic roll, the best roll is shown apart
        assert u["score"] > 0 and "top" in u and "odds" in u


def test_ideal_item(s):
    r = ideal_item(s, "Ring 2")
    types = [m["type"] for m in r["mods"]]
    assert types.count("Prefix") <= 3 and types.count("Suffix") <= 3 and len(r["mods"]) == 6
    assert len({m["group"] for m in r["mods"]}) == 6
    assert s.pob.summary() == s.base


def test_craft_odds(s):
    r = craft_odds(s, "Gold Ring", 79, ["IncreasedLife", "FireResistance"])
    assert 0 < r["Prefix"]["chance_pct"] < 100 and 0 < r["Suffix"]["chance_pct"] < 100


def test_classify():
    prod, ben = classify(["Blinds Enemies", "Consumes Whirlwinds to create an additional twister",
                          "25% increased Damage against Shocked Enemies"])
    assert "Blind" in prod and "Whirlwind" in ben and "Shock" in ben
    assert len({m.name for m in MECHANICS}) == len(MECHANICS)


def test_suggest_combos(s):
    r = suggest_combos(s, Objective())
    prod = r["profile"]["produces"]
    assert "Blind" in prod and "Whirlwind" in prod and "Herald" in prod
    assert "gem: Whirling Slash" in prod["Whirlwind"]
    assert {c["config"] for c in r["config_check"]} >= {"conditionEnemyChilled"}
    blind = r["payoffs"]["Blind"]["supports"]
    assert blind and blind[0]["support"] == "Blindside" and blind[0]["dps_pct"] > 10
    assert s.pob.summary() == s.base


def test_mod_blocking_tags(s):
    from soe.items.craft import added_tags, can_roll

    # Voltaic Staff itself blocks every non-lightning spell level; a neutral base shows the mod-to-mod block
    assert "no_cold_spell_mods" in s.kb.base("Voltaic Staff")["tags"]
    staff = set(s.kb.base("Roaring Staff")["tags"])
    pool = s.kb.mod_pool("Roaring Staff", 82)
    light = next(m for m in pool if m["grp"] == "GlobalIncreaseLightningSpellSkillGemLevelWeapon")
    cold = next(m for m in pool if m["grp"] == "GlobalIncreaseColdSpellSkillGemLevelWeapon")
    allsp = next(m for m in pool if m["grp"] == "GlobalIncreaseSpellSkillGemLevelWeapon")
    assert "no_cold_spell_mods" in light["adds_tags"]
    with_light = staff | added_tags([light])
    assert can_roll(cold, staff) and not can_roll(cold, with_light)  # lightning levels block cold levels
    assert can_roll(allsp, with_light)  # tags allow it; the shared mod family does not (see the test below)


def test_skill_level_suffixes_are_one_family():
    from soe.items.craft import family

    # the game allows one "+# to Level of all ... Skills" suffix per item, whatever PoB's group says
    fams = {family(g) for g in ("GlobalIncreaseSpellSkillGemLevelWeapon", "GlobalIncreaseLightningSpellSkillGemLevelWeapon",
                                "GlobalIncreaseMinionSpellSkillGemLevel", "GlobalIncreaseProjectileSkillGemLevelWeapon",
                                "EssenceSpellSkillLevel")}
    assert fams == {"SkillGemLevels"}
    assert family("IncreasedCastSpeed") == "IncreasedCastSpeed"
