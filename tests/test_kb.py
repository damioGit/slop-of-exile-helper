"""Knowledge base built from PoB data (built once per test session into a temp file)."""
import pytest

from soe.kb.build import parse_unique
from soe.kb.query import KB, can_support, type_expr_match


@pytest.fixture(scope="module")
def kb(kb_path):
    return KB(kb_path)


def test_meta(kb):
    m = kb.meta()
    assert m["pob_version"].startswith("v")
    assert m["tree_version"]


def test_gem_lookup(kb):
    g = kb.gem("fireball")
    assert g["name"] == "Fireball" and g["kind"] == "active"
    assert "Spell" in g["skill_types"] and "fire" in g["tags"]
    assert any("Fire Damage" in line for line in g["stats_text"])


def test_gem_lookup_falls_back_to_search(kb):
    assert kb.gem("twister")["name"] == "Twister"  # case-insensitive exact
    assert kb.gem("Garukhan")["name"] == "Garukhan's Resolve"  # prefix via full-text search
    assert kb.gem("Twister")["gem_type"] == "Attack"


def test_support_text(kb):
    ef = kb.gem("Elemental Focus")
    assert ef["kind"] == "support"
    assert "Supported Skills deal 25% more Elemental Damage" in ef["stats_text"]


def test_type_expressions():
    assert type_expr_match(["Spell"], {"Spell"})
    assert not type_expr_match(["Spell"], {"Attack"})
    assert type_expr_match(["Spell", "Attack", "OR"], {"Attack"})
    assert not type_expr_match(["Spell", "Attack", "AND"], {"Attack"})
    assert type_expr_match(["Spell", "NOT"], {"Attack"})
    # PoB: any true value left on the stack counts
    assert type_expr_match(["Damage", "Attack"], {"Attack"})


def test_supports_for_real_build(kb):
    names = {s["name"] for s in kb.supports_for("Twister")}
    # every support the Spirit Walker reference build has on Twister must be allowed
    for s in ["Garukhan's Resolve", "Rakiata's Flow", "Prolonged Duration II", "Projectile Acceleration III", "Salvo"]:
        assert s in names
    assert "Rapid Attacks III" not in {s["name"] for s in kb.supports_for("Fireball")}


def test_can_support_exclusions():
    active = {"skill_types": ["Spell", "Damage"], "minion_types": []}
    assert can_support({"require_types": ["Spell"], "exclude_types": []}, active)
    assert not can_support({"require_types": ["Spell"], "exclude_types": ["Damage"]}, active)
    assert not can_support({"require_types": [], "exclude_types": []}, {**active, "cannot_be_supported": True})


def test_unique(kb):
    hh = kb.unique("headhunter")
    assert hh and hh[0]["base"] == "Heavy Belt"
    assert any("Rare monster" in m for m in hh[0]["mods"])


def test_unique_variants_keep_current():
    raw = """Test Unique
Gold Ring
Variant: Old
Variant: Current
Implicits: 1
+10 to Strength
{variant:1}10% old mod
{variant:2}20% new mod
{tags:life}+50 to maximum Life
"""
    p = parse_unique(raw)
    assert p["implicits"] == ["+10 to Strength"]
    assert p["mods"] == ["20% new mod", "+50 to maximum Life"]


def test_mods_by_slot_and_tiers(kb):
    ring_life = kb.mods("maximum Life", slot="ring", affix_type="Prefix")
    assert ring_life and all("ring" in m["spawns_on"] for m in ring_life)
    tiers = kb.mod_tiers(ring_life[0]["grp"], slot="ring", affix_type="Prefix")
    assert tiers[0]["tier"] == 1 and tiers[0]["level"] >= tiers[-1]["level"]
    assert all("ring" in t["spawns_on"] for t in tiers)


def test_search(kb):
    kinds = {r["kind"] for r in kb.search("deflection", limit=30)}
    assert "node" in kinds
    assert kb.search("headhunter")[0]["name"] == "Headhunter"
    assert kb.search("twister", kind="gem")[0]["name"] == "Twister"
    assert kb.search("") == []


def test_tree_and_classes(kb):
    oasis = kb.node("Oasis")[0]
    assert oasis["type"] == "Keystone" and oasis["linked"]
    assert kb.node(oasis["id"])[0]["name"] == "Oasis"
    classes = kb.classes()
    assert "Spirit Walker" in classes["Huntress"]
