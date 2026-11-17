"""Craft planner for a base and mods the player picks (the Crafting tab).

The player picks a base, an item level and up to 3 prefixes + 3 suffixes (each with a minimum tier).
We compare several real PoE2 crafting routes by Monte Carlo over the mod pool:

- chance per try that the finished item has every wanted mod (how deterministic the route is),
- the currency one try uses on average (poe.ninja prices), and the expected cost until it works.

PoE2 rules used (poe2db, checked 2026-11):
- Orb of Transmutation: normal -> magic with 1 mod. Orb of Augmentation: adds a mod to a magic item (max 2).
- Regal Orb: magic -> rare, adds 1 mod. Orb of Alchemy: normal -> rare with 4 random mods.
- Exalted Orb: adds 1 random mod to a rare (max 3 prefixes + 3 suffixes). Greater Exalted Orb only adds mods of
  level 35+, Perfect Exalted Orb 50+.
- Chaos Orb: removes a random mod and adds a random one.
- Lesser / normal / Greater Essence: magic -> rare with its guaranteed mod. Perfect Essence: on a rare, removes a
  random mod and adds its guaranteed mod; Omen of Sinistral / Dextral Crystallisation makes it remove only a prefix /
  suffix.
- Omen of Sinistral / Dextral Exaltation: the next Exalted Orb adds only a prefix / suffix.

PoE2 spawn weights are not in PoB's data: every mod tier that can roll has the same weight. Real top tiers are rarer,
so chances for high minimum tiers are optimistic. The ranking of routes is what matters.
"""
from __future__ import annotations

import random
from collections import Counter

from soe.items.craft import family, pool_by_group, resolve_ranges

SIDES = ("Prefix", "Suffix")
MIN_LEVEL = {"Exalted Orb": 0, "Greater Exalted Orb": 35, "Perfect Exalted Orb": 50}
OMEN_EXALT = {"Prefix": "Omen of Sinistral Exaltation", "Suffix": "Omen of Dextral Exaltation"}
OMEN_CRYST = {"Prefix": "Omen of Sinistral Crystallisation", "Suffix": "Omen of Dextral Crystallisation"}
CHAOS_CAP = 250


def _price(name: str) -> float | None:
    from soe.prices import safe_price

    p = safe_price(name)
    return p.get("divine") if p else None


def _essence_type(base: dict) -> str:
    return "Warstaff" if base.get("sub_type") == "Warstaff" else base.get("type")


# ---------------------------------------------------------------- what the UI lists

CRAFT_TYPES = ("Ring", "Amulet", "Belt", "Helmet", "Gloves", "Boots", "Body Armour", "Shield", "Focus", "Quiver",
               "Wand", "Staff", "Sceptre", "Bow", "Crossbow", "Spear", "Talisman", "Dagger", "Claw", "Flail",
               "One Hand Mace", "Two Hand Mace", "One Hand Sword", "Two Hand Sword", "One Hand Axe", "Two Hand Axe")


def craft_bases(kb, item_type: str | None = None, text: str | None = None) -> list[dict]:
    sql, args = "SELECT name, type, sub_type, req, props FROM bases WHERE hidden = 0", []
    if item_type:
        sql += " AND type = ?"
        args.append(item_type)
    if text:
        sql += " AND name LIKE ?"
        args.append(f"%{text}%")
    out = []
    for b in kb._rows(sql, args):
        if b["type"] not in CRAFT_TYPES:
            continue
        req = b.get("req") or {}
        out.append({"name": b["name"], "type": b["type"], "sub_type": b.get("sub_type"),
                    "level": (req.get("level") if isinstance(req, dict) else None) or 1})
    out.sort(key=lambda b: (b["type"], -b["level"], b["name"]))
    return out


