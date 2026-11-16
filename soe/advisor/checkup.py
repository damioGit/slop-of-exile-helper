"""Build check-up: ranked findings about what holds a build back.

Idea and finding format adapted from Exile Build Advisor by reytla (MIT,
https://github.com/reytla/exile-build-adviser): every finding has a severity, a certainty, why it
matters, what fixing it gains, what to do, and weights for the player's goals. Unlike the original,
"does nothing" checks are measured with the Path of Building engine, not guessed from text.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

RES_CAP = 75
ELEMENTS = ("Fire", "Cold", "Lightning")
GOALS = ("damage", "survive", "mana", "ease", "speed")
DEFAULT_GOALS = {"damage": 2, "survive": 2, "mana": 1, "ease": 1, "speed": 1}
SEV_W = {"bad": 3, "warn": 2, "info": 1}
CERT_W = {"sure": 1.0, "likely": 0.8, "check": 0.5}
# stats compared when deciding whether something "does nothing"
EFFECT_KEYS = ("MainDPS", "CombinedDPS", "TotalEHP", "Life", "EnergyShield", "Mana", "Spirit", "Evasion", "Armour",
               "DeflectChance", "FireResist", "ColdResist", "LightningResist", "ChaosResist",
               "MovementSpeedMod", "ManaRegenRecovery", "LifeRegenRecovery", "EnergyShieldRecharge",
               "Str", "Dex", "Int", "SpiritUnreserved")


@dataclass
class Finding:
    id: str
    area: str
    title: str
    why: str
    effect: str
    action: list[str]
    severity: str = "info"        # bad / warn / info
    certainty: str = "sure"       # sure (PoB numbers) / likely / check (cannot be settled here)
    goals: dict = field(default_factory=dict)
    data: dict = field(default_factory=dict)
    score: float = 0.0


def score(f: Finding, goals: dict) -> float:
    total = sum(goals.values()) or 1
    goal_fit = sum(goals.get(g, 0) * w for g, w in f.goals.items()) / total if f.goals else 0.3
    return round(SEV_W[f.severity] * CERT_W[f.certainty] * (0.4 + goal_fit), 3)


def split_item(raw: str) -> tuple[list[str], list[str], list[str]]:
    """PoB item text -> (header lines, implicit lines, explicit lines)."""
    lines = raw.split("\n")
    for i, ln in enumerate(lines):
        if ln.startswith("Implicits:"):
            n = int(ln.split(":")[1])
            return lines[: i + 1], lines[i + 1: i + 1 + n], lines[i + 1 + n:]
    return lines, [], []


def join_item(header: list[str], implicits: list[str], explicits: list[str]) -> str:
    header = [f"Implicits: {len(implicits)}" if h.startswith("Implicits:") else h for h in header]
    return "\n".join(header + implicits + explicits)


_TAGS = re.compile(r"^(\{[^}]*\})+")


def _clean(line: str) -> str:
    return _TAGS.sub("", line)


def _no_effect(base: dict, w: dict, tol: float = 1e-6) -> bool:
    return all(abs((w.get(k) or 0) - (base.get(k) or 0)) <= tol * max(1, abs(base.get(k) or 0)) for k in EFFECT_KEYS)


def run_checkup(session, goals: dict | None = None, deep: bool = True) -> dict:
    """All findings for the loaded build, best value first. deep=False skips the per-node and
    per-mod measurements (about 2 s on a level 100 build)."""
    session._need_build()
    pob = session.pob
    s = session.base
    goals = {**DEFAULT_GOALS, **(goals or {})}
    F: list[Finding] = []

    # ---- resistances
    over = [e for e in ELEMENTS if (pob.output().get(f"{e}ResistOverCap") or 0) > 0]
    for e in ELEMENTS:
        v = s.get(f"{e}Resist", 0)
        if v >= RES_CAP:
            continue
        gap = RES_CAP - v
        less = 100 - 100 * (100 - RES_CAP) / (100 - v)
        F.append(Finding(
            id=f"res-{e.lower()}", area="Resistances",
            severity="bad" if gap >= 30 else "warn" if gap >= 10 else "info",
            title=f"{e} resistance {v}% ({gap} below cap)",
            why=f"Below {RES_CAP}% you take more {e.lower()} damage than needed.",
            effect=f"Capping it means about {less:.0f}% less {e.lower()} damage taken.",
            action=[f"Find +{gap}% {e} Resistance on gear (rings, amulet, belt, boots, gloves, helmet)."]
                   + ([f"You are over the cap on {', '.join(x.lower() for x in over)}: trade some of that for {e.lower()}."]
                      if over else []),
            goals={"survive": min(1.0, gap / 50)}, data={"stat": f"{e}Resist", "gap": gap}))
    chaos = s.get("ChaosResist", 0)
    if chaos < 0:
        F.append(Finding(
            id="res-chaos", area="Resistances", severity="warn" if chaos <= -30 else "info",
            title=f"Chaos resistance is negative ({chaos}%)",
            why="Negative resistance makes chaos damage hit harder than listed.",
            effect=f"Raising it to 0% means about {100 - 100 * 100 / (100 - chaos):.0f}% less chaos damage taken.",
            action=["Pick up Chaos Resistance on gear once elemental resistances are capped."],
            goals={"survive": 0.3}))

    # ---- weakest hit
    hits = {t: s.get(f"{t}MaximumHitTaken", 0) for t in ("Physical", "Fire", "Cold", "Lightning", "Chaos")}
    hits = {k: v for k, v in hits.items() if v > 0}
    if len(hits) >= 3:
        low = min(hits, key=hits.get)
        med = sorted(hits.values())[len(hits) // 2]
        if hits[low] < 0.6 * med:
            F.append(Finding(
                id=f"hit-{low.lower()}", area="Defence", severity="warn" if hits[low] < 0.4 * med else "info",
                certainty="likely",
                title=f"Weak against big {low.lower()} hits ({hits[low]:,.0f} vs {med:,.0f} for others)",
                why=f"The largest {low.lower()} hit you survive is far below the other damage types; bosses that "
                    f"deal {low.lower()} damage are the main one-shot risk.",
                effect="Raising it closes the gap that kills you first.",
                action=[{"Physical": "More armour, life/ES, or physical damage taken as elemental.",
                         "Chaos": "Chaos resistance, more life, or energy shield that chaos cannot bypass."}
                        .get(low, f"{low} resistance above cap, max {low.lower()} resistance, or more life/ES.")],
                goals={"survive": 0.6}, data=hits))

    # ---- attributes
    for k, name in (("Str", "Strength"), ("Dex", "Dexterity"), ("Int", "Intelligence")):
        need, have = s.get(f"Req{k}", 0), s.get(k, 0)
        if need > have:
            F.append(Finding(
                id=f"attr-{k.lower()}", area="Attributes", severity="bad",
                title=f"Not enough {name}: {have} of {need} needed",
                why="Items or gems with unmet requirements do not work.",
                effect="Meeting it turns those items and gems back on.",
                action=[f"Find +{need - have} {name} (gear, passives, or a different base)."],
                goals={"damage": 0.5, "survive": 0.5}))

    # ---- spirit
    free = s.get("SpiritUnreserved", 0)
    if free < 0:
        F.append(Finding(id="spirit-over", area="Spirit", severity="bad",
                         title=f"Spirit over-reserved by {-free}",
                         why="Some persistent skills cannot be active together.",
                         effect="Fixing it makes every buff you count on actually run.",
                         action=["Drop or lower a reservation, or get more Spirit (body armour, sceptre, amulet)."],
                         goals={"damage": 0.5, "survive": 0.5}))
    elif free >= 30:
        F.append(Finding(id="spirit-free", area="Spirit", severity="info",
                         title=f"{free} Spirit unused",
                         why="Unreserved Spirit is wasted power.",
                         effect="Another persistent buff, herald or minion fits.",
                         action=["Add a persistent skill that fits the free Spirit."],
                         goals={"damage": 0.4, "survive": 0.4}))

    # ---- mana
    cost, regen, pool = s.get("ManaPerSecondCost", 0), s.get("ManaRegenRecovery", 0), s.get("Mana", 0)
    if cost > regen > -1 and cost > 0:
        secs = pool / (cost - regen) if cost > regen else 0
        F.append(Finding(
            id="mana-main", area="Mana", severity="warn" if secs < 10 else "info", certainty="likely",
            title=f"Main skill costs {cost:.0f} mana/s, you regenerate {regen:.0f}/s",
            why=f"Using the main skill without pause empties {pool:,.0f} mana in about {secs:.0f} s "
                f"(leech and flasks not counted).",
            effect="Sustaining it means no pauses in damage.",
            action=["More mana regeneration or leech, a mana flask, or a cheaper support setup."],
            goals={"mana": 1.0, "ease": 0.5}, data={"seconds": round(secs, 1)}))

    # ---- skill groups
    low_gems = []
    for g in pob.groups():
        if not g["enabled"]:
            continue
        own_gem = not g.get("slot") and not g.get("source")  # not granted by an item, the tree or ascendancy
        for gem in g["gems"]:
            if gem["support"] and gem["enabled"] and not gem.get("applies", True):
                F.append(Finding(
                    id=f"support-dead-{g['index']}-{gem['name']}", area="Skills", severity="warn",
                    title=f"{gem['name']} cannot support {', '.join(g['skills']) or 'that group'}",
                    why="The support's required skill types do not match, so it does nothing.",
                    effect="Replacing it with a working support is free damage or utility.",
                    action=["Swap it: kb_supports_for lists supports that work with that skill."],
                    goals={"damage": 0.7}))
            if own_gem and not gem["support"] and gem["valid"] and gem["enabled"] and gem["level"] < 20:
                low_gems.append({"group": g["index"], "gem": gem["name"], "level": gem["level"]})
    if low_gems:
        F.append(Finding(
            id="gem-levels", area="Skills", severity="info", certainty="likely",
            title=f"{len(low_gems)} skill gems below level 20",
            why="Higher gem levels scale damage, buffs and reservations. Some low levels are on purpose "
                "(cheap reservation, utility skills, weapon-swap tricks).",
            effect="Measure each with try_changes set_gem level=20 before buying.",
            action=["Level or buy higher level gems for the skills that matter (main skill, auras, minions)."],
            goals={"damage": 0.4}, data={"gems": low_gems}))

    # ---- passive points
    pts = pob.points()
    if pts["unspent"] > 0:
        F.append(Finding(id="tree-unspent", area="Passives", severity="warn",
                         title=f"{pts['unspent']} passive points unspent",
                         why="Free points are free power.", effect="Spend them: see rank_passives.",
                         action=["rank_passives shows the best value per point."],
                         goals={"damage": 0.5, "survive": 0.5}))
    inactive = [n for n in pob.allocated_nodes() if not n["active"]]
    if inactive:
        F.append(Finding(
            id="tree-inactive-set", area="Passives", severity="info", certainty="check",
            title=f"{len(inactive)} passives belong to the other weapon set",
            why=f"They only apply while weapon set {inactive[0]['weapon_set']} is out; the calculation uses "
                f"set {pts['active_weapon_set']}.",
            effect="If you never swap, those points could move to the set you use.",
            action=["Check whether you actually use the other weapon set before moving them."],
            goals={"damage": 0.2}, data={"nodes": [n["name"] for n in inactive]}))

    if deep:
        # passives that change nothing PoB can measure
        dead, unmodelled = [], []
        for n in pob.allocated_nodes():
            if n.get("ascendancy") or not n["active"] or n["type"] in ("Socket", "Mastery"):
                continue
            w = pob.whatif(remove_nodes=[n["id"]])
            if -w["points"] != 1 or not _no_effect(s, w):
                continue  # only leaf nodes, so refunding it frees exactly this one point
            (unmodelled if n["unsupported"] else dead).append(n)
        if dead:
            F.append(Finding(
                id="tree-dead", area="Passives", severity="warn", certainty="likely",
                title=f"{len(dead)} passives change nothing measurable",
                why="Removing each of them changes no damage, defence, resource or attribute number in PoB with the "
                    "current config. Some may matter for conditions that are switched off.",
                effect=f"Up to {len(dead)} points to move to something that counts.",
                action=["Refund them and spend the points from rank_passives.",
                        "Before that, check build_config for conditions these nodes need."],
                goals={"damage": 0.6, "survive": 0.6}, data={"nodes": [n["name"] for n in dead]}))
        if unmodelled:
            F.append(Finding(
                id="tree-unmodelled", area="Passives", severity="info", certainty="check",
                title=f"{len(unmodelled)} passives have effects PoB does not calculate",
                why="Their value cannot be measured here (slows, maim, triggers, movement tricks...).",
                effect="Judge them by how you play.",
                action=["Keep them only if you feel the effect in game."],
                data={"nodes": {n["name"]: n["unsupported"] for n in unmodelled}}))

        # gear mods that change nothing
        dead_mods = []
        for it in pob.items(active_only=True):
            if it["slot"].startswith(("Flask", "Charm")):
                continue
            head, imp, exp = split_item(it["raw"])
            for idx, line in enumerate(exp):
                if not line.strip() or _clean(line).strip() in ("Corrupted", "Mirrored", "Unidentified", "Sanctified"):
                    continue
                w = pob.whatif(slot=it["slot"], item_raw=join_item(head, imp, exp[:idx] + exp[idx + 1:]),
                               exact_slot=True)
                if _no_effect(s, w):
                    dead_mods.append({"slot": it["slot"], "item": it["name"], "mod": _clean(line)})
        if dead_mods:
            F.append(Finding(
                id="gear-dead", area="Gear", severity="info", certainty="likely",
                title=f"{len(dead_mods)} gear mods change nothing measurable",
                why="Removing each one changes no damage, defence, resource or attribute number in PoB. "
                    "Rarity, utility and conditional mods land here too.",
                effect="These are the slots to craft over or replace first.",
                action=["Upgrade the item with the most dead mods first; whatif_item measures the replacement."],
                goals={"damage": 0.5, "survive": 0.5}, data={"mods": dead_mods}))

    for f in F:
        f.score = score(f, goals)
    F.sort(key=lambda f: f.score, reverse=True)
    return {"goals": goals, "findings": [asdict(f) for f in F],
            "credit": "Check-up format inspired by Exile Build Advisor (reytla, MIT)."}
