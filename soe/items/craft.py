"""Crafting help, measured with PoB.

- mod pool of a base at an item level (what can roll, tiers, prefix/suffix)
- ideal_item: the best 3 prefixes + 3 suffixes for this build on the slot's base (top rolls)
- mod_upgrades: which mod of the current item to replace, with what, and the gain
- odds: chance that one random added mod hits the wanted families

Odds use equal weights for every mod that can roll, because PoE2 spawn weights are not in PoB's data.
They show which crafts are realistic, not exact percentages.
"""
from __future__ import annotations

import re

from soe.advisor.checkup import join_item, split_item
from soe.optimize.objective import Objective

_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")
_TAG_PREFIX = re.compile(r"^(\{[^}]*\})+")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")
MAX_AFFIX = {"Prefix": 3, "Suffix": 3}
SLOT_ITEM_TYPE = {"Ring 1": "Ring", "Ring 2": "Ring", "Amulet": "Amulet", "Belt": "Belt", "Helmet": "Helmet",
                  "Gloves": "Gloves", "Boots": "Boots", "Body Armour": "Body Armour"}


def resolve_ranges(text: str, mode: str = "max") -> str:
    """'+(10-20) to Life' -> '+20 to Life' (max) or '+15 to Life' (mid)."""
    def sub(m):
        a, b = float(m.group(1)), float(m.group(2))
        v = b if mode == "max" else (a + b) / 2
        if mode != "max" and a == int(a) and b == int(b):
            v = float(int(v))  # whole-number stats (skill levels, flat values) roll whole numbers
        return str(int(v)) if v == int(v) else f"{v:.1f}"
    return _RANGE.sub(sub, text)


_TEMPLATE_CACHE: dict[str, tuple[re.Pattern, list[tuple[float, float]]]] = {}


def _template(text: str) -> tuple[re.Pattern, list[tuple[float, float]]]:
    """Regex for a rolled line made from a KB mod text, plus the (min, max) of each rolled number.
    Fixed numbers in the text must match exactly."""
    if text in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[text]
    parts, bounds, last = [], [], 0
    for m in _RANGE.finditer(text):
        parts.append(re.escape(text[last:m.start()]))
        parts.append(r"(-?\d+(?:\.\d+)?)")
        bounds.append((float(m.group(1)), float(m.group(2))))
        last = m.end()
    parts.append(re.escape(text[last:]))
    res = (re.compile("^" + "".join(parts) + "$", re.I), bounds)
    _TEMPLATE_CACHE[text] = res
    return res


def _matches(text: str, mod_part: str) -> bool:
    pat, bounds = _template(mod_part)
    m = pat.match(text)
    if not m:
        return False
    for val, (lo, hi) in zip(m.groups(), bounds):
        v = float(val)
        if not (min(lo, hi) <= v <= max(lo, hi)):
            return False
    return True


def _clean(line: str) -> str:
    return _TAG_PREFIX.sub("", line).strip()


def _item_level(raw: str) -> int:
    m = re.search(r"^Item Level: (\d+)", raw, re.M)
    return int(m.group(1)) if m else 82


def _essences(kb, mod_id: str, slot: str) -> list[str]:
    """Essences that guarantee this mod on this slot's item type, with poe.ninja price when listed."""
    from soe.prices import safe_price

    out = []
    for e in kb.essences_for(mod_id):
        if e["item_type"] == SLOT_ITEM_TYPE.get(slot, e["item_type"]) and e["name"] not in [x.split(" (")[0] for x in out]:
            pr = safe_price(e["name"])
            out.append(f"{e['name']} ({pr['text']})" if pr else e["name"])
    return out[:2]