def craft_pool(kb, base_name: str, ilvl: int) -> dict:
    """Every mod family that can roll on the base at this item level, with its tiers (T1 = best)
    and the essences that guarantee one of its tiers."""
    base = kb.base(base_name)
    if not base:
        raise ValueError(f"unknown base {base_name!r}")
    groups = pool_by_group(kb, base["name"], ilvl)
    ess = _essence_index(kb, _essence_type(base), ilvl)
    fams = []
    for (atype, grp), tiers in groups.items():
        fams.append({
            "type": atype, "group": grp, "family": family(grp),
            "text": tiers[0]["text"], "tags": tiers[0].get("tags") or [],
            "tiers": [{"tier": i, "level": t["level"] or 1, "text": t["text"]} for i, t in enumerate(tiers, 1)],
            "essences": [{"name": e["name"], "level": e["mod_level"], "text": e["mod_text"], "perfect": e["perfect"]}
                         for e in ess.get(family(grp), []) if e["affix"] == atype],
        })
    in_pool = {f["family"] for f in fams}
    for fam, rows in ess.items():  # mods only an essence gives (e.g. % life from a Perfect Essence)
        for atype in SIDES:
            mine = [e for e in rows if e["affix"] == atype]
            if fam in in_pool or not mine:
                continue
            mine.sort(key=lambda e: e["mod_level"], reverse=True)
            fams.append({"type": atype, "group": mine[0]["grp"], "family": fam, "text": mine[0]["mod_text"],
                         "tags": [], "essence_only": True,
                         "tiers": [{"tier": i, "level": e["mod_level"], "text": e["mod_text"]} for i, e in enumerate(mine, 1)],
                         "essences": [{"name": e["name"], "level": e["mod_level"], "text": e["mod_text"],
                                       "perfect": e["perfect"]} for e in mine]})
    fams.sort(key=lambda f: (f["type"], f["text"].lower()))
    req = base.get("req") or {}
    return {"base": base["name"], "type": base["type"], "item_level": ilvl,
            "base_level": (req.get("level") if isinstance(req, dict) else None) or 1, "families": fams}


def _essence_index(kb, item_type: str, ilvl: int) -> dict[str, list[dict]]:
    rows = kb._rows("SELECT e.name, m.text AS mod_text, m.level AS mod_level, m.type AS affix, m.grp, "
                    "m.adds_tags FROM essences e JOIN mods m ON m.id = e.mod_id AND m.domain = 'Item' "
                    "WHERE e.item_type = ?", (item_type,))
    out: dict[str, list[dict]] = {}
    for r in rows:
        if (r["mod_level"] or 0) > ilvl or r["affix"] not in SIDES:
            continue
        r["perfect"] = r["name"].startswith("Perfect ")
        r["mod_level"] = r["mod_level"] or 1
        out.setdefault(family(r["grp"]), []).append(r)
    for v in out.values():
        v.sort(key=lambda r: r["mod_level"])
    return out


# ---------------------------------------------------------------- simulation


class _Pool:
    """Fast random picks from the base's mod pool: rejection sampling instead of filtering the whole list."""

    def __init__(self, groups, base_tags: set):
        self.base_tags = base_tags
        self.entries = {s: [] for s in SIDES}
        for (atype, grp), tiers in groups.items():
            for m in tiers:
                self.entries[atype].append({"type": atype, "grp": grp, "fam": family(grp), "level": m["level"] or 1,
                                            "adds_tags": m.get("adds_tags") or [], "weight_keys": m.get("weight_keys"),
                                            "weight_vals": m.get("weight_vals")})
        self._by_min: dict[tuple, list] = {}

    def side_list(self, side: str, min_level: int) -> list:
        key = (side, min_level)
        if key not in self._by_min:
            self._by_min[key] = [e for e in self.entries[side] if e["level"] >= min_level]
        return self._by_min[key]

    def add(self, rng, mods: list, side: str | None = None, min_level: int = 0) -> dict | None:
        from soe.items.craft import can_roll

        counts = Counter(m["type"] for m in mods)
        sides = [s for s in SIDES if counts[s] < 3 and (side is None or s == side)]
        lists = [self.side_list(s, min_level) for s in sides]
        total = sum(len(x) for x in lists)
        if not total:
            return None
        fams = {m["fam"] for m in mods}
        extra = set()
        for m in mods:
            extra.update(m["adds_tags"])
        tags = self.base_tags | extra if extra else None
        for _ in range(200):
            i = rng.randrange(total)
            for lst in lists:
                if i < len(lst):
                    e = lst[i]
                    break
                i -= len(lst)
            if e["fam"] in fams or (tags is not None and not can_roll(e, tags)):
                continue
            mods.append(e)
            return e
        return None  # everything left is blocked


class _Want:
    def __init__(self, wanted: list[dict]):
        self.min = {family(w["group"]): int(w.get("min_level") or 0) for w in wanted}
        self.side = {family(w["group"]): w["type"] for w in wanted}

    def hit(self, m: dict) -> bool:
        return m["fam"] in self.min and m["level"] >= self.min[m["fam"]]

    def hits(self, mods: list) -> int:
        return len({m["fam"] for m in mods if self.hit(m)})

    def missing_sides(self, mods: list) -> set:
        have = {m["fam"] for m in mods if self.hit(m)}
        return {self.side[f] for f in self.min if f not in have}


