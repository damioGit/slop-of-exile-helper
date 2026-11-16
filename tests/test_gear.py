"""Gear view: mod values, currency advice, realistic items for the level, which slot to replace first."""
import pytest

from soe.advisor.session import Session
from soe.items.gear import gear_audit, item_analysis, realistic_item


@pytest.fixture(scope="module")
def s(kb_path, spirit_walker_code):
    sess = Session(kb_path)
    sess.load(spirit_walker_code, "sw")
    return sess


def test_item_analysis_values_and_crafting(s):
    a = item_analysis(s, "Ring 2")  # Kraken Whorl: 2 prefixes (one fractured), 3 suffixes, a rarity suffix
    assert a["rarity"] == "RARE" and a["item_value"]["score"] > 0
    rarity = next(m for m in a["mods"] if "Rarity" in m["text"])
    assert rarity["value"]["score"] < 0.5  # worth nothing to the build
    assert a["mods"][0]["value"]["score"] >= a["mods"][-1]["value"]["score"]  # most valuable first
    assert a["affixes"]["open_prefix"] == 1 and a["affixes"]["open_suffix"] == 0
    c = a["crafting"]
    assert c["exalt"]["possible_outcomes"] > 0 and 0 <= c["exalt"]["chance_pct"] <= 100
    # the exalt can only add a prefix, and never a second "Adds # Lightning damage to Attacks" (fractured one)
    assert not any("Lightning damage to Attacks" in o["text"] for o in c["exalt"]["best"])
    assert "Rarity" in " ".join(c["annul"]["junk_mods"])
    assert "fracture" not in c  # already has a fractured mod
    assert s.pob.summary() == s.base


def test_unique_cannot_be_crafted(s):
    a = item_analysis(s, "Belt")  # Headhunter
    assert a["crafting"]["possible"] is False


def test_realistic_item_respects_level(s):
    r = realistic_item(s, "Ring 1", level=40)
    assert r["base_level"] <= 40 and r["item_level"] == 40
    assert 1 <= len(r["mods"]) <= 6
    assert sum(m["type"] == "Prefix" for m in r["mods"]) <= 3 and sum(m["type"] == "Suffix" for m in r["mods"]) <= 3


def test_gear_audit_sorted(s):
    g = gear_audit(s)
    scores = [(x["realistic"] or {}).get("score", -1e9) for x in g["slots"]]
    assert scores == sorted(scores, reverse=True)
    assert not any(x["slot"].startswith(("Flask", "Charm")) for x in g["slots"])
    assert s.pob.summary() == s.base
