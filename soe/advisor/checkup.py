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
RES_PL = {"Fire": "ogień", "Cold": "zimno", "Lightning": "błyskawice", "Chaos": "chaos"}
HIT_PL = {"Physical": "fizyczne", "Fire": "ogień", "Cold": "zimno", "Lightning": "błyskawice", "Chaos": "chaos"}
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


def _n(v: float) -> str:
    return f"{v:,.0f}".replace(",", " ")


def _why_not_applied(gem: dict) -> str:
    from soe.advisor.assistant import explain_not_applied

    na = gem.get("not_applied")
    return explain_not_applied(na) if na else "Path of Building nie stosuje tego supportu do tego skilla, więc daje 0."


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
# stat text that only applies under a condition (enemy state, buff, charge, recent event...)
_CONDITIONAL = re.compile(
    r"\b(against|while|if|when|whenever|during|recently|on (hit|kill|crit)|per (frenzy|power|endurance)|"
    r"frozen|freez|chill|shock|ignit|electrocut|bleed|poison|blind|maim|stun|daze|pin|exposure|"
    r"broken armour|full life|low life|consum|infusion|herald|charges?)", re.I)


def _clean(line: str) -> str:
    return _TAGS.sub("", line)


def _no_effect(base: dict, w: dict, tol: float = 1e-6) -> bool:
    """True only if NO number PoB calculates changes (damage, defence, ailments like freeze/shock buildup,
    chill/shock magnitude, durations, costs...). base and w are full what-if outputs."""
    keys = {k for k in set(base) | set(w) if "Rarity" not in k and "Quantity" not in k}  # loot is not build power
    for k in keys:
        a, b = base.get(k), w.get(k)
        if isinstance(a, bool) or isinstance(b, bool):
            if a != b:
                return False
            continue
        if isinstance(a, (int, float)) or isinstance(b, (int, float)):
            a, b = a or 0, b or 0
            if abs(a - b) > tol * max(1, abs(a)):
                return False
    return True


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
            title=f"Odporność: {RES_PL[e]} {v}% ({gap} poniżej capu)",
            why=f"Poniżej {RES_CAP}% dostajesz więcej obrażeń ({RES_PL[e]}) niż trzeba.",
            effect=f"Cap = ok. {less:.0f}% mniej obrażeń tego typu.",
            action=[f"Znajdź +{gap}% {e} Resistance na gearze (pierścienie, amulet, pas, buty, rękawice, hełm)."]
                   + ([f"Masz nadmiar ponad cap na: {', '.join(RES_PL[x] for x in over)}. Zamień część tego na {RES_PL[e]}."]
                      if over else []),
            goals={"survive": min(1.0, gap / 50)}, data={"stat": f"{e}Resist", "gap": gap}))
    chaos = s.get("ChaosResist", 0)
    if chaos < 0:
        F.append(Finding(
            id="res-chaos", area="Resistances", severity="warn" if chaos <= -30 else "info",
            title=f"Ujemna odporność na chaos ({chaos}%)",
            why="Ujemna odporność sprawia, że chaos bije mocniej, niż pokazuje.",
            effect=f"Podniesienie do 0% to ok. {100 - 100 * 100 / (100 - chaos):.0f}% mniej obrażeń od chaosu.",
            action=["Dobieraj Chaos Resistance na gearze, gdy żywioły są już na capie."],
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
                title=f"Słabo znosisz duże trafienia: {HIT_PL[low]} (max {_n(hits[low])}, przy innych ok. {_n(med)})",
                why=f"Największy hit typu {HIT_PL[low]}, który przeżyjesz, jest dużo niższy niż przy innych typach. "
                    "To od takich bossów najłatwiej dostać oneshota.",
                effect="Podniesienie go zamyka lukę, przez którą giniesz najszybciej.",
                action=[{"Physical": "Więcej armoura, życia/ES albo część fizycznych obrażeń przyjmowana jako żywioł.",
                         "Chaos": "Odporność na chaos, więcej życia albo ES, którego chaos nie omija."}
                        .get(low, f"Maksymalna odporność ({HIT_PL[low]}) powyżej 75% albo więcej życia/ES.")],
                goals={"survive": 0.6}, data=hits))

    # ---- attributes
    for k, name in (("Str", "Strength"), ("Dex", "Dexterity"), ("Int", "Intelligence")):
        need, have = s.get(f"Req{k}", 0), s.get(k, 0)
        if need > have:
            F.append(Finding(
                id=f"attr-{k.lower()}", area="Attributes", severity="bad",
                title=f"Za mało atrybutu {name}: masz {have}, potrzeba {need}",
                why="Itemy lub gemy z niespełnionymi wymaganiami nie działają.",
                effect="Spełnienie wymagań włączy je z powrotem.",
                action=[f"Znajdź +{need - have} {name} (gear, pasywki albo inna baza itemu)."],
                goals={"damage": 0.5, "survive": 0.5}))

    # ---- spirit
    free = s.get("SpiritUnreserved", 0)
    if free < 0:
        F.append(Finding(id="spirit-over", area="Spirit", severity="bad",
                         title=f"Brakuje {-free} Spirit na wszystkie aury/buffy",
                         why="Część trwałych skilli nie może działać naraz.",
                         effect="Po naprawie wszystkie buffy, na które liczysz, naprawdę działają.",
                         action=["Usuń lub zmniejsz którąś rezerwację albo zdobądź więcej Spirit (zbroja, berło, amulet)."],
                         goals={"damage": 0.5, "survive": 0.5}))
    elif free >= 30:
        F.append(Finding(id="spirit-free", area="Spirit", severity="info",
                         title=f"{free} Spirit leży niewykorzystane",
                         why="Wolny Spirit to zmarnowana moc.",
                         effect="Zmieści się kolejny buff, herald albo minion.",
                         action=["Dodaj trwały skill, który zmieści się w wolnym Spirit."],
                         goals={"damage": 0.4, "survive": 0.4}))

    # ---- mana
    cost, regen, pool = s.get("ManaPerSecondCost", 0), s.get("ManaRegenRecovery", 0), s.get("Mana", 0)
    if cost > regen > -1 and cost > 0:
        secs = pool / (cost - regen) if cost > regen else 0
        F.append(Finding(
            id="mana-main", area="Mana", severity="warn" if secs < 10 else "info", certainty="likely",
            title=f"Główny skill zużywa {cost:.0f} many/s, a regenerujesz {regen:.0f}/s",
            why=f"Ciągłe używanie skilla opróżnia {_n(pool)} many w ok. {secs:.0f} s (bez leecha i flasek).",
            effect="Bez braków many nie ma przerw w zadawaniu obrażeń.",
            action=["Więcej regeneracji many lub leecha, flaska many albo tańszy zestaw supportów."],
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
                    title=f"{gem['name']} nie działa na {', '.join(g['skills']) or 'tę grupę'}",
                    why=_why_not_applied(gem),
                    effect="Ten slot daje teraz 0. Działający support w jego miejscu to darmowy zysk.",
                    action=["Wymień go na support pasujący do tego skilla (zakładka Skille → optymalizator supportów)."],
                    goals={"damage": 0.7}))
            if own_gem and not gem["support"] and gem["valid"] and gem["enabled"] and gem["level"] < 20:
                low_gems.append({"group": g["index"], "gem": gem["name"], "level": gem["level"]})
    if low_gems:
        F.append(Finding(
            id="gem-levels", area="Skills", severity="info", certainty="likely",
            title=f"{len(low_gems)} gemów skilli poniżej poziomu 20",
            why="Wyższy poziom gema to więcej obrażeń i mocniejsze buffy. Część niskich poziomów bywa celowa "
                "(tańsza rezerwacja, skille pomocnicze).",
            effect="Asystent policzy, ile da podniesienie konkretnego skilla.",
            action=["Podnieś poziom gemów, które się liczą (główny skill, aury, miniony)."],
            goals={"damage": 0.4}, data={"gems": low_gems}))

    # ---- passive points
    pts = pob.points()
    if pts["unspent"] > 0:
        F.append(Finding(id="tree-unspent", area="Passives", severity="warn",
                         title=f"{pts['unspent']} niewydanych punktów pasywnych",
                         why="Wolne punkty to darmowa moc.", effect="Wydaj je: zakładka Drzewko → Co warto wziąć.",
                         action=["Ranking pokazuje najlepszy zysk na punkt."],
                         goals={"damage": 0.5, "survive": 0.5}))
    inactive = [n for n in pob.allocated_nodes() if not n["active"]]
    if inactive:
        F.append(Finding(
            id="tree-inactive-set", area="Passives", severity="info", certainty="check",
            title=f"{len(inactive)} pasywek jest na drugim zestawie broni",
            why=f"Działają tylko przy zestawie broni {inactive[0]['weapon_set']}, a liczymy "
                f"zestaw {pts['active_weapon_set']}.",
            effect="Jeśli nigdy nie przełączasz broni, te punkty można przenieść.",
            action=["Sprawdź, czy naprawdę używasz drugiego zestawu, zanim je przeniesiesz."],
            goals={"damage": 0.2}, data={"nodes": [n["name"] for n in inactive]}))

    if deep:
        # passives that change nothing PoB can measure
        base_full = pob.whatif(full=True)
        base_full.pop("points", None)
        dead, unmodelled, conditional = [], [], []
        for n in pob.allocated_nodes():
            if n.get("ascendancy") or not n["active"] or n["type"] in ("Socket", "Mastery"):
                continue
            w = pob.whatif(remove_nodes=[n["id"]], full=True)
            freed = -w.pop("points", 0)
            if freed != 1 or not _no_effect(base_full, w):
                continue  # only leaf nodes, so refunding it frees exactly this one point
            text = " ".join(n["stats"])
            if n["unsupported"]:
                unmodelled.append(n)
            elif _CONDITIONAL.search(text):
                conditional.append(n)
            else:
                dead.append(n)
        if conditional:
            F.append(Finding(
                id="tree-conditional", area="Passives", severity="info", certainty="check",
                title=f"{len(conditional)} pasywek działa tylko pod warunkiem wyłączonym w configu PoB",
                why="Ich bonus wymaga np. zamrożonego/porażonego wroga, buffa albo charge'a. "
                    "W configu PoB ten warunek jest wyłączony, więc liczy je jako 0.",
                effect="Jeśli w grze build naprawdę spełnia ten warunek, są warte pełną wartość.",
                action=["Włącz ten warunek w configu PoB, żeby zobaczyć ich wartość.",
                        "Jeśli build nigdy go nie spełnia, punkty można przenieść."],
                goals={"damage": 0.4}, data={"nodes": {n["name"]: n["stats"] for n in conditional}}))
        if dead:
            F.append(Finding(
                id="tree-dead", area="Passives", severity="warn", certainty="likely",
                title=f"{len(dead)} pasywek nie zmienia żadnej liczby w PoB",
                why="Zdjęcie każdej z nich nie zmienia ani jednej liczby, którą liczy PoB (obrażenia, obrona, ailmenty, "
                    "zasoby, atrybuty), a nie mają żadnego warunku.",
                effect=f"Do {len(dead)} punktów do przeniesienia na coś, co działa.",
                action=["Zwolnij je i wydaj punkty według zakładki Drzewko → Co warto wziąć."],
                goals={"damage": 0.6, "survive": 0.6}, data={"nodes": [n["name"] for n in dead]}))
        if unmodelled:
            F.append(Finding(
                id="tree-unmodelled", area="Passives", severity="info", certainty="check",
                title=f"{len(unmodelled)} pasywek ma efekty, których kalkulator nie liczy",
                why="Ich wartości nie da się tu zmierzyć (spowolnienia, maim, triggery, efekty ruchu...).",
                effect="Oceń je po tym, jak grasz. Opis efektu jest w szczegółach, więcej na poe2wiki.net.",
                action=["Zostaw je, jeśli czujesz ten efekt w grze."],
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
                               exact_slot=True, full=True)
                w.pop("points", None)
                if _no_effect(base_full, w):
                    dead_mods.append({"slot": it["slot"], "item": it["name"], "mod": _clean(line)})
        if dead_mods:
            F.append(Finding(
                id="gear-dead", area="Gear", severity="info", certainty="likely",
                title=f"{len(dead_mods)} modów na gearze nie zmienia żadnej liczby w PoB",
                why="Zdjęcie każdego z nich nie zmienia żadnej liczby, którą liczy PoB. Lądują tu też rarity, "
                    "mody użytkowe i odporności ponad cap.",
                effect="Te sloty najlepiej przecraftować albo wymienić jako pierwsze.",
                action=["Zacznij od itemu z największą liczbą takich modów (zakładka Gear pokaże lepsze mody)."],
                goals={"damage": 0.5, "survive": 0.5}, data={"mods": dead_mods}))

    for f in F:
        f.score = score(f, goals)
    F.sort(key=lambda f: f.score, reverse=True)
    return {"goals": goals, "findings": [asdict(f) for f in F],
            "credit": "Check-up format inspired by Exile Build Advisor (reytla, MIT)."}