def _ess_mod(e: dict) -> dict:
    return {"type": e["affix"], "grp": e["grp"], "fam": family(e["grp"]), "level": e["mod_level"],
            "adds_tags": e.get("adds_tags") or []}


class _Run:
    def __init__(self, pool: _Pool, want: _Want, rng):
        self.pool, self.want, self.rng = pool, want, rng
        self.mods: list = []
        self.used: Counter = Counter()

    def use(self, name: str, n: int = 1):
        self.used[name] += n

    def exalt(self, orb: str = "Exalted Orb", omens: bool = False):
        side = None
        if omens:
            miss = self.want.missing_sides(self.mods)
            counts = Counter(m["type"] for m in self.mods)
            open_miss = [s for s in miss if counts[s] < 3]
            if len(open_miss) == 1 and counts[SIDES[1 - SIDES.index(open_miss[0])]] < 3:
                side = open_miss[0]  # only one side still needs mods and the other is open too: steer it
                self.use(OMEN_EXALT[side])
        self.use(orb)
        self.pool.add(self.rng, self.mods, side, MIN_LEVEL[orb])

    def fill(self, orb="Exalted Orb", omens=False):
        while len(self.mods) < 6:
            before = len(self.mods)
            self.exalt(orb, omens)
            if len(self.mods) == before:
                break

    def perfect_essence(self, e: dict):
        """Perfect Essence on a rare: removes a random mod (only from its own side with the omen) and adds its mod."""
        if any(m["fam"] == family(e["grp"]) for m in self.mods):
            return
        side = e["affix"]
        other = SIDES[1 - SIDES.index(side)]
        by = {s: [m for m in self.mods if m["type"] == s] for s in SIDES}
        junk = {s: [m for m in by[s] if not self.want.hit(m)] for s in SIDES}
        if len(by[side]) >= 3:  # its side is full: the removed mod must come from there
            if not junk[side]:
                return
            remove_from = side
        elif junk[other] and not junk[side]:
            remove_from = other
        elif junk[side]:
            remove_from = side
        else:
            return  # nothing worth sacrificing
        self.use(OMEN_CRYST[remove_from])
        self.use(e["name"])
        self.mods.remove(self.rng.choice(by[remove_from]))  # still random within that side
        self.mods.append(_ess_mod(e))

    def chaos(self):
        self.use("Chaos Orb")
        if self.mods:
            self.mods.remove(self.rng.choice(self.mods))
        self.pool.add(self.rng, self.mods)


def _usable_essences(want: _Want, ess_by_fam: dict) -> tuple[list, list]:
    """Essences that give a wanted mod at the wanted tier: (normal ones, one per family, cheapest first; perfect ones)."""
    usable = []
    for f in want.min:
        for e in ess_by_fam.get(f, []):
            if e["mod_level"] >= want.min[f] and e["affix"] == want.side[f]:
                usable.append({**e, "price": _price(e["name"])})
    key = lambda e: (e["price"] is None, e["price"] or 0, e["mod_level"])  # noqa: E731
    normal, seen = [], set()
    for e in sorted((e for e in usable if not e["perfect"]), key=key):
        if family(e["grp"]) not in seen:
            seen.add(family(e["grp"]))
            normal.append(e)
    return normal, sorted((e for e in usable if e["perfect"]), key=key)


