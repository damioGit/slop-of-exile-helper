"""Craft planner for a base and mods the player picks (the Kuźnia tab).

The player picks a base, an item level and up to 3 prefixes + 3 suffixes (each with a minimum tier).
We compare real PoE2 crafting routes by Monte Carlo over the base's mod pool from poe2db (real spawn weights,
the game's mod families, essences and desecrated mods):

- chance per try that the finished item has every wanted mod,
- the currency a try (or a whole craft on one base) uses on average, priced from poe.ninja,
- what it costs to stop at fewer wanted mods (4 of 6, 5 of 6).

PoE2 rules used (poe2db, checked 2026-11):
- Orb of Transmutation: normal -> magic with 1 mod. Orb of Augmentation: adds a mod to a magic item (max 2).
- Regal Orb: magic -> rare, adds 1 mod. Orb of Alchemy: normal -> rare with 4 random mods.
- Exalted Orb: adds 1 random mod to a rare (max 3 prefixes + 3 suffixes). Greater Exalted Orb only adds mods of
  level 35+, Perfect Exalted Orb 50+. Omen of Sinistral / Dextral Exaltation: only a prefix / suffix.
- Chaos Orb: removes a random mod and adds a random one. Orb of Annulment: removes a random mod; Omen of Sinistral /
  Dextral Annulment: only a prefix / suffix; Omen of Light: only the desecrated mod.
- Lesser / normal / Greater Essence: magic -> rare with its guaranteed mod. Perfect Essence: on a rare, removes a
  random mod and adds its mod; Omen of Sinistral / Dextral Crystallisation: removes only a prefix / suffix.
- Desecration: a bone (Jawbone: weapons and quivers, Rib: armour, Collarbone: rings, amulets, belts; Ancient bones
  only mods of level 40+) adds an unrevealed desecrated mod to a rare with room. At the Well of Souls you pick one of
  three options, which may include the base's normal mods. Omen of Abyssal Echoes rerolls the options once, Omen of
  Sinistral / Dextral Necromancy makes it a prefix / suffix. One desecrated mod per item.
"""
from __future__ import annotations

import bisect
import random
import statistics
import time
from collections import Counter

from soe.items.craft import added_tags, can_roll, family, pool_by_group, resolve_ranges
from soe.i18n import t
from soe.kb import poe2db

SIDES = ("Prefix", "Suffix")
MIN_LEVEL = {"Exalted Orb": 0, "Greater Exalted Orb": 35, "Perfect Exalted Orb": 50}
OMEN_EXALT = {"Prefix": "Omen of Sinistral Exaltation", "Suffix": "Omen of Dextral Exaltation"}
OMEN_ANNUL = {"Prefix": "Omen of Sinistral Annulment", "Suffix": "Omen of Dextral Annulment"}
OMEN_CRYST = {"Prefix": "Omen of Sinistral Crystallisation", "Suffix": "Omen of Dextral Crystallisation"}
OMEN_NECRO = {"Prefix": "Omen of Sinistral Necromancy", "Suffix": "Omen of Dextral Necromancy"}
ECHOES, LIGHT = "Omen of Abyssal Echoes", "Omen of Light"
BONE_MIN: dict[str, int] = {"Ancient Rib": 40, "Ancient Collarbone": 40, "Ancient Jawbone": 40}
LOOP_CAP = 300  # currency uses on one base before we call it a failure
ONE_SHOT_MAX = 200_000
EXTEND = {"random", "alchemy", "essence"}  # cheap routes whose full-goal chance is worth measuring well
FARM_TRIES = 3000  # cheap bases tried before finishing the best one
REVEAL_OPTIONS = 3
# poe2db says revealed options "may include base modifiers" but not how often: a desecrated-only mod counts like a
# typical (median weight) normal mod of that side. Stated in the result note.


def _price(name: str) -> float | None:
    from soe.prices import safe_price

    p = safe_price(name)
    return p.get("divine") if p else None


def _essence_type(base: dict) -> str:
    return "Warstaff" if base.get("sub_type") == "Warstaff" else base.get("type")


def fkey(fams) -> str:
    return "|".join(sorted(fams))


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


def _essence_index(kb, base: dict, ilvl: int) -> dict[str, list[dict]]:
    """family -> essences that guarantee a mod of it on this base (poe2db; PoB's essence table as fallback)."""
    data = poe2db.for_base(base)
    rows = []
    if data and data.get("essence"):
        for e in data["essence"]:
            if e["fams"]:
                rows.append({"name": e["name"], "mod_text": e["text"], "mod_level": e["level"], "affix": e["type"],
                             "grp": e["fams"][0], "fams": e["fams"], "adds_tags": [], "perfect": e["perfect"]})
    else:
        for r in kb._rows("SELECT e.name, m.text AS mod_text, m.level AS mod_level, m.type AS affix, m.grp, "
                          "m.adds_tags FROM essences e JOIN mods m ON m.id = e.mod_id AND m.domain = 'Item' "
                          "WHERE e.item_type = ?", (_essence_type(base),)):
            r.update(perfect=r["name"].startswith("Perfect "), mod_level=r["mod_level"] or 1, fams=[family(r["grp"])])
            rows.append(r)
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r["mod_level"] > ilvl or r["affix"] not in SIDES:
            continue
        for f in r["fams"]:
            out.setdefault(f, []).append(r)
    for v in out.values():
        v.sort(key=lambda r: r["mod_level"])
    return out


