"""Gear advice beyond what PoB shows, every number measured in PoB.

- item_analysis: what each mod of an item is worth to this build, free affixes, and whether an Exalted Orb,
  Chaos Orb, Orb of Annulment or Fracturing Orb is worth using on it (odds with the spawn weights from poe2db)
- realistic_item: a rare a player of this level can realistically get for the slot (best base for the level,
  middle tier rolls), with its gain over the current item
- gear_audit: every slot ranked by how much a realistic replacement gains: "which item to replace first"
"""
from __future__ import annotations

from soe.advisor.checkup import join_item, split_item
from soe.items.craft import (MAX_AFFIX, _clean, _item_level, _mod_of, added_tags, can_roll, family, identify,
                             pool_by_group, resolve_ranges)
from soe.optimize.objective import Objective

SKIP_SLOTS = ("Flask", "Charm")
NOTICEABLE = 0.5  # score points; below that a change is noise


def _price(name: str):
    from soe.prices import safe_price

    return safe_price(name)


def _w(session, slot, raw):
    return session.pob.whatif(slot=slot, item_raw=raw, exact_slot=True)


def _lines(exp: list[str]) -> list[int]:
    return [i for i, ln in enumerate(exp) if ln.strip() and _clean(ln) not in ("Corrupted", "Mirrored")]


def _short(ex: dict) -> dict:
    return {k: ex.get(k) for k in ("score", "dps_pct", "ehp_pct", "move_speed_pct") if ex.get(k) is not None}


