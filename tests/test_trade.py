"""Trade search helpers, offline (no requests to the trade site in tests)."""
import soe.prices.trade as tr


def test_norm_matches_trade_text():
    assert tr._norm("+(3-4) to Level of all Lightning Spell Skills") == tr._norm("# to Level of all Lightning Spell Skills")
    assert tr._norm("{fractured}Adds 1 to 99 Lightning damage to Attacks") == "adds # to # lightning damage to attacks"
    assert tr._norm("51% increased Spell Damage") == "#% increased spell damage"


def test_relaxed_lowers_first_number():
    assert tr._relaxed("+5 to Level of all Spell Skills") == "+4 to Level of all Spell Skills"
    assert tr._relaxed("195% increased Spell Damage") == "156% increased Spell Damage"
    assert tr._relaxed("+1 to Level of all Spell Skills") == "+1 to Level of all Spell Skills"


def test_listing_to_pob_text():
    item = {"rarity": "Rare", "name": "Morbid Goad", "typeLine": "Roaring Staff", "ilvl": 69,
            "properties": [{"name": "Quality", "values": [["+20%", 1]]}],
            "grantedSkills": [{"name": "Grants Skill", "values": [["Level 15 Unleash", 0]]}],
            "explicitMods": [{"description": "+4 to Level of all [Lightning|Lightning] [Spell|Spell] Skills"},
                             "82% increased [Spell] Damage"],
            "corrupted": True}
    raw = tr._raw_from_listing(item)
    lines = raw.split("\n")
    assert lines[:4] == ["Rarity: RARE", "Morbid Goad", "Roaring Staff", "Item Level: 69"]
    assert "Quality: 20" in lines and "Implicits: 1" in lines and "Grants Skill: Level 15 Unleash" in lines
    assert "+4 to Level of all Lightning Spell Skills" in lines and "82% increased Spell Damage" in lines
    assert lines[-1] == "Corrupted"


def test_stat_filter_uses_cached_stats(monkeypatch):
    monkeypatch.setattr(tr, "_STATS", {tr._norm("# to Level of all Lightning Spell Skills"): {"explicit": "explicit.stat_1"}})
    assert tr.stat_filter("+3 to Level of all Lightning Spell Skills") == {"id": "explicit.stat_1", "value": {"min": 3.0}}
    assert tr.stat_filter("Some mod the site does not know") is None