def craft_pool(kb, base_name: str, ilvl: int) -> dict:
    """Every mod group that can roll on the base at this item level: tiers (T1 = best) with spawn weights, the chance
    that a random mod of that side is from the group, and the essences that guarantee one of its tiers."""
    base = kb.base(base_name)
    if not base:
        raise ValueError(f"unknown base {base_name!r}")
    groups = pool_by_group(kb, base["name"], ilvl)
    ess = _essence_index(kb, base, ilvl)
    side_w = Counter()
    for (atype, _), tiers in groups.items():
        side_w[atype] += sum(t["w"] for t in tiers)
    out = []
    for (atype, grp), tiers in groups.items():
        fams = tiers[0]["fams"]
        es = {e["name"]: e for f in fams for e in ess.get(f, []) if e["affix"] == atype}
        out.append({
            "type": atype, "group": grp, "family": fkey(fams), "text": tiers[0]["text"],
            "tags": tiers[0].get("tags") or [],
            "chance_pct": round(sum(t["w"] for t in tiers) / side_w[atype] * 100, 2) if side_w[atype] else 0,
            "tiers": [{"tier": i, "level": t["level"] or 1, "text": t["text"], "weight": t["w"]}
                      for i, t in enumerate(tiers, 1)],
            "essences": [{"name": e["name"], "level": e["mod_level"], "text": e["mod_text"], "perfect": e["perfect"]}
                         for e in es.values()],
        })
    in_pool = {f for g in out for f in g["family"].split("|")}
    only: dict[tuple, list] = {}
    for rows in ess.values():  # mods only an essence gives (e.g. % life from a Perfect Essence)
        for e in rows:
            if not set(e["fams"]) & in_pool:
                only.setdefault((e["affix"], fkey(e["fams"])), {})[e["name"]] = e
    for (atype, fk), es in only.items():
        mine = sorted(es.values(), key=lambda e: e["mod_level"], reverse=True)
        out.append({"type": atype, "group": mine[0]["grp"], "family": fk, "text": mine[0]["mod_text"], "tags": [],
                    "essence_only": True, "chance_pct": 0,
                    "tiers": [{"tier": i, "level": e["mod_level"], "text": e["mod_text"], "weight": 0}
                              for i, e in enumerate(mine, 1)],
                    "essences": [{"name": e["name"], "level": e["mod_level"], "text": e["mod_text"],
                                  "perfect": e["perfect"]} for e in mine]})
    out.sort(key=lambda f: (f["type"], f["text"].lower()))
    req = base.get("req") or {}
    data = poe2db.for_base(base)
    return {"base": base["name"], "type": base["type"], "item_level": ilvl,
            "base_level": (req.get("level") if isinstance(req, dict) else None) or 1, "families": out,
            "weights": "poe2db" if data else "equal", "poe2db_page": poe2db.page_for_base(base),
            "desecrated_mods": len(data["desecrated"]) if data else 0}


# ---------------------------------------------------------------- simulation


class _Pool:
    """Weighted random picks from the base's mod pool (rejection for family / tag conflicts)."""

    def __init__(self, groups, base_tags: set, data: dict | None, ilvl: int):
        self.base_tags = base_tags
        self.entries = {s: [] for s in SIDES}
        for (atype, grp), tiers in groups.items():
            for m in tiers:
                fams = frozenset(m.get("fams") or [family(grp)])
                self.entries[atype].append({"type": atype, "grp": grp, "fam": fkey(fams), "fams": fams,
                                            "level": m["level"] or 1, "w": m.get("w", 1),
                                            "adds_tags": m.get("adds_tags") or [], "weight_keys": m.get("weight_keys"),
                                            "weight_vals": m.get("weight_vals")})
        self.des = {s: [] for s in SIDES}  # desecrated-only mods, weighted like a typical normal mod of the side
        for s in SIDES:
            med = statistics.median([e["w"] for e in self.entries[s]]) if self.entries[s] else 1
            for d in (data or {}).get("desecrated", []):
                if d["type"] == s and d["level"] <= ilvl and d["fams"]:
                    fams = frozenset(d["fams"])
                    self.des[s].append({"type": s, "grp": d["fams"][0], "fam": fkey(fams), "fams": fams,
                                        "level": d["level"], "w": med, "adds_tags": [], "desecrated_only": True})
        self._cache: dict[tuple, tuple] = {}

    def side_list(self, side: str, min_level: int, reveal: bool = False) -> tuple[list, list, float]:
        key = (side, min_level, reveal)
        if key not in self._cache:
            lst = [e for e in self.entries[side] if e["level"] >= min_level and e["w"] > 0]
            if reveal:
                lst += [e for e in self.des[side] if e["level"] >= min_level]
            cum, t = [], 0.0
            for e in lst:
                t += e["w"]
                cum.append(t)
            self._cache[key] = (lst, cum, t)
        return self._cache[key]

    def pick(self, rng, mods: list, sides: list, min_level: int = 0, reveal: bool = False, avoid=()) -> dict | None:
        lists = [self.side_list(s, min_level, reveal) for s in sides]
        total = sum(t for _, _, t in lists)
        if not total:
            return None
        present = set()
        for m in mods:
            present |= m["fams"]
        for a in avoid:
            present |= a["fams"]
        extra = added_tags(mods)
        tags = self.base_tags | extra if extra else None
        for _ in range(300):
            x = rng.random() * total
            for lst, cum, t in lists:
                if x < t:
                    e = lst[min(bisect.bisect_right(cum, x), len(lst) - 1)]
                    break
                x -= t
            if e["fams"] & present or (tags is not None and e.get("weight_keys") is not None and not can_roll(e, tags)):
                continue
            return e
        return None  # everything left is blocked

    def add(self, rng, mods: list, side: str | None = None, min_level: int = 0) -> dict | None:
        counts = Counter(m["type"] for m in mods)
        sides = [s for s in SIDES if counts[s] < 3 and (side is None or s == side)]
        if not sides:
            return None
        e = self.pick(rng, mods, sides, min_level)
        if e:
            mods.append(e)
        return e