# ---------------------------------------------------------------------------------------------------------------
def item_analysis(session, slot: str, objective: Objective | None = None) -> dict:
    session._need_build()
    obj = objective or Objective()
    pob, kb = session.pob, session.kb
    real = pob.resolve_slot(slot)
    cur = session.item(slot)
    if cur is None:
        raise ValueError(f"nothing equipped in {slot}")
    head, imp, exp = split_item(cur["raw"])
    ilvl = _item_level(cur["raw"])
    rarity = (cur.get("rarity") or "").upper()
    corrupted = any(_clean(x) == "Corrupted" for x in exp)
    try:
        groups = pool_by_group(kb, cur["base"], ilvl)
    except ValueError:
        groups = {}
    base_tags = set((kb.base(cur["base"]) or {}).get("tags") or [])

    # what each mod is worth: the item without that line
    idx = _lines(exp)
    mods, line_mods = [], {}
    for i in idx:
        ident = identify(exp[i], groups) if groups else []
        line_mods[i] = _mod_of(ident[0], groups) if ident else None
        ex = obj.explain(_w(session, real, join_item(head, imp, exp[:i] + exp[i + 1:])), session.base)
        tags = [t for t in ("fractured", "desecrated", "crafted") if exp[i].startswith("{" + t + "}")]
        mods.append({"line": i, "text": _clean(exp[i]), "type": ident[0][0] if ident else None,
                     "tier": (f"T{ident[0][2]} z {len(groups[(ident[0][0], ident[0][1])])}" if ident and ident[0][2] else None),
                     "family": family(ident[0][1]) if ident else None, "flags": tags,
                     "value": {"score": round(-ex["score"], 2), "dps_pct": -(ex.get("dps_pct") or 0),
                               "ehp_pct": -(ex.get("ehp_pct") or 0)}})
    slot_ex = obj.explain(pob.whatif(slot=real, exact_slot=True), session.base)  # the slot empty
    res = {"slot": real, "item": cur["name"], "base": cur["base"], "rarity": rarity, "item_level": ilvl,
           "corrupted": corrupted, "item_value": {"score": round(-slot_ex["score"], 2),
                                                  "dps_pct": -(slot_ex.get("dps_pct") or 0),
                                                  "ehp_pct": -(slot_ex.get("ehp_pct") or 0)},
           "mods": sorted(mods, key=lambda m: m["value"]["score"], reverse=True)}
    counts = {"Prefix": sum(m["type"] == "Prefix" for m in mods), "Suffix": sum(m["type"] == "Suffix" for m in mods)}
    unknown = sum(m["type"] is None for m in mods)
    res["affixes"] = {**counts, "unknown": unknown,
                      "open_prefix": max(0, MAX_AFFIX["Prefix"] - counts["Prefix"]),
                      "open_suffix": max(0, MAX_AFFIX["Suffix"] - counts["Suffix"])}
    if unknown and counts["Prefix"] + counts["Suffix"] + unknown >= 6:  # a line we cannot name still takes a slot
        res["affixes"]["open_prefix"] = res["affixes"]["open_suffix"] = 0
    if corrupted or rarity != "RARE" or not groups:
        why = ("Item jest skorumpowany: żadna waluta go już nie zmieni." if corrupted else
               "Unikat: nie da się go craftować walutą (zostają korupcja i runy)." if rarity == "UNIQUE" else
               "Crafting liczę tylko dla rare." if rarity != "RARE" else "Brak puli modów dla tej bazy.")
        res["crafting"] = {"possible": False, "why": why}
        return res

    def present_families(skip: int | None):
        return {family(m["grp"]) for i, m in line_mods.items()
                if m and i != skip and not exp[i].startswith("{crafted}")}

    def outcomes(types: set[str], skip: int | None):
        """Every mod family a random new mod can be (weighted by its tiers' spawn weights from poe2db), measured with
        the line `skip` replaced."""
        tags = base_tags | added_tags([m for i, m in line_mods.items() if m and i != skip])
        fams = present_families(skip)
        out = []
        for (atype, grp), tiers in groups.items():
            if atype not in types or family(grp) in fams:
                continue
            typical = tiers[len(tiers) // 2]
            if not can_roll(typical, tags):
                continue
            new = [resolve_ranges(p, "mid") for p in typical["text"].split(" / ")]
            lines = exp[:skip] + new + exp[skip + 1:] if skip is not None else exp + new
            ex = obj.explain(_w(session, real, join_item(head, imp, lines)), session.base)
            out.append({"text": " / ".join(new), "type": atype, "weight": sum(t.get("w", 1) for t in tiers), **_short(ex)})
        return out

    def summarize(outs: list[dict], cost_name: str, extra: dict | None = None) -> dict:
        total = sum(o["weight"] for o in outs) or 1
        good = [o for o in outs if o.get("score", 0) > NOTICEABLE]
        ev = sum(o.get("score", 0) * o["weight"] for o in outs) / total
        gw = sum(o["weight"] for o in good)
        r = {"chance_pct": round(gw / total * 100, 1), "expected_score": round(ev, 2),
             "gain_if_good": round(sum(o["score"] * o["weight"] for o in good) / gw, 2) if gw else 0,
             "best": sorted(good, key=lambda o: o["score"], reverse=True)[:5], "price": _price(cost_name),
             "possible_outcomes": len(outs)}
        if extra:
            r.update(extra)
        return r

    craft: dict = {"possible": True}
    open_types = {t for t, k in (("Prefix", "open_prefix"), ("Suffix", "open_suffix")) if res["affixes"][k] > 0}
    if open_types:
        o = summarize(outcomes(open_types, None), "Exalted Orb")
        o["verdict"] = ("raczej nie" if o["chance_pct"] < 10 or o["gain_if_good"] < 1 else
                        "mały zysk" if o["gain_if_good"] < 3 else "warto" if o["chance_pct"] >= 30 else "loteria")
        craft["exalt"] = o
    # Chaos Orb: removes a random mod (not fractured) and adds a random one of the same kind
    removable = [m for m in mods if "fractured" not in m["flags"] and m["type"]]
    if removable:
        all_outs, per_mod = [], []
        for m in removable:
            outs = outcomes({m["type"]}, m["line"])
            total = max(1, sum(y["weight"] for y in outs))
            for x in outs:  # each removable mod is equally likely to go, then one random mod of its kind comes
                all_outs.append({**x, "weight": x["weight"] / total, "removes": m["text"]})
            per_mod.append(m["text"])
        o = summarize(all_outs, "Chaos Orb")
        o["verdict"] = ("warto" if o["chance_pct"] >= 30 and o["expected_score"] > 0 else
                        "ryzykowne" if o["chance_pct"] >= 10 else "raczej nie")
        craft["chaos"] = o
        junk = [m for m in removable if m["value"]["score"] < NOTICEABLE]
        craft["annul"] = {"chance_pct": round(len(junk) / len(removable) * 100, 1),
                          "junk_mods": [m["text"] for m in junk], "price": _price("Orb of Annulment"),
                          "verdict": "warto" if len(junk) / len(removable) >= 0.5 else "ryzykowne" if junk else "nie"}
    fractured = any("fractured" in m["flags"] for m in mods)
    if len(mods) >= 4 and not fractured:
        best = mods[0]
        junk = [m for m in mods if m["value"]["score"] < NOTICEABLE]
        craft["fracture"] = {"best_mod": best["text"], "best_value": best["value"],
                             "chance_best_pct": round(100 / len(mods), 1),
                             "chance_junk_pct": round(len(junk) / len(mods) * 100, 1),
                             "price": _price("Fracturing Orb"),
                             "verdict": ("warto" if best["value"]["score"] >= 5 and len(junk) <= 1 else
                                         "loteria" if best["value"]["score"] >= 5 else "nie")}
    res["crafting"] = craft
    res["note"] = ("Odds use the spawn weights from poe2db (equal weights when poe2db has no page for the base). "
                   "Outcomes use a middle tier with a middle roll. 'value' = what you lose without the mod.")
    return res


# ---------------------------------------------------------------------------------------------------------------
def _make_raw(base: dict, ilvl: int, mods: list[str], keep_head: list[str], keep_imp: list[str]) -> str:
    implicit = [resolve_ranges(x, "mid") for x in (base.get("implicit") or "").split("\n") if x.strip()]
    head = ["Rarity: RARE", "Realistyczny item", base["name"], f"Item Level: {ilvl}", *keep_head,
            f"Implicits: {len(keep_imp) + len(implicit)}"]
    return "\n".join(head + keep_imp + implicit + mods)


def realistic_item(session, slot: str, objective: Objective | None = None, level: int | None = None,
                   cur: dict | None = None) -> dict | None:
    """A rare for this slot that a character of this level can realistically get: bases it can wear,
    3 prefixes + 3 suffixes at a middle tier with middle rolls, chosen for this build."""
    session._need_build()
    obj = objective or Objective()
    pob, kb = session.pob, session.kb
    real = pob.resolve_slot(slot)
    cur = cur or session.item(slot)
    if cur is None:
        return None
    cur_base = kb.base(cur["base"])
    if not cur_base:
        return None
    level = level or int(session.base.get("level") or 1)
    ilvl = max(1, min(level, 82))
    head, imp, exp = split_item(cur["raw"])
    keep_head = [h for h in head if h.startswith(("Quality:", "Sockets:", "Rune:"))]
    keep_imp = [x for x in imp if x.startswith(("{rune}", "{enchant}"))]
    try:
        groups = pool_by_group(kb, cur_base["name"], ilvl)
    except ValueError:
        return None
    tags0 = set(cur_base.get("tags") or [])

    # value of each mod family alone on the current base (mid tier, mid roll)
    empty = _make_raw(cur_base, ilvl, [], keep_head, keep_imp)
    base_score = obj.score(_w(session, real, empty), session.base)
    singles = []
    for (atype, grp), tiers in groups.items():
        typical = tiers[len(tiers) // 2]
        if not can_roll(typical, tags0):
            continue
        lines = [resolve_ranges(p, "mid") for p in typical["text"].split(" / ")]
        sc = obj.score(_w(session, real, _make_raw(cur_base, ilvl, lines, keep_head, keep_imp)), session.base)
        singles.append((sc - base_score, atype, grp, typical, lines))
    singles.sort(key=lambda s: s[0], reverse=True)
    chosen, fams, counts, gains = [], set(), {"Prefix": 0, "Suffix": 0}, {}
    for gain, atype, grp, mod, lines in singles:
        if counts[atype] >= MAX_AFFIX[atype] or family(grp) in fams:
            continue
        if not can_roll(mod, tags0 | added_tags([c[0] for c in chosen])):
            continue
        chosen.append((mod, lines, atype))
        gains[mod["id"]] = gain
        fams.add(family(grp))
        counts[atype] += 1
    mod_lines = [ln for _, lines, _ in chosen for ln in lines]

    # bases of the same kind the character can wear at this level
    cands = kb._rows("SELECT * FROM bases WHERE type = ? AND hidden = 0", (cur_base["type"],))
    cands = [b for b in cands if (b.get("sub_type") == cur_base.get("sub_type"))
             and ((b.get("req") or {}).get("level") or 1) <= level]
    best = None
    for b in cands or [cur_base]:
        btags = set(b.get("tags") or [])
        ok = [ln for mod, lines, _ in chosen if can_roll(mod, btags) for ln in lines]
        raw = _make_raw(b, ilvl, ok, keep_head, keep_imp)
        ex = obj.explain(_w(session, real, raw), session.base)
        if best is None or ex["score"] > best[0]["score"]:
            best = (ex, b, raw, ok)
    ex, b, raw, ok = best
    return {"slot": real, "current": cur["name"], "base": b["name"], "base_level": (b.get("req") or {}).get("level") or 1,
            "item_level": ilvl,
            "mods": [{"type": t, "text": " / ".join(lines), "id": m["id"], "group": m["grp"], "level": m["level"],
                      "gain": round(gains.get(m["id"], 0), 2)}
                     for m, lines, t in chosen if all(ln in ok for ln in lines)],
            "implicit": [resolve_ranges(x, "mid") for x in (b.get("implicit") or "").split("\n") if x.strip()],
            "kept_runes": [_clean(x) for x in keep_imp], **_short(ex), "item_text": raw}


def gear_audit(session, objective: Objective | None = None) -> dict:
    """Every equipped slot: what the item gives now and how much a realistic rare for this level would gain.
    Sorted by that gain: the first row is the item to replace first."""
    session._need_build()
    obj = objective or Objective()
    pob = session.pob
    level = int(session.base.get("level") or 1)
    rows = []
    for it in pob.items(active_only=True):
        if it["slot"].startswith(SKIP_SLOTS):
            continue
        empty = obj.explain(pob.whatif(slot=it["slot"], exact_slot=True), session.base)
        try:
            r = realistic_item(session, it["slot"], obj, level, cur=it)
        except Exception as e:  # noqa: BLE001  one odd item must not hide the others
            r = {"error": f"{type(e).__name__}: {e}"}
        rows.append({"slot": it["slot"], "item": it["name"], "rarity": it.get("rarity"),
                     "item_value": {"score": round(-empty["score"], 2), "dps_pct": -(empty.get("dps_pct") or 0),
                                    "ehp_pct": -(empty.get("ehp_pct") or 0)},
                     "realistic": r})
    rows.sort(key=lambda r: ((r["realistic"] or {}).get("score") or -1e9), reverse=True)
    return {"level": level, "slots": rows,
            "note": ("'realistic' = a rare with 3 prefixes + 3 suffixes at a middle tier and middle roll, on the best base "
                     "this character can wear, mods picked for this build (items for this level, not mirror tier). "
                     "Its score/% are vs your current item. item_value = what the item gives now (vs an empty slot).")}
