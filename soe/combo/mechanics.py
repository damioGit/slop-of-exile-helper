"""Combo engine: which game mechanics a build creates and which it feeds on.

Reads the text of everything the build uses (skill and support gems from the knowledge base,
allocated passives in the active weapon set, equipped items) and matches it against a dictionary
of mechanics, each with "produces" and "benefits" patterns and, where PoB has one, the config
switch that turns the condition on.

From that:
- payoffs:  things in the game data that benefit from what the build already produces
- enablers: things that produce what the build benefits from but does not create itself
- config check: conditions switched on in PoB's config that nothing in the build creates
  (those numbers are optimistic until the build can actually apply the condition)
Payoffs and enablers that can be tested in PoB (supports for the main skill, reachable notables,
uniques for a slot) are measured; the rest are listed as leads.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from soe.optimize.objective import Objective


@dataclass(frozen=True)
class Mechanic:
    name: str
    produces: str
    benefits: str
    config: str | None = None


def _rx(p: str) -> re.Pattern:
    return re.compile(p, re.I)


MECHANICS = [
    Mechanic("Shock", r"\bshocks? (enemies|on hit|targets)|chance to shock|inflicts? shock|\bshocking\b|creates? shocked ground",
             r"against shocked|shocked enemies|enemies (that are |you )?shock(ed)?\b.*(take|have)|consumes? shock", "conditionEnemyShocked"),
    Mechanic("Ignite", r"\bignites? (enemies|on hit)|chance to ignite|inflicts? ignite|creates? ignited ground|flammability magnitude",
             r"against ignited|ignited enemies|consumes? ignite", "conditionEnemyIgnited"),
    Mechanic("Chill", r"\bchills? (enemies|on hit)|inflicts? chill|creates? chilled ground|chill magnitude",
             r"against chilled|chilled enemies", "conditionEnemyChilled"),
    Mechanic("Freeze", r"\bfreezes? (enemies|on hit)|chance to freeze|freeze buildup|inflicts? freeze",
             r"against frozen|frozen enemies|shatter", "conditionEnemyFrozen"),
    Mechanic("Electrocute", r"\belectrocutes?\b(?! enemies take)|electrocute buildup",
             r"against electrocuted|electrocuted enemies", "conditionEnemyElectrocuted"),
    Mechanic("Bleeding", r"(inflict|cause)s? bleeding|chance to (inflict |cause )?bleed|aggravates? bleeding",
             r"against bleeding|bleeding enemies", "conditionEnemyBleeding"),
    Mechanic("Poison", r"\bpoisons? (enemies|on hit)|chance to poison|inflicts? poison",
             r"against poisoned|poisoned enemies|per poison", "conditionEnemyPoisoned"),
    Mechanic("Blind", r"\bblinds? (enemies|on hit|targets)|^blinds enemies|inflicts? blind",
             r"against blinded|blinded enemies", "conditionEnemyBlinded"),
    Mechanic("Maim", r"\bmaims? (enemies|on hit)|chance to maim", r"against maimed|maimed enemies", "conditionEnemyMaimed"),
    Mechanic("Armour Break", r"breaks? (\w+ )?armour|armour break",
             r"fully broken armour|against enemies with broken armour", "conditionEnemyArmourBroken"),
    Mechanic("Exposure", r"inflicts? (\w+ )?exposure|exposure on hit",
             r"against enemies with (\w+ )?exposure", "conditionEnemyFireExposure"),
    Mechanic("Heavy Stun", r"heavy stun|stun buildup", r"against (heavy )?stunned|primed for stun", "conditionEnemyHeavyStunned"),
    Mechanic("Pin", r"\bpins? (enemies|on hit)|pin buildup", r"against pinned|pinned enemies", "conditionEnemyPinned"),
    Mechanic("Daze", r"\bdazes? (enemies|on hit)|daze buildup", r"against dazed|dazed enemies", "conditionEnemyDazed"),
    Mechanic("Curse", r"\bcurses? (enemies|targets)|curse skill", r"against cursed|cursed enemies", "conditionEnemyCursed"),
    Mechanic("Frenzy Charge", r"gain(s)? (a |an |\d+ )?frenzy charges?|frenzy charge on",
             r"per frenzy charge|consumes? (\w+ )?frenzy charges?", "useFrenzyCharges"),
    Mechanic("Power Charge", r"gain(s)? (a |an |\d+ )?power charges?|power charge on",
             r"per power charge|consumes? (\w+ )?power charges?", "usePowerCharges"),
    Mechanic("Endurance Charge", r"gain(s)? (a |an |\d+ )?endurance charges?|endurance charge on",
             r"per endurance charge|consumes? (\w+ )?endurance charges?", "useEnduranceCharges"),
    Mechanic("Whirlwind", r"creates? (a )?whirlwind|leaves? (a )?whirlwind|kicks up a whirlwind|^whirlwind: ",
             r"consumes? whirlwinds?"),
    Mechanic("Infusion", r"(gain|grants?|creates?) (a |an )?(fire |cold |lightning )?infusion",
             r"consumes? (a |an )?(fire |cold |lightning )?infusion"),
    Mechanic("Elemental Ground", r"creates? (shocked|ignited|chilled|burning) ground|leaves? (a trail of )?(shocked|ignited|chilled) ground",
             r"boosted by (\w+ )?(elemental )?ground|elemental ground surfaces"),
    Mechanic("Onslaught", r"gain(s)? onslaught|grants? onslaught", r"while you have onslaught", "buffOnslaught"),
    Mechanic("Rage", r"gain(s)? (\d+ )?rage|grants? rage", r"per (\d+ )?rage|while (you have|at maximum) rage|consumes? rage", "multiplierRage"),
    Mechanic("Herald", r"^herald of", r"while affected by herald"),
    Mechanic("Arcane Surge", r"gain(s)? arcane surge|grants? arcane surge", r"while you have arcane surge", "buffArcaneSurge"),
]
_PROD = {m.name: _rx(m.produces) for m in MECHANICS}
_BEN = {m.name: _rx(m.benefits) for m in MECHANICS}


def classify(lines: list[str]) -> tuple[set, set]:
    prod, ben = set(), set()
    for ln in lines:
        for m in MECHANICS:
            if _PROD[m.name].search(ln):
                prod.add(m.name)
            if _BEN[m.name].search(ln):
                ben.add(m.name)
    return prod, ben


_TAGS = re.compile(r"\{[^}]*\}")


def build_corpus(session) -> list[tuple[str, str]]:
    """(source, line) for everything the build uses."""
    pob, kb = session.pob, session.kb
    out = []
    for g in pob.groups():
        if not g["enabled"]:
            continue
        for gem in g["gems"]:
            if not gem["enabled"]:
                continue
            row = kb.gem(gem["name"])
            if row:
                out.append((f"gem: {gem['name']}", gem["name"]))
                out += [(f"gem: {gem['name']}", ln) for ln in (row.get("stats_text") or []) + [row.get("description") or ""]]
    for n in pob.allocated_nodes():
        if n["active"]:
            out += [(f"passive: {n['name']}", ln) for ln in n["stats"]]
    for it in pob.items(active_only=True):
        lines = it["raw"].split("\n")
        start = next((i for i, ln in enumerate(lines) if ln.startswith("Implicits:")), 0)
        out += [(f"item: {it['name']}", _TAGS.sub("", ln)) for ln in lines[start + 1:] if ln.strip()]
    return out


def profile(session) -> dict:
    corpus = build_corpus(session)
    produced: dict[str, set] = {}
    benefits: dict[str, set] = {}
    for src, ln in corpus:
        for m in MECHANICS:
            if _PROD[m.name].search(ln):
                produced.setdefault(m.name, set()).add(src)
            if _BEN[m.name].search(ln):
                benefits.setdefault(m.name, set()).add(src)
    return {"produces": {k: sorted(v) for k, v in produced.items()},
            "benefits_from": {k: sorted(v) for k, v in benefits.items()}}


def config_check(session, prof: dict) -> list[dict]:
    opts = {o["var"]: o.get("value") for o in session.pob.config_options()}
    out = []
    for m in MECHANICS:
        if m.config and opts.get(m.config) not in (None, False, 0) and m.name not in prof["produces"]:
            out.append({"mechanic": m.name, "config": m.config, "value": opts.get(m.config),
                        "issue": f"PoB's config assumes {m.name} is up, but nothing in the build text creates it. "
                                 "The numbers include its bonus; check it is really applied in game (another player, "
                                 "an ailment from a different source, or PoB's own guaranteed source)."})
    return out


class _Ctx:
    """Things every mechanic needs, computed once per suggest_combos call."""

    def __init__(self, session, max_cost: int):
        pob = session.pob
        self.main = next((g for g in pob.groups() if g["main"]), None)
        active = next((x for x in self.main["gems"] if not x["support"]), None) if self.main else None
        self.supports = session.kb.supports_for(active["name"]) if active else []
        self.reach = [(n, pob.node_info(n["id"])) for t in ("Notable", "Keystone")
                      for n in pob.reachable(t, 3000) if n["cost"] <= max_cost]
        self.uniques = session.kb._rows("SELECT name, base, slot_type, implicits, mods FROM uniques")
        self.node_scores: dict[int, dict] = {}
        self.support_scores: dict[str, tuple] = {}
        self.unique_scores: dict[str, dict | None] = {}


def _measure_supports(session, ctx: _Ctx, mechanic: str, kind: str, obj: Objective, limit: int) -> list[dict]:
    """Supports for the main skill whose text produces (kind='produces') / benefits from a mechanic."""
    pob = session.pob
    main = ctx.main
    if not main:
        return []
    rx = _PROD[mechanic] if kind == "produces" else _BEN[mechanic]
    have = {x["name"] for x in main["gems"]}
    cands = [s for s in ctx.supports if s["name"] not in have
             and any(rx.search(ln) for ln in s["stats_text"] + [s.get("description") or ""])]
    if not cands:
        return []
    slots = [(i, x) for i, x in enumerate(main["gems"], 1) if x["support"]]
    todo = [s["name"] for s in cands[:limit] if s["name"] not in ctx.support_scores]
    if todo:
        # every (candidate, slot) as a fast do/undo job on the process pool
        jobs, meta = [], []
        for name in todo:
            for idx, old in slots:
                jobs.append({"do": [["set_gem", {"group": main["index"], "gem": idx, "name": name}]],
                             "undo": [["set_gem", {"group": main["index"], "gem": idx, "name": old["name"],
                                                   "level": old["level"], "quality": old["quality"],
                                                   "enabled": old["enabled"]}]]})
                meta.append((name, old["name"]))
        for (name, old), r in zip(meta, session.pool().run(jobs, chunksize=2)):
            if not r["ok"]:
                continue
            ex = obj.explain(r["result"], session.base)
            if name not in ctx.support_scores or ex["score"] > ctx.support_scores[name][1]["score"]:
                ctx.support_scores[name] = (old, ex)
    out = []
    for s in cands[:limit]:
        if s["name"] in ctx.support_scores:
            old, ex = ctx.support_scores[s["name"]]
            out.append({"support": s["name"], "replaces": old, **ex,
                        "text": [ln for ln in s["stats_text"] if rx.search(ln)][:2]})
    out.sort(key=lambda r: r["score"], reverse=True)
    return out


def _measure_notables(session, ctx: _Ctx, mechanic: str, kind: str, obj: Objective, limit: int) -> list[dict]:
    pob = session.pob
    rx = _PROD[mechanic] if kind == "produces" else _BEN[mechanic]
    rows = []
    for n, info in ctx.reach:
        hits = [ln for ln in info["stats"] if rx.search(ln)]
        if not hits:
            continue
        if n["id"] not in ctx.node_scores:
            w = pob.whatif(add_nodes=[n["id"]], with_path=True)
            ctx.node_scores[n["id"]] = {"points": w["points"], **obj.explain(w, session.base)}
        rows.append({"passive": n["name"], **ctx.node_scores[n["id"]], "text": hits})
    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows[:limit]


def _leads(session, ctx: _Ctx, mechanic: str, kind: str, limit: int, obj: Objective) -> list[dict]:
    """Uniques whose text matches, each put in its slot and measured; only real gains are kept."""
    from soe.items.uniques import try_unique

    rx = _PROD[mechanic] if kind == "produces" else _BEN[mechanic]
    out = []
    for r in ctx.uniques:
        hits = [ln for ln in r["implicits"] + r["mods"] if rx.search(ln)]
        if not hits:
            continue
        if r["name"] not in ctx.unique_scores:
            try:
                t = try_unique(session, r["name"], objective=obj)
                ctx.unique_scores[r["name"]] = {k: t[k] for k in ("slot", "score", "dps_pct", "ehp_pct", "price")}
            except Exception:
                ctx.unique_scores[r["name"]] = None
        sc = ctx.unique_scores[r["name"]]
        if sc and sc["score"] > MIN_GAIN:
            out.append({"unique": r["name"], "base": r["base"], **sc, "text": hits[:2]})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


MIN_GAIN = 0.5  # objective points (≈ %): below this a suggestion is noise


def suggest_combos(session, objective: Objective | None = None, max_cost: int = 6, per_mechanic: int = 4,
                   measure_supports: bool = True) -> dict:
    """Only suggestions that measure as a real gain in PoB are returned; a mechanic with nothing that
    helps is left out instead of listing loose text matches."""
    session._need_build()
    obj = objective or Objective()
    prof = profile(session)
    ctx = _Ctx(session, max_cost)
    produced, wants = set(prof["produces"]), set(prof["benefits_from"])
    payoffs, enablers = {}, {}
    for target, mechanics, kind in ((payoffs, sorted(produced), "benefits"), (enablers, sorted(wants - produced), "produces")):
        for m in mechanics:
            block = {"passives": [x for x in _measure_notables(session, ctx, m, kind, obj, per_mechanic * 2)
                                  if x["score"] > MIN_GAIN][:per_mechanic],
                     "uniques": _leads(session, ctx, m, kind, per_mechanic, obj)}
            if measure_supports:
                block["supports"] = [x for x in _measure_supports(session, ctx, m, kind, obj, per_mechanic * 2)
                                     if x["score"] > MIN_GAIN][:per_mechanic]
            if any(block.values()):
                target[m] = block
    return {
        "profile": prof,
        "config_check": config_check(session, prof),
        "payoffs": payoffs,
        "enablers": enablers,
        "note": "Every listed support, passive and unique was measured in PoB and gains at least "
                f"{MIN_GAIN}% on the goal; the mechanic profile itself is read from item, gem and passive text.",
    }