class _Want:
    def __init__(self, wanted: list[dict]):
        """wanted: [{"key", "fams" (frozenset), "type", "min_level"}]"""
        self.w = wanted
        self.min = {w["key"]: int(w.get("min_level") or 0) for w in wanted}
        self.side = {w["key"]: w["type"] for w in wanted}
        self._memo: dict[int, str | None] = {}

    def key_of(self, m: dict) -> str | None:
        k = self._memo.get(id(m), 0)
        if k != 0:
            return k
        # the same mod group (a hybrid sharing one family, e.g. Strength and Intelligence, is not "+Intelligence")
        k = next((w["key"] for w in self.w if w["type"] == m["type"] and w["key"] == m["fam"]
                  and m["level"] >= self.min[w["key"]]), None)
        if not m.get("_tmp"):
            self._memo[id(m)] = k
        return k

    def hit(self, m: dict) -> bool:
        return self.key_of(m) is not None

    def have(self, mods: list) -> set:
        return {k for k in (self.key_of(m) for m in mods) if k}

    def hits(self, mods: list) -> int:
        return len(self.have(mods))

    def missing(self, mods: list) -> list[str]:
        have = self.have(mods)
        return [k for k in self.min if k not in have]

    def missing_sides(self, mods: list) -> set:
        return {self.side[k] for k in self.missing(mods)}


def _ess_mod(e: dict) -> dict:
    return {"type": e["affix"], "grp": e["grp"], "fam": fkey(e["fams"]), "fams": frozenset(e["fams"]),
            "level": e["mod_level"], "adds_tags": e.get("adds_tags") or []}


