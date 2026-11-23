"""Step-by-step craft of the realistic item for a slot: base, Transmutation, Essence, Exalted Orbs,
with odds (Monte Carlo over the mod pool, spawn weights from poe2db) and the cost of the orbs from poe.ninja.

PoE2 rules used: Orb of Transmutation makes a normal item magic with one mod; an Essence (Lesser / normal /
Greater) turns a magic item rare and adds its guaranteed mod; an Exalted Orb adds one random mod while the item
has room (3 prefixes + 3 suffixes). Families and blocking tags are respected (craft.family / can_roll).
"""
from __future__ import annotations

import random

from soe.items.craft import added_tags, can_roll, family, pool_by_group, resolve_ranges
from soe.items.gear import realistic_item
from soe.i18n import t
from soe.optimize.objective import Objective

SIMS = 4000


def _price(name):
    from soe.prices import safe_price

    return safe_price(name)


def _essence_type(base: dict) -> str:
    return "Warstaff" if base.get("sub_type") == "Warstaff" else base.get("type")


def _essences(kb, grp: str, item_type: str, ilvl: int) -> list[dict]:
    rows = kb._rows("SELECT e.name, e.tier_level, m.text AS mod_text, m.level AS mod_level, m.type AS affix "
                    "FROM essences e JOIN mods m ON m.id = e.mod_id AND m.domain = 'Item' "
                    "WHERE m.grp = ? AND e.item_type = ? AND e.name NOT LIKE 'Perfect %' ORDER BY m.level DESC",
                    (grp, item_type))
    return [r for r in rows if (r["mod_level"] or 0) <= ilvl]


def _simulate(groups, base_tags: set, start: list[dict], wanted: set[str], exalts: int, sims: int, seed: int = 7):
    """Distribution of how many wanted families the random mods hit: one Transmutation mod + `exalts` Exalted Orbs,
    next to the `start` mods (e.g. the essence mod)."""
    entries = [(atype, grp, m) for (atype, grp), tiers in groups.items() for m in tiers]
    rng = random.Random(seed)
    hist = [0] * (exalts + 2)
    for _ in range(sims):
        mods = list(start)
        hits = 0
        for _step in range(1 + exalts):  # the transmute mod comes first, then the exalts
            counts = {"Prefix": sum(m["type"] == "Prefix" for m in mods), "Suffix": sum(m["type"] == "Suffix" for m in mods)}
            fams = {family(m["grp"]) for m in mods}
            tags = base_tags | added_tags(mods)
            pool = [m for atype, grp, m in entries
                    if counts[atype] < 3 and family(grp) not in fams and can_roll(m, tags)]
            if not pool:
                break
            m = rng.choices(pool, weights=[x.get("w", 1) for x in pool])[0]
            mods.append(m)
            if family(m["grp"]) in wanted:
                hits += 1
        hist[hits] += 1
    return hist


