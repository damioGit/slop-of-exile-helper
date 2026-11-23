"""The Forge (Kuźnia) tab and the loaded build: pick the mods worth crafting for a slot, and measure what a craft target
would give the build (a middle roll of the lowest tier the player accepts, PoB what-if in that slot).
"""
from __future__ import annotations

from soe.advisor.checkup import split_item
from soe.items.craft import pool_by_group, resolve_ranges
from soe.items.gear import _make_raw, _short, _w, realistic_item
from soe.i18n import t
from soe.optimize.objective import Objective

SLOTS_FOR_TYPE = {"Ring": ["Ring 1", "Ring 2"], "Amulet": ["Amulet"], "Belt": ["Belt"], "Helmet": ["Helmet"],
                  "Gloves": ["Gloves"], "Boots": ["Boots"], "Body Armour": ["Body Armour"]}


def slot_for_base(session, base_type: str) -> str | None:
    """Where an item of this type goes in the build: the armour slot, a ring slot, else the slot holding the
    same item type (weapons, off-hands)."""
    for s in SLOTS_FOR_TYPE.get(base_type, []):
        return s
    for it in session.pob.items(active_only=True):
        b = session.kb.base(it.get("base") or "") if it.get("base") else None
        if b and b["type"] == base_type:
            return it["slot"]
    return None


def slot_target(session, slot: str, objective: Objective | None = None) -> dict:
    """The realistic rare for this slot (best base for the level, 3+3 mods for this build) as a Forge goal."""
    session._need_build()
    r = realistic_item(session, slot, objective or Objective())
    if not r or not r.get("mods"):
        raise ValueError(f"no craft goal for {slot}")
    base = session.kb.base(r["base"])
    return {"slot": r["slot"], "base": r["base"], "type": base["type"] if base else None, "item_level": r["item_level"],
            "wanted": [{"group": m["group"], "type": m["type"], "min_level": m["level"] or 0, "text": m["text"]}
                       for m in r["mods"]],
            "gain": {k: r.get(k) for k in ("score", "dps_pct", "ehp_pct")}, "current": r.get("current")}


def target_value(session, slot: str | None, base_name: str, ilvl: int, wanted: list[dict],
                 objective: Objective | None = None) -> dict:
    """What the craft goal gives this build: each wanted mod at the lowest accepted tier with a middle roll."""
    session._need_build()
    kb = session.kb
    base = kb.base(base_name)
    if not base:
        raise ValueError(f"unknown base {base_name!r}")
    slot = slot or slot_for_base(session, base["type"])
    if not slot:
        return {"slot": None, "note": t("Your build has no slot for this item type.", "Twój build nie ma slotu na ten typ itemu.")}
    groups = pool_by_group(kb, base["name"], ilvl)
    lines = []
    for w in wanted:
        tiers = groups.get((w["type"], w["group"])) or []
        ok = [x for x in tiers if (x["level"] or 1) >= int(w.get("min_level") or 0)]
        tier = ok[-1] if ok else (tiers[-1] if tiers else None)  # the lowest tier the player still accepts
        text = tier["text"] if tier else w.get("text")
        if text:
            lines += [resolve_ranges(p, "mid") for p in text.split(" / ")]
    cur = session.item(slot)
    keep_head, keep_imp = [], []
    if cur:
        head, imp, _ = split_item(cur["raw"])
        keep_head = [h for h in head if h.startswith(("Quality:", "Sockets:", "Rune:"))]
        keep_imp = [x for x in imp if x.startswith(("{rune}", "{enchant}"))]
    raw = _make_raw(base, ilvl, lines, keep_head, keep_imp)
    obj = objective or Objective()
    real = session.pob.resolve_slot(slot)
    ex = obj.explain(_w(session, real, raw), session.base)
    return {"slot": real, "current": cur["name"] if cur else None, **_short(ex), "item_text": raw,
            "note": t("The lowest accepted tier of each mod, middle roll; runes and enchants of the current item stay.",
                      "Najniższy akceptowany tier każdego moda, średni roll; runy i enchanty z obecnego itemu zostają.")}