class _Run:
    def __init__(self, pool: _Pool, want: _Want, rng, prices: dict | None = None, bone: str | None = None):
        self.pool, self.want, self.rng = pool, want, rng
        self.mods: list = []
        self.used: Counter = Counter()
        self.prices = prices or {}
        self.spent = 0.0
        self.bone = bone
        self.reached: dict[int, float] = {}  # hits -> divine spent when first reached (the player could stop there)

    def use(self, name: str, n: int = 1):
        self.used[name] += n
        self.spent += (self.prices.get(name) or 0) * n

    def mark(self):
        for j in range(1, self.want.hits(self.mods) + 1):
            self.reached.setdefault(j, self.spent)

    def counts(self) -> Counter:
        return Counter(m["type"] for m in self.mods)

    def exalt(self, orb: str = "Exalted Orb", omens: bool = False):
        side = None
        if omens:
            c = self.counts()
            open_miss = [s for s in self.want.missing_sides(self.mods) if c[s] < 3]
            if len(open_miss) == 1 and c[SIDES[1 - SIDES.index(open_miss[0])]] < 3:
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

    def perfect_essence(self, e: dict) -> bool:
        """Perfect Essence on a rare: removes a random mod (one side with the omen) and adds its mod."""
        if any(m["fams"] & set(e["fams"]) for m in self.mods):
            return False
        side = e["affix"]
        other = SIDES[1 - SIDES.index(side)]
        by = {s: [m for m in self.mods if m["type"] == s] for s in SIDES}
        junk = {s: [m for m in by[s] if not self.want.hit(m)] for s in SIDES}
        if len(by[side]) >= 3:  # its side is full: the removed mod must come from there
            if not junk[side]:
                return False
            remove_from = side
        elif junk[other] and not junk[side]:
            remove_from = other
        elif junk[side]:
            remove_from = side
        else:
            return False  # nothing worth sacrificing
        self.use(OMEN_CRYST[remove_from])
        self.use(e["name"])
        self.mods.remove(self.rng.choice(by[remove_from]))  # still random within that side
        self.mods.append(_ess_mod(e))
        return True

    def chaos(self):
        self.use("Chaos Orb")
        if self.mods:
            self.mods.remove(self.rng.choice(self.mods))
        self.pool.add(self.rng, self.mods)

    def annul(self, side: str | None = None):
        if side:
            self.use(OMEN_ANNUL[side])
        self.use("Orb of Annulment")
        cands = [m for m in self.mods if side is None or m["type"] == side]
        if cands:
            self.mods.remove(self.rng.choice(cands))

    def desecrated(self) -> dict | None:
        return next((m for m in self.mods if m.get("des")), None)

    def desecrate(self, side: str) -> bool:
        """Bone + reveal: take a wanted option when one shows up (reroll once with Omen of Abyssal Echoes)."""
        c = self.counts()
        if self.desecrated() or c[side] >= 3:
            return False
        if c[SIDES[1 - SIDES.index(side)]] < 3:
            self.use(OMEN_NECRO[side])  # both sides open: make it this side
        self.use(self.bone)
        min_lvl = BONE_MIN.get(self.bone, 0)  # Ancient bones: mods of level 40+ (from poe2db, craft_rules)
        need = set(self.want.missing(self.mods))
        chosen = None
        for attempt in range(2):
            opts = []
            for _ in range(REVEAL_OPTIONS):
                o = self.pool.pick(self.rng, self.mods, [side], min_lvl, reveal=True, avoid=opts)
                if o:
                    opts.append(o)
            good = [o for o in opts if self.want.key_of(o) in need]
            if good:
                chosen = good[0]
                break
            if attempt == 0:
                self.use(ECHOES)
            elif opts:
                chosen = opts[0]  # nothing wanted: one of them has to be taken
        if chosen:
            self.mods.append({**chosen, "des": True, "_tmp": True})
        return True

    def blocked_side(self) -> str | None:
        """A side that is full, still misses a wanted mod and holds junk: something has to go."""
        miss = self.want.missing_sides(self.mods)
        for s in SIDES:
            mine = [m for m in self.mods if m["type"] == s]
            if len(mine) >= 3 and s in miss and any(not self.want.hit(m) for m in mine):
                return s
        return None

    def until_done(self, fixer: str, perfect: list, cap: int):
        """The way players finish a rare: add mods one by one (omens steer the Exalt to the side that still needs
        mods). When a full side holds junk instead of a wanted mod, remove one (Chaos, Annulment, Annulment with a
        side omen; a junk desecrated mod: Omen of Light + Annulment). A Perfect Essence gives a missing mod it
        guarantees. With a bone, the last missing mod comes from a Desecration (pick 1 of 3)."""
        k = len(self.want.min)
        for _ in range(cap):
            self.mark()
            miss = self.want.missing(self.mods)
            if not miss:
                return
            if any(e["for"] in miss and self.perfect_essence(e) for e in perfect):
                continue
            c = self.counts()
            if self.bone and not self.desecrated():
                last = len(miss) == 1 or len(self.mods) == 5
                side = self.want.side[miss[0]]
                if last and c[side] < 3 and self.desecrate(side):
                    continue
            d = self.desecrated()
            side = self.blocked_side()
            if d and not self.want.hit(d) and (side == d["type"] or len(self.mods) >= 6):
                self.use(LIGHT)
                self.use("Orb of Annulment")
                self.mods.remove(d)
                continue
            if side or len(self.mods) >= 6:
                if fixer == "chaos":
                    self.chaos()
                elif fixer == "annul_omen" and side:
                    self.annul(side)
                else:
                    self.annul()
            else:
                self.exalt(omens=True)
        self.mark()


def _usable_essences(want: _Want, ess_by_fam: dict) -> tuple[list, list]:
    """Essences that give a wanted mod at the wanted tier: (normal ones, one per wanted mod, cheapest first;
    perfect ones)."""
    usable = {}
    for w in want.w:
        for f in w["fams"]:
            for e in ess_by_fam.get(f, []):
                if e["mod_level"] >= want.min[w["key"]] and e["affix"] == w["type"]:
                    usable[e["name"]] = {**e, "price": _price(e["name"]), "for": w["key"]}
    key = lambda e: (e["price"] is None, e["price"] or 0, e["mod_level"])  # noqa: E731
    normal, seen = [], set()
    for e in sorted((e for e in usable.values() if not e["perfect"]), key=key):
        if e["for"] not in seen:
            seen.add(e["for"])
            normal.append(e)
    return normal, sorted((e for e in usable.values() if e["perfect"]), key=key)