def craft_plan(session, slot: str, objective: Objective | None = None, level: int | None = None,
               sims: int = SIMS) -> dict:
    session._need_build()
    obj = objective or Objective()
    kb = session.kb
    target = realistic_item(session, slot, obj, level)
    if not target or not target.get("mods"):
        raise ValueError(f"no craftable target for {slot}")
    base = kb.base(target["base"])
    ilvl = target["item_level"]
    need_ilvl = max((m["level"] or 1) for m in target["mods"])
    groups = pool_by_group(kb, base["name"], ilvl)
    base_tags = set(base.get("tags") or [])
    item_type = _essence_type(base)

    # the essence: the most valuable target mod an essence can guarantee
    ess, ess_mod = None, None
    for m in sorted(target["mods"], key=lambda x: x["gain"], reverse=True):
        opts = _essences(kb, m["group"], item_type, ilvl)
        if opts:
            ess, ess_mod = opts[0], m
            break
    if ess_mod:  # the essence fixes this mod's tier: show what it really gives
        ess_mod["text"] = resolve_ranges(ess["mod_text"], "mid")
    wanted = {family(m["group"]) for m in target["mods"] if m is not ess_mod}
    start = []
    if ess_mod:
        tiers = groups.get((ess_mod["type"], ess_mod["group"])) or []
        start = [next((t for t in tiers if t["text"] == ess["mod_text"]), None) or {
            "type": ess_mod["type"], "grp": ess_mod["group"], "adds_tags": [], "weight_keys": [], "weight_vals": []}]
    exalts = 6 - 1 - len(start)  # room left after the transmute mod and the essence mod
    hist = _simulate(groups, base_tags, start, wanted, exalts, sims)
    total = sum(hist) or 1
    at_least = {k: round(sum(hist[k:]) / total * 100, 1) for k in range(1, min(4, len(hist)))}

    p = {n: _price(n) for n in ("Orb of Transmutation", "Exalted Orb", "Orb of Annulment")}
    ess_price = _price(ess["name"]) if ess else None
    steps = [{"orb": target["base"], "kind": "base",
              "title": t(f"Base: {target['base']}, item level {need_ilvl} or higher",
                         f"Baza: {target['base']}, item level co najmniej {need_ilvl}"),
              "detail": t(f"A normal (white) item. Needs character level {target.get('base_level') or 1}. Drop or trade; "
                          "poe.ninja has no base prices, they are usually cheap.",
                          f"Normalny (biały) item. Wymaga {target.get('base_level') or 1} lvl postaci. Drop albo trade; "
                          "ceny baz nie ma na poe.ninja, zwykle są tanie."), "price": None},
             {"orb": "Orb of Transmutation", "kind": "currency", "title": "Orb of Transmutation",
              "detail": t("Makes the base a magic item with one random mod.", "Robi z bazy magic item z jednym losowym modem."),
              "price": p["Orb of Transmutation"]}]
    if ess:
        steps.append({"orb": ess["name"], "kind": "currency", "title": ess["name"],
                      "detail": t(f"Makes the magic item rare and guarantees: {ess['mod_text']} ({ess['affix']}).",
                                  f"Zmienia magic item w rare i daje na pewno: {ess['mod_text']} ({ess['affix']})."),
                      "price": ess_price})
    else:
        steps.append({"orb": "Regal Orb", "kind": "currency", "title": "Regal Orb",
                      "detail": t("No essence gives a goal mod on this base: a Regal makes the magic item rare with a random mod.",
                                  "Żadna esencja nie daje modów z celu na tej bazie: Regal zmienia magic w rare z losowym modem."),
                      "price": _price("Regal Orb")})
    goal = ", ".join(m["text"] for m in target["mods"] if m is not ess_mod)
    steps.append({"orb": "Exalted Orb", "kind": "currency", "title": f"Exalted Orb × {exalts}",
                  "detail": t(f"Each adds a random mod until the item has 6. Goal: {goal}. "
                              "When junk lands, Orb of Annulment removes a random mod (a good one too, so it is a risk).",
                              f"Każdy dodaje losowy mod, aż item ma 6. Cel: {goal}. "
                              "Gdy wypadnie śmieć, Orb of Annulment usuwa losowy mod (też dobry, więc ryzyko)."),
                  "price": p["Exalted Orb"], "count": exalts})
    for name, why in (("Omen of Sinistral Exaltation", t("the next Exalt adds only a prefix", "następny Exalt doda tylko prefix")),
                      ("Omen of Dextral Exaltation", t("the next Exalt adds only a suffix", "następny Exalt doda tylko suffix"))):
        pr = _price(name)
        if pr:
            steps.append({"orb": name, "kind": "tip", "title": name, "detail": t(f"Optional: {why}, when mods of one kind are missing.", f"Opcjonalnie: {why}, kiedy brakuje modów jednego typu."),
                          "price": pr})
    known = [(s.get("price"), s.get("count", 1)) for s in steps if s["kind"] == "currency"]
    cost = sum(pr["divine"] * n for pr, n in known if pr and pr.get("divine") is not None)
    return {"slot": target["slot"], "target": target, "steps": steps,
            "essence_mod": ess_mod["text"] if ess_mod else None,
            "odds": {"wanted_mods": len(wanted), "random_mods": 1 + exalts, "at_least_pct": at_least,
                     "expected_hits": round(sum(i * n for i, n in enumerate(hist)) / total, 2)},
            "cost_divine": round(cost, 3), "cost_complete": all(pr for pr, _ in known),
            "note": ("Odds: Monte Carlo over the mod pool with the spawn weights from poe2db (equal weights when poe2db has "
                     "no page for the base). A 'hit' is the right mod family at any tier. Costs: one try, poe.ninja prices.")}