def _routes(pool: _Pool, want: _Want, ilvl: int, first: dict | None, perfect: list, basic: bool) -> list:
    """Route definitions (key, name, about, function(run), orbs). `first`: the essence that makes the item rare;
    `basic`: also the routes without essences."""
    wanted_fams = list(want.min)
    perf = [e for e in perfect if not first or family(e["grp"]) != family(first["grp"])]
    perf_one = []
    seen = set()
    for e in perf:
        if family(e["grp"]) not in seen:
            seen.add(family(e["grp"]))
            perf_one.append(e)

    def start_essence(r):
        fam = family(first["grp"])
        for _ in range(50):  # the transmute mod must not be the essence's own family: else take a new base
            r.mods.clear()
            r.use("Orb of Transmutation")
            m = r.pool.add(r.rng, r.mods)
            if not m or m["fam"] != fam:
                break
        r.use(first["name"])
        r.mods.append(_ess_mod(first))

    routes = []

    def cheap(r):
        r.use("Orb of Transmutation"); r.pool.add(r.rng, r.mods)
        r.use("Orb of Augmentation"); r.pool.add(r.rng, r.mods)
        r.use("Regal Orb"); r.pool.add(r.rng, r.mods)
        r.fill()
    if basic:
        routes.append(("random", "Najtańsza loteria",
                       "Transmutation, Augmentation, Regal, potem Exalty do 6 modów. Same tanie orby, czysty los.",
                       cheap, ["Orb of Transmutation", "Orb of Augmentation", "Regal Orb", "Exalted Orb"]))

    def alch(r):
        r.use("Orb of Alchemy")
        for _ in range(4):
            r.pool.add(r.rng, r.mods)
        r.fill()
    if basic:
        routes.append(("alchemy", "Alchemy + Exalty",
                       "Orb of Alchemy daje od razu 4 mody, potem 2 Exalty. Szybko, ale też los.", alch,
                       ["Orb of Alchemy", "Exalted Orb"]))

    if first:
        def ess(r):
            start_essence(r)
            r.fill(omens=True)
        routes.append(("essence", f"{first['name']} + Exalty z omenami",
                       f"{first['name']} daje na pewno: {resolve_ranges(first['mod_text'], 'mid')}. "
                       "Potem Exalty; gdy brakuje modów tylko jednego typu, omen Sinistral/Dextral Exaltation "
                       "kieruje Exalta na prefix albo suffix.", ess,
                       ["Orb of Transmutation", first["name"], "Exalted Orb", "Omen of Sinistral Exaltation",
                        "Omen of Dextral Exaltation"]))
    if perf_one and (first or basic):
        def ess_perf(r):
            if first:
                start_essence(r)
            else:
                r.use("Orb of Transmutation"); r.pool.add(r.rng, r.mods)
                r.use("Regal Orb"); r.pool.add(r.rng, r.mods)
            r.fill(omens=True)
            for e in perf_one:
                if not any(m["fam"] == family(e["grp"]) and want.hit(m) for m in r.mods):
                    r.perfect_essence(e)
            r.fill(omens=True)
        names = ", ".join(e["name"] for e in perf_one)
        routes.append(("perfect", f"{first['name'] + ' + ' if first else ''}Exalty + Perfect Essence",
                       (f"{first['name'] + ' na start, ' if first else ''}Exalty z omenami, a na koniec {names}: "
                        "Perfect Essence usuwa losowy mod (z omenem Crystallisation tylko z tej samej strony) "
                        "i daje swój mod na pewno."), ess_perf,
                       (["Orb of Transmutation"] + ([first["name"]] if first else ["Regal Orb"]) +
                        ["Exalted Orb", "Omen of Sinistral Exaltation", "Omen of Dextral Exaltation"] +
                        [e["name"] for e in perf_one] + list(OMEN_CRYST.values()))))
    hi = max(want.min.values() or [0])
    for orb in ("Greater Exalted Orb", "Perfect Exalted Orb"):
        if hi >= MIN_LEVEL[orb] and ilvl >= MIN_LEVEL[orb] and (first or basic):
            def high(r, orb=orb):
                if first:
                    start_essence(r)
                else:
                    r.use("Orb of Transmutation"); r.pool.add(r.rng, r.mods)
                    r.use("Regal Orb"); r.pool.add(r.rng, r.mods)
                r.fill(orb, omens=True)
            routes.append((orb.split()[0].lower(), f"{first['name'] + ' + ' if first else ''}{orb}",
                           f"{orb} dodaje tylko mody od {MIN_LEVEL[orb]} poziomu: mniej śmieci i niskich tierów, "
                           "ale drożej za sztukę.", high,
                           ["Orb of Transmutation", first["name"] if first else "Regal Orb", orb,
                            "Omen of Sinistral Exaltation", "Omen of Dextral Exaltation"]))

    if basic and len(wanted_fams) <= 3:
        def chaos(r):
            alch(r)
            n = 0
            while want.hits(r.mods) < len(wanted_fams) and n < CHAOS_CAP:
                r.chaos()
                n += 1
        routes.append(("chaos", "Chaos spam do skutku",
                       f"Alchemy + Exalty, potem Chaos Orb (usuwa losowy mod, dodaje losowy) aż wejdzie wszystko "
                       f"(najwyżej {CHAOS_CAP}). Mało pewne na jedną próbę, ale bez nowych baz.", chaos,
                       ["Orb of Alchemy", "Exalted Orb", "Chaos Orb"]))
    return routes