def _routes(pool: _Pool, want: _Want, ilvl: int, first: dict | None, perfect: list, basic: bool,
            bone: str | None) -> list:
    """Route definitions (key, name, about, function(run), orbs). `first`: the essence that makes the item rare;
    `basic`: also the routes without essences; `bone`: the Desecration bone for this base (None: no desecration)."""
    k = len(want.min)
    perf_one, seen = [], set()
    for e in perfect:
        if (not first or e["for"] != first["for"]) and e["for"] not in seen:
            seen.add(e["for"])
            perf_one.append(e)

    def start_essence(r):
        fams = set(first["fams"])
        for _ in range(50):  # the transmute mod must not be the essence's own family: else take a new base
            r.mods.clear()
            r.use("Orb of Transmutation")
            m = r.pool.add(r.rng, r.mods)
            if not m or not (m["fams"] & fams):
                break
        r.use(first["name"])
        r.mods.append(_ess_mod(first))

    routes = []
    tail_p = [e["name"] for e in perf_one] + (list(OMEN_CRYST.values()) if perf_one else [])
    bone_orbs = [bone, ECHOES, LIGHT, "Orb of Annulment"] + list(OMEN_NECRO.values()) if bone else []

    def cheap(r):
        r.use("Orb of Transmutation"); r.pool.add(r.rng, r.mods)
        r.use("Orb of Augmentation"); r.pool.add(r.rng, r.mods)
        r.use("Regal Orb"); r.pool.add(r.rng, r.mods)
        r.fill()
    if basic:
        routes.append(("random", t("Cheapest lottery", "Najtańsza loteria"),
                       t("Transmutation, Augmentation, Regal, then Exalts up to 6 mods. Only cheap orbs, pure luck.",
                         "Transmutation, Augmentation, Regal, potem Exalty do 6 modów. Same tanie orby, czysty los."),
                       cheap, ["Orb of Transmutation", "Orb of Augmentation", "Regal Orb", "Exalted Orb"]))

    def alch(r):
        r.use("Orb of Alchemy")
        for _ in range(4):
            r.pool.add(r.rng, r.mods)
        r.fill()
    if basic:
        routes.append(("alchemy", t("Alchemy + Exalts", "Alchemy + Exalty"),
                       t("Orb of Alchemy gives 4 mods at once, then 2 Exalts. Fast, but also luck.",
                         "Orb of Alchemy daje od razu 4 mody, potem 2 Exalty. Szybko, ale też los."), alch,
                       ["Orb of Alchemy", "Exalted Orb"]))

    if first:
        def ess(r):
            start_essence(r)
            r.fill(omens=True)
        routes.append(("essence", t(f"{first['name']} + Exalts with omens", f"{first['name']} + Exalty z omenami"),
                       t(f"{first['name']} guarantees: {resolve_ranges(first['mod_text'], 'mid')}. "
                         "Then Exalts; when only one kind of mod is missing, Omen of Sinistral/Dextral Exaltation "
                         "steers the Exalt to a prefix or a suffix.",
                         f"{first['name']} daje na pewno: {resolve_ranges(first['mod_text'], 'mid')}. "
                         "Potem Exalty; gdy brakuje modów tylko jednego typu, omen Sinistral/Dextral Exaltation "
                         "kieruje Exalta na prefix albo suffix."), ess,
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
                if e["for"] in want.missing(r.mods):
                    r.perfect_essence(e)
            r.fill(omens=True)
        names = ", ".join(e["name"] for e in perf_one)
        lead = first["name"] + " + " if first else ""
        routes.append(("perfect", t(f"{lead}Exalts + Perfect Essence", f"{lead}Exalty + Perfect Essence"),
                       t((f"{first['name']} to start, " if first else "") + f"Exalts with omens, and at the end {names}: "
                         "a Perfect Essence removes a random mod (with Omen of Crystallisation only from the same side) "
                         "and adds its own mod for sure.",
                         (f"{first['name']} na start, " if first else "") + f"Exalty z omenami, a na koniec {names}: "
                         "Perfect Essence usuwa losowy mod (z omenem Crystallisation tylko z tej samej strony) "
                         "i daje swój mod na pewno."), ess_perf,
                       (["Orb of Transmutation"] + ([first["name"]] if first else ["Regal Orb"]) +
                        ["Exalted Orb", "Omen of Sinistral Exaltation", "Omen of Dextral Exaltation"] + tail_p)))
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
                           t(f"{orb} adds only mods of level {MIN_LEVEL[orb]}+: less junk and fewer low tiers, "
                             "but more expensive per orb.",
                             f"{orb} dodaje tylko mody od {MIN_LEVEL[orb]} poziomu: mniej śmieci i niskich tierów, "
                             "ale drożej za sztukę."), high,
                           ["Orb of Transmutation", first["name"] if first else "Regal Orb", orb,
                            "Omen of Sinistral Exaltation", "Omen of Dextral Exaltation"]))

    bone_txt = t(f" The last missing mod: {bone} (desecration); at the Well of Souls you pick 1 of 3 options; when none "
                 "fits, Omen of Abyssal Echoes rerolls the options once, and Omen of Light with an Annulment removes a "
                 "wrong desecrated mod.",
                 f" Ostatni brakujący mod: {bone} (desecration), w Well of Souls wybierasz 1 z 3 opcji; gdy żadna nie "
                 "pasuje, Omen of Abyssal Echoes losuje opcje jeszcze raz, a zły desecrated mod zdejmuje Omen of Light "
                 "z Annulmentem.") if bone else ""
    if basic and k >= 3:
        def farm_then_finish(r, fixer):
            need = k - 1
            for _ in range(FARM_TRIES):  # cheap bases until one has all but one wanted mod
                one = _Run(pool, want, r.rng, r.prices)
                one.use("Orb of Transmutation"); pool.add(one.rng, one.mods)
                one.use("Orb of Augmentation"); pool.add(one.rng, one.mods)
                one.use("Regal Orb"); pool.add(one.rng, one.mods)
                while len(one.mods) < 6:  # stop while the slot is still open: 5 good mods and room for the last
                    if want.hits(one.mods) >= need and want.hits(one.mods) == len(one.mods):
                        break
                    before = len(one.mods)
                    one.exalt()
                    if len(one.mods) == before:
                        break
                r.used.update(one.used)
                r.spent += one.spent
                if want.hits(one.mods) >= need:
                    r.mods = one.mods
                    break
            else:
                return
            r.until_done(fixer, perf_one, LOOP_CAP)
        fixers = [("annul_omen", t("Annul with a side omen", "Annul z omenem strony"),
                   ["Orb of Annulment"] + list(OMEN_ANNUL.values()), None),
                  ("chaos", "Chaos", ["Chaos Orb"], None)]
        if bone:
            fixers.append(("bone", "desecration", bone_orbs, bone))
        for fixer, label, orbs, b in fixers:
            def fn(r, fx=fixer, b=b):
                r.bone = b
                farm_then_finish(r, "annul" if fx == "bone" else fx)  # Annul opens the slot the bone needs
            routes.append((f"farm_{fixer}", t(f"Cheap bases to {k - 1}/{k}, then {label}",
                                              f"Tanie bazy do {k - 1}/{k}, potem {label}"),
                           t(f"Make cheap items (Transmutation, Augmentation, Regal, Exalts) until one has {k - 1} of {k} "
                             "mods. Finish that one: ",
                             f"Robisz tanie itemy (Transmutation, Augmentation, Regal, Exalty), aż jeden ma {k - 1} z {k} "
                             "modów. Ten jeden dokańczasz: ") +
                           ({"annul_omen": t("Orb of Annulment with Omen of Sinistral/Dextral Annulment removes a mod "
                                             "only from the full side, and an Exalt with an omen adds the missing kind.",
                                             "Orb of Annulment z omenem Sinistral/Dextral Annulment usuwa mod tylko z "
                                             "pełnej strony, a Exalt z omenem dokłada brakujący typ."),
                             "chaos": t("Chaos Orb swaps a random mod until the missing one lands.",
                                        "Chaos Orb wymienia losowy mod, aż wejdzie brakujący."),
                             "bone": t("a bone (desecration) offers 1 of 3 mods.",
                                       "kość (desecration) daje wybór 1 z 3 modów.") + bone_txt}[fixer]),
                           fn, ["Orb of Transmutation", "Orb of Augmentation", "Regal Orb", "Exalted Orb",
                                "Omen of Sinistral Exaltation", "Omen of Dextral Exaltation"] + orbs + tail_p))

    # finishing on one base: add mods one by one and remove what blocks a wanted slot
    def begin(r):
        if first:
            start_essence(r)
        else:
            r.use("Orb of Transmutation"); r.pool.add(r.rng, r.mods)
            r.use("Regal Orb"); r.pool.add(r.rng, r.mods)
    head = first["name"] if first else "Regal Orb"
    pnames = ", ".join(e["name"] for e in perf_one)
    perf_txt = t(f" The missing mod from a Perfect Essence ({pnames}) lands for sure, and Omen of Crystallisation picks "
                 "the side the removed mod comes from.",
                 f" Brakujący mod z Perfect Essence ({pnames}) wchodzi na pewno, a omen "
                 "Crystallisation wybiera, z której strony wypada mod.") if perf_one else ""
    if first or basic:
        start_txt = (t("An essence to start, then ", "Esencja na start, potem ") if first
                     else t("Transmutation + Regal, then ", "Transmutation + Regal, potem "))
        routes.append(("loop_chaos", t(f"{head} + Exalt/Chaos until done", f"{head} + Exalt/Chaos do skutku"),
                       start_txt + t("Exalt after Exalt (an omen steers it to the prefix or suffix still missing). When "
                                     "junk takes the slot a wanted mod needs: Chaos Orb (removes a random mod, adds a "
                                     "random one) and on. One base, until everything is in.",
                                     "Exalt po Exalcie (omen kieruje go na prefix albo suffix, którego brakuje). Gdy śmieć "
                                     "zajmuje miejsce potrzebnego moda: Chaos Orb (usuwa losowy mod, dodaje losowy) i "
                                     "dalej. Jedna baza, aż wejdzie wszystko.") + perf_txt,
                       lambda r: (begin(r), r.until_done("chaos", perf_one, LOOP_CAP)),
                       ["Orb of Transmutation", head, "Exalted Orb", "Omen of Sinistral Exaltation",
                        "Omen of Dextral Exaltation", "Chaos Orb"] + tail_p))
        if bone:
            def loop_bone(r):
                r.bone = bone
                begin(r)
                r.until_done("annul", perf_one, LOOP_CAP)
            routes.append(("loop_bone", t(f"{head} + Exalts + desecration", f"{head} + Exalty + desecration"),
                           start_txt + t("Exalts with omens, Annulment removes junk.", "Exalty z omenami, śmieci zdejmuje Annul.")
                           + bone_txt + perf_txt, loop_bone,
                           ["Orb of Transmutation", head, "Exalted Orb", "Omen of Sinistral Exaltation",
                            "Omen of Dextral Exaltation"] + bone_orbs + tail_p))
    return routes