def pool_by_group(kb, base: str, ilvl: int) -> dict[tuple[str, str], list[dict]]:
    """(affix type, group) -> tiers, best (highest level) first."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for m in kb.mod_pool(base, ilvl):
        groups.setdefault((m["type"], m["grp"]), []).append(m)
    for v in groups.values():
        v.sort(key=lambda m: m["level"] or 0, reverse=True)
    return groups


def identify(line: str, groups) -> list[tuple[str, str, int]]:
    """Every (affix type, group, tier) a rolled line can be, with the value inside the tier's range.
    Single-line mods win over a part of a hybrid mod. Empty: not from the normal mod pool
    (desecrated, essence-only, corrupted or rolled above normal tiers)."""
    text = _clean(line)
    single, hybrid, loose = [], [], []
    for (atype, grp), tiers in groups.items():
        for t, m in enumerate(tiers, 1):
            parts = m["text"].split(" / ")
            if any(_matches(text, p) for p in parts):
                (single if len(parts) == 1 else hybrid).append((atype, grp, t))
                break
        else:
            # same wording, value outside every tier (quality/catalysts on jewellery, special crafts): tier 0
            if any(_template(p)[0].match(text) for m in tiers for p in m["text"].split(" / ") if len(m["text"].split(" / ")) == 1):
                loose.append((atype, grp, 0))
    return single or hybrid or loose


def _mod_lines(mod: dict) -> list[str]:
    return [resolve_ranges(p) for p in mod["text"].split(" / ")]


def mod_weight(mod: dict, tags: set) -> float:
    """The game's spawn rule: the first weight key in the mod's list that the item has decides
    (0 = cannot roll). Item tags = base tags + tags added by mods already on it (e.g. no_cold_spell_mods)."""
    for k, v in zip(mod.get("weight_keys") or [], mod.get("weight_vals") or []):
        if k in tags:
            return v
    return 0


def can_roll(mod: dict, tags: set) -> bool:
    return mod_weight(mod, tags) > 0


def added_tags(mods: list[dict]) -> set:
    out = set()
    for m in mods:
        out.update(m.get("adds_tags") or [])
    return out


# Mod groups PoB keeps apart that the game treats as one family (only one of them per item).
# Checked on the trade site (2026-11): no item has natural "+# to Level of all Spell Skills" together with
# lightning/cold/... spell levels, or spell + minion / melee + projectile levels. The ones that seem to are a
# crafted +1 (Verisium), a rune or an enchant.
_FAMILIES = [
    (re.compile(r"^(GlobalIncrease\w*SkillGemLevel(Weapon)?|Essence\w*SkillLevel|MarkSkillGemLevels)$"), "SkillGemLevels"),
]


def family(group: str) -> str:
    for rx, name in _FAMILIES:
        if rx.match(group or ""):
            return name
    return group


def _mod_of(ident: tuple, groups) -> dict | None:
    atype, grp, tier = ident
    tiers = groups.get((atype, grp))
    return tiers[max(tier, 1) - 1] if tiers else None


def _context(session, slot: str):
    cur = session.item(slot)
    if cur is None:
        raise ValueError(f"nothing equipped in {slot}")
    head, imp, exp = split_item(cur["raw"])
    base = cur["base"]
    ilvl = _item_level(cur["raw"])
    return cur, head, imp, exp, base, ilvl


def ideal_item(session, slot: str, objective: Objective | None = None, ilvl: int | None = None) -> dict:
    """Greedy best 3 prefixes + 3 suffixes for this build on the current item's base (top rolls)."""
    session._need_build()
    obj = objective or Objective()
    pob, kb = session.pob, session.kb
    cur, head, imp, exp, base, item_lvl = _context(session, slot)
    groups = pool_by_group(kb, base, ilvl or item_lvl)
    real_slot = pob.resolve_slot(slot)
    base_tags = set((kb.base(base) or {}).get("tags") or [])
    chosen: list[tuple[tuple[str, str], dict]] = []
    counts = {"Prefix": 0, "Suffix": 0}
    lines: list[str] = []
    while counts["Prefix"] < 3 or counts["Suffix"] < 3:
        best = None
        tags = base_tags | added_tags([m for _, m in chosen])  # mods already picked can block others
        for key, tiers in groups.items():
            atype, _ = key
            if counts[atype] >= MAX_AFFIX[atype] or any(family(k[1]) == family(key[1]) for k, _ in chosen):
                continue
            top = tiers[0]
            if not can_roll(top, tags):
                continue
            w = pob.whatif(slot=real_slot, item_raw=join_item(head, imp, lines + _mod_lines(top)), exact_slot=True)
            sc = obj.score(w, session.base)
            if best is None or sc > best[0]:
                best = (sc, key, top)
        if best is None:
            break
        _, key, top = best
        chosen.append((key, top))
        counts[key[0]] += 1
        lines += _mod_lines(top)
    raw = join_item(head, imp, lines)
    w = pob.whatif(slot=real_slot, item_raw=raw, exact_slot=True)
    return {"slot": real_slot, "base": base, "item_level": ilvl or item_lvl, "current": cur["name"],
            **obj.explain(w, session.base),
            "mods": [{"type": k[0], "group": k[1], "text": " / ".join(_mod_lines(m)), "level": m["level"],
                      "essence": _essences(kb, m["id"], real_slot)}
                     for k, m in chosen],
            "item_text": raw,
            "note": "Top rolls of the highest tier available at this item level; score vs the current item. "
                    "A perfect item is a ceiling, not a shopping list: look at which mods made the cut."}