def craft_routes(kb, base_name: str, ilvl: int, wanted: list[dict], sims: int = 2000, seed: int = 11) -> dict:
    """wanted: [{"group": mod group, "type": "Prefix"|"Suffix", "min_level": minimum mod level (0 = any tier)}]."""
    base = kb.base(base_name)
    if not base:
        raise ValueError(f"unknown base {base_name!r}")
    if not wanted:
        raise ValueError("pick at least one mod")
    groups = pool_by_group(kb, base["name"], ilvl)
    ess_by_fam = _essence_index(kb, _essence_type(base), ilvl)
    problems = []
    fams = Counter(family(w["group"]) for w in wanted)
    if any(n > 1 for n in fams.values()):
        problems.append("Dwa wybrane mody są z tej samej rodziny: na itemie może być tylko jeden z nich.")
    for side in SIDES:
        if sum(w["type"] == side for w in wanted) > 3:
            problems.append(f"Za dużo modów typu {side}: najwyżej 3.")
    for w in wanted:
        tiers = groups.get((w["type"], w["group"])) or []
        ok = [t for t in tiers if (t["level"] or 1) >= int(w.get("min_level") or 0)]
        if not ok and not any(e["mod_level"] >= int(w.get("min_level") or 0) for e in ess_by_fam.get(family(w["group"]), [])):
            problems.append(f"{w['group']}: ten tier nie wypada na tej bazie przy item level {ilvl}.")
    need_ilvl = max(int(w.get("min_level") or 0) for w in wanted)
    if problems:
        return {"base": base["name"], "item_level": ilvl, "possible": False, "problems": problems, "routes": []}

    pool = _Pool(groups, set(base.get("tags") or []))
    want = _Want(wanted)
    normal, perfect = _usable_essences(want, ess_by_fam)
    defs = []
    for j, first in enumerate([None] + normal[:3]):  # every wanted mod an essence can start with
        defs += _routes(pool, want, ilvl, first, perfect, basic=j == 0)
    out = []
    for i, (key, name, about, fn, orbs) in enumerate(defs):
        rng = random.Random(seed + i)
        n_ok, hist, used = 0, Counter(), Counter()
        for _ in range(sims):
            r = _Run(pool, want, rng)
            fn(r)
            h = want.hits(r.mods)
            hist[h] += 1
            n_ok += h == len(want.min)
            used.update(r.used)
        p = n_ok / sims
        steps, cost, known = [], 0.0, True
        for orb in dict.fromkeys(orbs):
            avg = used[orb] / sims
            if avg <= 0:
                continue
            price = _price(orb)
            if price is None:
                known = False
            else:
                cost += price * avg
            steps.append({"orb": orb, "avg_count": round(avg, 2), "price_divine": price})
        k = len(want.min)
        out.append({"key": key, "name": name, "about": about, "steps": steps,
                    "chance_pct": round(p * 100, 2),
                    "at_least_pct": {j: round(sum(v for h, v in hist.items() if h >= j) / sims * 100, 1)
                                     for j in range(1, k + 1)},
                    "cost_try_divine": round(cost, 3), "cost_complete": known,
                    "tries": round(1 / p, 1) if p else None,
                    "expected_divine": round(cost / p, 3) if p else None})
    # per kind of route keep the essence that works best
    best_of: dict[str, dict] = {}
    for r in out:
        cur = best_of.get(r["key"])
        rank = lambda x: (x["expected_divine"] is None, x["expected_divine"] or 0, -x["chance_pct"])  # noqa: E731
        if cur is None or rank(r) < rank(cur):
            best_of[r["key"]] = r
    out = list(best_of.values())
    one_shot = [r for r in out if r["key"] != "chaos"]  # chaos spam is many tries on one item, not one try
    if one_shot:
        best = max(one_shot, key=lambda r: r["chance_pct"])
        best["badges"] = ["najpewniejsza"]
        priced = [r for r in out if r["expected_divine"] is not None]
        if priced:
            cheap = min(priced, key=lambda r: r["expected_divine"])
            cheap.setdefault("badges", []).append("najtańsza do skutku")
    out.sort(key=lambda r: (-(r["chance_pct"] > 0), r["expected_divine"] if r["expected_divine"] is not None else 1e9))
    return {"base": base["name"], "item_level": ilvl, "need_item_level": need_ilvl, "possible": True,
            "wanted": [{**w, "family": family(w["group"])} for w in wanted], "routes": out,
            "note": ("Szanse: symulacja (równe wagi dla każdego tieru, bo PoB nie ma prawdziwych wag z gry), więc "
                     "wysokie tiery wychodzą tu łatwiej niż w grze. Koszt: średnie zużycie orbów na jedną próbę, "
                     "ceny z poe.ninja, bez ceny bazy. 'Do skutku' = koszt próby / szansa.")}
