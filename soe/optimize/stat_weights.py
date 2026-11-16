"""Stat weights: how much each common gear stat is worth to this build, measured in PoB.

Each stat line is added to an equipped jewellery piece (all its mods are global) and calculated with
PoB's what-if calculator, so the build itself never changes. ~40 stats take well under a second.
"""
from __future__ import annotations

from soe.advisor.checkup import join_item, split_item
from soe.optimize.objective import Objective

# (label, stat line as it appears on items, amount for the label)
STATS = [
    ("+10 maximum Life", "+10 to maximum Life"),
    ("+10 maximum Energy Shield", "+10 to maximum Energy Shield"),
    ("+10 maximum Mana", "+10 to maximum Mana"),
    ("+10 Spirit", "+10 to Spirit"),
    ("5% increased maximum Life", "5% increased maximum Life"),
    ("10% increased Energy Shield", "10% increased maximum Energy Shield"),
    ("+100 Armour", "+100 to Armour"),
    ("+100 Evasion", "+100 to Evasion Rating"),
    ("10% increased Armour", "10% increased Armour"),
    ("10% increased Evasion", "10% increased Evasion Rating"),
    ("+10 Strength", "+10 to Strength"),
    ("+10 Dexterity", "+10 to Dexterity"),
    ("+10 Intelligence", "+10 to Intelligence"),
    ("+10% Fire Resistance", "+10% to Fire Resistance"),
    ("+10% Cold Resistance", "+10% to Cold Resistance"),
    ("+10% Lightning Resistance", "+10% to Lightning Resistance"),
    ("+10% Chaos Resistance", "+10% to Chaos Resistance"),
    ("10% increased Damage", "10% increased Damage"),
    ("10% increased Attack Damage", "10% increased Attack Damage"),
    ("10% increased Spell Damage", "10% increased Spell Damage"),
    ("10% increased Elemental Damage", "10% increased Elemental Damage"),
    ("10% increased Projectile Damage", "10% increased Projectile Damage"),
    ("10% increased Physical Damage", "10% increased Physical Damage"),
    ("10% increased Fire Damage", "10% increased Fire Damage"),
    ("10% increased Cold Damage", "10% increased Cold Damage"),
    ("10% increased Lightning Damage", "10% increased Lightning Damage"),
    ("10% increased Chaos Damage", "10% increased Chaos Damage"),
    ("Adds 10-20 Physical to Attacks", "Adds 10 to 20 Physical Damage to Attacks"),
    ("Adds 10-20 Fire to Attacks", "Adds 10 to 20 Fire damage to Attacks"),
    ("Adds 10-20 Cold to Attacks", "Adds 10 to 20 Cold damage to Attacks"),
    ("Adds 1-29 Lightning to Attacks", "Adds 1 to 29 Lightning damage to Attacks"),
    ("10% increased Attack Speed", "10% increased Attack Speed"),
    ("10% increased Cast Speed", "10% increased Cast Speed"),
    ("20% increased Critical Hit Chance", "20% increased Critical Hit Chance"),
    ("20% increased Critical Damage Bonus", "20% increased Critical Damage Bonus"),
    ("+1 Level of all Projectile Skills", "+1 to Level of all Projectile Skills"),
    ("+1 Level of all Attack Skills", "+1 to Level of all Attack Skills"),
    ("+1 Level of all Spell Skills", "+1 to Level of all Spell Skills"),
    ("+1 Level of all Minion Skills", "+1 to Level of all Minion Skills"),
    ("+1 Level of all Melee Skills", "+1 to Level of all Melee Skills"),
    ("Penetrate 10% Elemental Resistances", "Damage Penetrates 10% Elemental Resistances"),
    ("+100 Accuracy", "+100 to Accuracy Rating"),
    ("10% increased Movement Speed", "10% increased Movement Speed"),
    ("20% increased Mana Regeneration", "20% increased Mana Regeneration Rate"),
]

CARRIER_SLOTS = ("Amulet", "Ring 1", "Ring 2", "Belt")


def _carrier(pob):
    items = {i["slot"]: i for i in pob.items(active_only=True)}
    for slot in CARRIER_SLOTS:
        if slot in items:
            return slot, items[slot]["raw"]
    return "Amulet", "Rarity: RARE\nStat Carrier\nGold Amulet\nImplicits: 0"


def stat_weights(pob, base: dict, objective: Objective | None = None, extra_lines: list[str] | None = None,
                 only_useful: bool = True) -> dict:
    """Value of each stat line for the loaded build: DPS %, EHP %, objective score and a
    'worth' column = how many of this stat give the same score as +1% DPS (lower = better)."""
    obj = objective or Objective()
    slot, raw = _carrier(pob)
    head, imp, exp = split_item(raw)
    rows, unparsed = [], []
    for label, line in STATS + [(x, x) for x in (extra_lines or [])]:
        if not pob.mod_supported(line):
            unparsed.append(line)
            continue
        w = pob.whatif(slot=slot, item_raw=join_item(head, imp, exp + [line]), exact_slot=True)
        ex = obj.explain(w, base)
        changed = {k: round(w[k] - base[k], 2) for k in ("Life", "EnergyShield", "Mana", "FireResist", "ColdResist",
                                                       "LightningResist", "ChaosResist", "SpiritUnreserved")
                   if abs((w.get(k) or 0) - (base.get(k) or 0)) > 1e-6}
        rows.append({"stat": label, "line": line, **ex, "other": changed})
    rows.sort(key=lambda r: r["score"], reverse=True)
    if only_useful:
        rows = [r for r in rows if abs(r["score"]) > 0.01 or r["other"]]
    return {"carrier_slot": slot, "objective": {"damage": obj.damage, "survive": obj.survive},
            "weights": rows, "not_understood_by_pob": unparsed,
            "note": "Each row adds one stat line on top of current gear. Resistances above cap show 0."}
