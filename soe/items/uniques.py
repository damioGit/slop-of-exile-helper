"""Unique items for a build: try one ("I like unique X") or rank every unique that fits a slot.

Each unique is put in the slot with PoB's what-if calculator (current variant, mid rolls as PoB
reads ranges), so the build is never changed. Lines PoB cannot calculate are listed, because many
uniques do things PoB does not model; those are judged by hand.
"""
from __future__ import annotations

import re

from soe.advisor.session import diff
from soe.optimize.objective import Objective

# item base type -> equipment slots it can go in
TYPE_SLOTS = {
    "Ring": ["Ring 1", "Ring 2"], "Amulet": ["Amulet"], "Belt": ["Belt"], "Body Armour": ["Body Armour"],
    "Helmet": ["Helmet"], "Gloves": ["Gloves"], "Boots": ["Boots"],
    "Shield": ["Weapon 2"], "Focus": ["Weapon 2"], "Quiver": ["Weapon 2"], "Buckler": ["Weapon 2"],
}
_TAGS = re.compile(r"\{[^}]*\}")


def _slots_for(session, base_type: str) -> list[str]:
    if base_type in TYPE_SLOTS:
        return TYPE_SLOTS[base_type]
    # weapons: main hand; off hand too if the build holds that type there now
    slots = ["Weapon 1"]
    off = session.item("Weapon 2")
    if off and session.kb.base(off["base"]) and session.kb.base(off["base"])["type"] == base_type:
        slots.append("Weapon 2")
    return slots


def _unsupported(pob, unique_row: dict) -> list[str]:
    from soe.items.craft import resolve_ranges

    lines = [_TAGS.sub("", x).strip() for x in unique_row["implicits"] + unique_row["mods"]]
    return [ln for ln in lines if ln and not pob.mod_supported(resolve_ranges(ln, "mid"))]


def _evaluate(session, row: dict, slot: str, obj: Objective) -> dict:
    w = session.pob.whatif(slot=slot, item_raw=row["raw"])
    w.pop("points", None)
    return {"slot": session.pob.resolve_slot(slot), **obj.explain(w, session.base), "changes": diff(session.base, w)}


def try_unique(session, name: str, slot: str | None = None, objective: Objective | None = None) -> dict:
    """Put a unique in the build (best fitting slot unless given) and report what changes."""
    session._need_build()
    obj = objective or Objective()
    rows = session.kb.unique(name)
    if not rows:
        raise ValueError(f"no unique named {name!r}")
    row = rows[0]
    base = session.kb.base(row["base"])
    btype = base["type"] if base else None
    slots = [slot] if slot else _slots_for(session, btype)
    results = [_evaluate(session, row, s, obj) for s in slots]
    best = max(results, key=lambda r: r["score"])
    current = session.item(best["slot"])
    unsupported = _unsupported(session.pob, row)
    notes = []
    if unsupported:
        notes.append("PoB does not calculate these lines, so their value is not in the numbers: " + "; ".join(unsupported))
    if best["penalty"]:
        notes.append("The swap breaks something (resistances below previous level, attributes or Spirit); "
                     "see changes and fix it elsewhere before judging the unique.")
    if row.get("req_level") and session.base.get("level", 100) < row["req_level"]:
        notes.append(f"Requires level {row['req_level']}.")
    return {"unique": row["name"], "base": row["base"], "base_type": btype,
            "replaces": current["name"] if current else None, **best,
            "other_slots": [{k: r[k] for k in ("slot", "score", "dps_pct", "ehp_pct")} for r in results if r is not best],
            "unique_mods": row["implicits"] + row["mods"], "notes": notes}


def rank_uniques(session, slot: str, objective: Objective | None = None, limit: int = 15) -> dict:
    """Every unique that fits the item type currently in `slot`, ranked against the current item."""
    session._need_build()
    obj = objective or Objective()
    cur = session.item(slot)
    if cur is None:
        raise ValueError(f"nothing equipped in {slot}; try_unique works for empty slots")
    base = session.kb.base(cur["base"])
    btype = base["type"] if base else None
    rows = []
    seen = set()
    for row in session.kb.uniques_for_base_type(btype):
        if row["name"] in seen:
            continue
        seen.add(row["name"])
        r = _evaluate(session, row, slot, obj)
        unsupported = _unsupported(session.pob, row)
        rows.append({"unique": row["name"], "base": row["base"], "score": r["score"], "dps_pct": r["dps_pct"],
                     "ehp_pct": r["ehp_pct"], "penalty": r["penalty"], "req_level": row["req_level"],
                     **({"not_calculated": unsupported} if unsupported else {})})
    rows.sort(key=lambda x: x["score"], reverse=True)
    return {"slot": session.pob.resolve_slot(slot), "current": cur["name"], "base_type": btype,
            "checked": len(rows), "ranking": rows[:limit],
            "note": "score vs the current item (0 = equal). Uniques are calculated with PoB's default rolls, so "
                    "the same unique you already wear can score below your own copy. Penalties mean the unique drops "
                    "resistances, attributes or Spirit you had; 'not_calculated' lines are invisible to PoB."}