def mod_upgrades(session, slot: str, objective: Objective | None = None, limit: int = 10) -> dict:
    """For each changeable mod on the current item: the best replacement of the same affix type."""
    session._need_build()
    obj = objective or Objective()
    pob, kb = session.pob, session.kb
    cur, head, imp, exp, base, ilvl = _context(session, slot)
    groups = pool_by_group(kb, base, ilvl)
    real_slot = pob.resolve_slot(slot)
    skip_tags = ("{fractured}", "{crafted}", "{desecrated}", "{enchant}", "{rune}")
    base_tags = set((kb.base(base) or {}).get("tags") or [])
    present: dict[str, int] = {}  # mod family -> the line that has it (one mod per family on an item)
    lines_info: list[list] = []
    line_mods: list[dict | None] = []  # the mod each line is, for the tags it puts on the item
    for i, line in enumerate(exp):
        if not line.strip() or _clean(line) in ("Corrupted", "Mirrored"):
            lines_info.append([])
            line_mods.append(None)
            continue
        ident = identify(line, groups)
        line_mods.append(_mod_of(ident[0], groups) if ident else None)
        if ident and not line.startswith("{crafted}"):  # fractured/desecrated stay and keep their family;
            present.setdefault(family(ident[0][1]), i)  # a crafted mod (Verisium) can sit next to its family
        if line.startswith(skip_tags):
            lines_info.append([])
            continue
        lines_info.append(ident)
        for atype, grp, _ in ident:
            present.setdefault(family(grp), i)
    rows, seen = [], set()
    corrupted = any(_clean(x) == "Corrupted" for x in exp)
    for i, idents in enumerate(lines_info):
        # tags of every other mod on the item: the replacement must still be allowed to roll next to them
        tags = base_tags | added_tags([m for j, m in enumerate(line_mods) if m and j != i])
        for atype, grp, tier in idents:
            for key, tiers in groups.items():
                fam = family(key[1])
                if key[0] != atype or (fam in present and present[fam] != i):
                    continue
                if key == (atype, grp) and tier == 1:
                    continue
                top = tiers[0]
                sig = (i, top["id"])
                if sig in seen:
                    continue
                seen.add(sig)
                # typical = the middle tier with a middle roll: what you realistically hit or can afford;
                # top = the best tier with the best roll: the ceiling, usually a lottery
                typical = tiers[len(tiers) // 2]
                if not can_roll(typical, tags):
                    continue  # blocked by another mod on the item (e.g. lightning levels block cold levels)
                evals = {}
                for label, mod, mode in (("typical", typical, "mid"), ("top", top, "max")):
                    lines = [resolve_ranges(p, mode) for p in mod["text"].split(" / ")]
                    w = pob.whatif(slot=real_slot, item_raw=join_item(head, imp, exp[:i] + lines + exp[i + 1:]),
                                   exact_slot=True)
                    evals[label] = (lines, obj.explain(w, session.base))
                t_lines, t_ex = evals["typical"]
                top_lines, top_ex = evals["top"]
                if t_ex["score"] <= 0.05:
                    continue  # a typical roll that is not better than what you have is no suggestion
                total = sum(len(t) for (a, _), t in groups.items() if a == atype)
                rows.append({"replace": _clean(exp[i]),
                             "replace_as": f"{atype} T{tier}" if tier else f"{atype}, value above normal tiers",
                             "with": " / ".join(t_lines), "with_tier": f"T{len(tiers) // 2 + 1} z {len(tiers)}",
                             "group": key[1], **t_ex,
                             "top": {"with": " / ".join(top_lines), "level": top["level"], **top_ex},
                             "odds": {"family_pct": round(len(tiers) / total * 100, 1),
                                      "top_tier_pct": round(100 / total, 2),
                                      "exalts_for_top_tier": total},
                             "essence": _essences(kb, typical["id"], real_slot) or _essences(kb, top["id"], real_slot)})
    rows.sort(key=lambda r: r["score"], reverse=True)  # ranked by the realistic (typical) roll
    unknown = [_clean(exp[i]) for i, x in enumerate(lines_info) if not x and exp[i].strip()
               and _clean(exp[i]) not in ("Corrupted", "Mirrored")]
    return {"slot": real_slot, "item": cur["name"], "base": base, "item_level": ilvl, "corrupted": corrupted,
            "upgrades": rows[:limit],
            "not_changeable_or_unknown": unknown,
            "note": ("Corrupted item: it cannot be modified." if corrupted else
                     "Ranked by a typical (middle tier, middle roll) replacement; 'top' is the best possible roll and "
                     "'odds' the chance per Exalted Orb with equal weights (estimate). A top tier at well under 1% is "
                     "a lottery or an expensive trade item; poe.ninja does not price rare items. Replacing a mod means "
                     "removing the old one first (annul is random) or an essence that guarantees the new one.")}


def craft_odds(session, base: str, ilvl: int, want_groups: list[str]) -> dict:
    """Chance that one random added prefix or suffix is in the wanted mod families (equal weights)."""
    from soe.prices import safe_price

    groups = pool_by_group(session.kb, base, ilvl)
    exalt = safe_price("Exalted Orb")
    res = {}
    for atype in ("Prefix", "Suffix"):
        total = sum(len(t) for (a, _), t in groups.items() if a == atype)
        hit = sum(len(t) for (a, g), t in groups.items() if a == atype and g in want_groups)
        r = {"possible_mods": total, "wanted_mods": hit, "chance_pct": round(hit / total * 100, 1) if total else 0}
        if hit:
            r["expected_exalts"] = round(total / hit, 1)  # an Exalted Orb adds one random mod of an open type
            if exalt:
                r["expected_cost_divine"] = round(total / hit * exalt["divine"], 3)
        res[atype] = r
    return {"base": base, "item_level": ilvl, "wanted": want_groups, **res,
            "exalted_orb_price": exalt,
            "families": sorted({g for (_, g) in groups}),
            "note": "Equal weights per possible mod tier (PoB has no real spawn weights): an estimate. Expected exalts "
                    "assume the slot type is open and only count hitting a wanted family, not its top tier."}