def _bone_for(base: dict, wanted: list[dict], ilvl: int) -> str | None:
    kind = poe2db.bone_kind(base)
    if not kind or ilvl < 1:
        return None
    hi = max(int(w.get("min_level") or 0) for w in wanted)
    ancient = f"Ancient {poe2db.BONE[kind]}"
    return ancient if hi >= BONE_MIN.get(ancient, 40) else f"Preserved {poe2db.BONE[kind]}"


def craft_routes(kb, base_name: str, ilvl: int, wanted: list[dict], sims: int = 2000, seed: int = 11) -> dict:
    """wanted: [{"group": mod group, "type": "Prefix"|"Suffix", "min_level": minimum mod level (0 = any tier)}]."""
    base = kb.base(base_name)
    if not base:
        raise ValueError(f"unknown base {base_name!r}")
    if not wanted:
        raise ValueError("pick at least one mod")
    groups = pool_by_group(kb, base["name"], ilvl)
    ess_by_fam = _essence_index(kb, base, ilvl)
    data = poe2db.for_base(base)
    problems, resolved = [], []
    for w in wanted:
        tiers = groups.get((w["type"], w["group"])) or []
        mn = int(w.get("min_level") or 0)
        if tiers:
            fams = frozenset(tiers[0]["fams"])
        else:  # essence-only mod
            hit = [e for rows in ess_by_fam.values() for e in rows if e["grp"] == w["group"] and e["affix"] == w["type"]]
            fams = frozenset(hit[0]["fams"]) if hit else frozenset([family(w["group"])])
        ok = [t for t in tiers if (t["level"] or 1) >= mn]
        if not ok and not any(e["mod_level"] >= mn for f in fams for e in ess_by_fam.get(f, [])):
            problems.append(t(f"{w['group']}: this tier does not roll on this base at item level {ilvl}.",
                              f"{w['group']}: ten tier nie wypada na tej bazie przy item level {ilvl}."))
        resolved.append({"key": fkey(fams), "fams": fams, "type": w["type"], "min_level": mn, "group": w["group"]})
    for i, a in enumerate(resolved):
        if any(a["fams"] & b["fams"] for b in resolved[i + 1:]):
            problems.append(t("Two picked mods are from the same family: an item can have only one of them.",
                              "Dwa wybrane mody są z tej samej rodziny: na itemie może być tylko jeden z nich."))
            break
    for side in SIDES:
        if sum(w["type"] == side for w in resolved) > 3:
            problems.append(t(f"Too many {side} mods: 3 at most.", f"Za dużo modów typu {side}: najwyżej 3."))
    need_ilvl = max(w["min_level"] for w in resolved)
    # mods that almost never roll (poe2db weight like 1 against 1000): say so before the numbers
    side_w = Counter()
    for (atype, _), tiers in groups.items():
        side_w[atype] += sum(t["w"] for t in tiers)
    warnings = []
    for w in resolved:
        tiers = [t for t in groups.get((w["type"], w["group"])) or [] if (t["level"] or 1) >= w["min_level"]]
        share = sum(t["w"] for t in tiers) / side_w[w["type"]] * 100 if side_w[w["type"]] else 0
        w["chance_pct"] = round(share, 3)
        has_ess = any(e["mod_level"] >= w["min_level"] for f in w["fams"] for e in ess_by_fam.get(f, []))
        if share < 0.5 and not has_ess:
            text = (tiers or (groups.get((w["type"], w["group"])) or [{"text": w["group"]}]))[0]["text"]
            warnings.append(t(f"{text}: almost never rolls on this base (chance for a random {w['type'].lower()} "
                              f"{share:.2f}%, poe2db weight), and no essence gives it. A goal with this mod is very "
                              "expensive; consider another mod or buy a finished item.",
                              f"{text}: na tej bazie prawie nie wypada (szansa na losowy {w['type'].lower()} "
                              f"{share:.2f}%, waga z poe2db), a żadna esencja go nie daje. Cel z tym modem jest bardzo "
                              "drogi; rozważ inny mod albo kup gotowy item."))
    if problems:
        return {"base": base["name"], "item_level": ilvl, "possible": False, "problems": problems, "routes": []}

    from soe.kb import craft_rules

    levels = craft_rules.min_levels()  # what poe2db says today; the code's defaults otherwise
    MIN_LEVEL.update({k: levels[k] for k in ("Greater Exalted Orb", "Perfect Exalted Orb") if k in levels})
    BONE_MIN.clear()
    BONE_MIN.update({k: v for k, v in levels.items() if k.startswith("Ancient")})
    rules = craft_rules.report()
    pool = _Pool(groups, set(base.get("tags") or []), data, ilvl)
    want = _Want(resolved)
    normal, perfect = _usable_essences(want, ess_by_fam)
    bone = _bone_for(base, wanted, ilvl) if data else None
    defs = []
    for j, first in enumerate([None] + normal[:3]):  # every wanted mod an essence can start with
        defs += [d for d in _routes(pool, want, ilvl, first, perfect, basic=j == 0, bone=bone)
                 if j <= 1 or not d[0].startswith("loop")]  # long loops: only the cheapest essence
    k = len(want.min)
    out = []
    for i, (key, name, about, fn, orbs) in enumerate(defs):
        rng = random.Random(seed + i)
        n_ok, hist, used, spends = 0, Counter(), Counter(), []
        ladder_cost, ladder_hit = Counter(), Counter()
        prices = {o: _price(o) for o in dict.fromkeys(orbs)}
        multi = key.startswith(("loop", "farm"))
        target = max(60, sims // 30) if multi else sims  # loops take many steps per try
        n_sims, t0 = 0, time.perf_counter()
        # one-shot routes are cheap to simulate: go on while the full goal is too rare to measure
        while n_sims < target or (key in EXTEND and n_ok < 25 and n_sims < ONE_SHOT_MAX and time.perf_counter() - t0 < 1.2):
            n_sims += 1
            r = _Run(pool, want, rng, prices)
            fn(r)
            r.mark()
            h = want.hits(r.mods)
            hist[h] += 1
            n_ok += h == k
            used.update(r.used)
            spends.append(r.spent)
            for j in range(1, k + 1):  # spend until j hits (or the whole run when never reached)
                ladder_cost[j] += r.reached.get(j, r.spent)
                ladder_hit[j] += j in r.reached
        p = n_ok / n_sims
        steps, cost, known = [], 0.0, True
        for orb in dict.fromkeys(orbs):
            avg = used[orb] / n_sims
            if avg <= 0:
                continue
            price = prices[orb]
            if price is None:
                known = False
            else:
                cost += price * avg
            steps.append({"orb": orb, "avg_count": round(avg, 2), "price_divine": price})
        out.append({"key": key, "name": name, "about": about, "steps": steps,
                    "chance_pct": round(p * 100, 4),
                    "at_least_pct": {j: round(sum(v for h, v in hist.items() if h >= j) / n_sims * 100, 1)
                                     for j in range(1, k + 1)},
                    "cost_try_divine": round(cost, 3), "cost_complete": known,
                    "tries": round(1 / p, 1) if p else None,
                    "expected_divine": round(cost / p, 3) if p else None,
                    "loop": multi,
                    # what it costs to stop at j wanted mods: one-shot routes repeat on new bases, loops go on
                    "ladder": {j: {"pct": round(ladder_hit[j] / n_sims * 100, 1),
                                   "expected_divine": (round(ladder_cost[j] / ladder_hit[j], 3) if multi
                                                       else round(cost / (ladder_hit[j] / n_sims), 3)) if ladder_hit[j] else None}
                               for j in range(1, k + 1) if not key.startswith("farm") or j >= k - 1},
                    "p90_divine": round(sorted(spends)[int(len(spends) * 0.9) - 1], 3) if multi and spends else None})
    # per kind of route keep the essence that works best
    best_of: dict[str, dict] = {}
    rank = lambda x: (x["expected_divine"] is None, x["expected_divine"] or 0, -x["chance_pct"])  # noqa: E731
    for r in out:
        cur = best_of.get(r["key"])
        if cur is None or rank(r) < rank(cur):
            best_of[r["key"]] = r
    out = list(best_of.values())
    alive = [r for r in out if r["chance_pct"] > 0 and not r["loop"]]  # chance per try: one-shot routes only
    if alive:  # a route that never reaches the goal gets no badge
        best = max(alive, key=lambda r: (r["chance_pct"], -(r["expected_divine"] or 0)))
        best["badges"] = [t("surest", "najpewniejsza")]
    priced = [r for r in out if r["expected_divine"] is not None]
    if priced:
        cheap = min(priced, key=lambda r: r["expected_divine"])
        cheap.setdefault("badges", []).append(t("cheapest until done", "najtańsza do skutku"))
    out.sort(key=lambda r: (r["expected_divine"] is None, r["expected_divine"] or 0))
    realistic = []
    for j in range(max(1, k - 3), k + 1):  # the cheapest way to j of the k wanted mods
        opts = [(r["ladder"][j]["expected_divine"], r["name"]) for r in out
                if j in r["ladder"] and r["ladder"][j]["expected_divine"] is not None]
        if opts:
            c, n = min(opts)
            realistic.append({"hits": j, "of": k, "expected_divine": c, "route": n})
    page = poe2db.page_for_base(base)
    src = (t(f"Mod weights, families, essences and desecrated mods: poe2db ({page}).",
             f"Wagi modów, rodziny, esencje i mody desecrated: poe2db ({page}).") if data else
           t("No poe2db data for this base: equal weights from PoB's data (less accurate).",
             "Brak danych z poe2db dla tej bazy: równe wagi z danych PoB (mniej dokładne)."))
    return {"base": base["name"], "item_level": ilvl, "need_item_level": need_ilvl, "possible": True,
            "weights": "poe2db" if data else "equal", "bone": bone, "warnings": warnings,
            "rules_changes": [c["text"] + (t(f" (the Forge assumes: {c['assumes']})", f" (Kuźnia zakłada: {c['assumes']})")
                                           if c.get("assumes") else "")
                              for c in rules["changes"]],
            "wanted": [{"group": w["group"], "type": w["type"], "min_level": w["min_level"], "family": w["key"],
                        "chance_pct": w["chance_pct"]}
                       for w in resolved], "routes": out, "realistic": realistic,
            "note": src + t(" Odds: a simulation on these weights. Desecration: poe2db does not say how often the options "
                            "are the base's normal mods, so a desecration-only mod counts like a typical mod of that side. "
                            "Cost: poe.ninja prices, without the base. 'Until done' for one try = cost of a try / chance; "
                            f"routes on one base count the whole craft (at most {LOOP_CAP} orb uses).",
                            " Szanse: symulacja na tych wagach. Desecration: poe2db nie podaje, jak często opcje to "
                            "zwykłe mody bazy, więc mod tylko z desecration liczę jak typowy mod tej strony. Koszt: ceny z "
                            "poe.ninja, bez ceny bazy. 'Do skutku' przy jednej próbie = koszt próby / szansa; drogi na "
                            f"jednej bazie liczą cały craft (najwyżej {LOOP_CAP} użyć orbów).")}
