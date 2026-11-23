"""Build check-up: ranked findings about what holds a build back.

Idea and finding format adapted from Exile Build Advisor by reytla (MIT,
https://github.com/reytla/exile-build-adviser): every finding has a severity, a certainty, why it
matters, what fixing it gains, what to do, and weights for the player's goals. Unlike the original,
"does nothing" checks are measured with the Path of Building engine, not guessed from text.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from soe.i18n import t

RES_CAP = 75
_NAMES = {"Physical": ("physical", "fizyczne"), "Fire": ("fire", "ogień"), "Cold": ("cold", "zimno"),
          "Lightning": ("lightning", "błyskawice"), "Chaos": ("chaos", "chaos")}


def res_name(k: str) -> str:
    return t(*_NAMES[k])


hit_name = res_name
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
    return explain_not_applied(na) if na else t("Path of Building does not apply this support to this skill, so it gives 0.",
                                                 "Path of Building nie stosuje tego supportu do tego skilla, więc daje 0.")


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
        overs = ", ".join(res_name(x) for x in over)
        F.append(Finding(
            id=f"res-{e.lower()}", area="Resistances",
            severity="bad" if gap >= 30 else "warn" if gap >= 10 else "info",
            title=t(f"{e} resistance {v}% ({gap} below cap)", f"Odporność: {res_name(e)} {v}% ({gap} poniżej capu)"),
            why=t(f"Below {RES_CAP}% you take more {e.lower()} damage than you need to.",
                  f"Poniżej {RES_CAP}% dostajesz więcej obrażeń ({res_name(e)}) niż trzeba."),
            effect=t(f"Capped = about {less:.0f}% less damage of this type.", f"Cap = ok. {less:.0f}% mniej obrażeń tego typu."),
            action=[t(f"Find +{gap}% {e} Resistance on gear (rings, amulet, belt, boots, gloves, helmet).",
                      f"Znajdź +{gap}% {e} Resistance na gearze (pierścienie, amulet, pas, buty, rękawice, hełm).")]
                   + ([t(f"You are over the cap on: {overs}. Swap some of it for {e.lower()}.",
                         f"Masz nadmiar ponad cap na: {overs}. Zamień część tego na {res_name(e)}.")] if over else []),
            goals={"survive": min(1.0, gap / 50)}, data={"stat": f"{e}Resist", "gap": gap}))
    chaos = s.get("ChaosResist", 0)
    if chaos < 0:
        less = 100 - 100 * 100 / (100 - chaos)
        F.append(Finding(
            id="res-chaos", area="Resistances", severity="warn" if chaos <= -30 else "info",
            title=t(f"Negative chaos resistance ({chaos}%)", f"Ujemna odporność na chaos ({chaos}%)"),
            why=t("Negative resistance makes chaos hit harder than it shows.",
                  "Ujemna odporność sprawia, że chaos bije mocniej, niż pokazuje."),
            effect=t(f"Raising it to 0% is about {less:.0f}% less chaos damage.",
                     f"Podniesienie do 0% to ok. {less:.0f}% mniej obrażeń od chaosu."),
            action=[t("Pick up Chaos Resistance on gear once the elements are capped.",
                      "Dobieraj Chaos Resistance na gearze, gdy żywioły są już na capie.")],
            goals={"survive": 0.3}))

    # ---- weakest hit
    hits = {k: s.get(f"{k}MaximumHitTaken", 0) for k in ("Physical", "Fire", "Cold", "Lightning", "Chaos")}
    hits = {k: v for k, v in hits.items() if v > 0}
    if len(hits) >= 3:
        low = min(hits, key=hits.get)
        med = sorted(hits.values())[len(hits) // 2]
        if hits[low] < 0.6 * med:
            name = hit_name(low)
            F.append(Finding(
                id=f"hit-{low.lower()}", area="Defence", severity="warn" if hits[low] < 0.4 * med else "info",
                certainty="likely",
                title=t(f"You take big hits badly: {name} (max {_n(hits[low])}, others about {_n(med)})",
                        f"Słabo znosisz duże trafienia: {name} (max {_n(hits[low])}, przy innych ok. {_n(med)})"),
                why=t(f"The biggest {name} hit you survive is far lower than for other types. "
                      "Bosses that deal it are the easiest way to get one-shot.",
                      f"Największy hit typu {name}, który przeżyjesz, jest dużo niższy niż przy innych typach. "
                      "To od takich bossów najłatwiej dostać oneshota."),
                effect=t("Raising it closes the gap that kills you fastest.",
                         "Podniesienie go zamyka lukę, przez którą giniesz najszybciej."),
                action=[{"Physical": t("More armour, life/ES, or part of physical damage taken as elemental.",
                                       "Więcej armoura, życia/ES albo część fizycznych obrażeń przyjmowana jako żywioł."),
                         "Chaos": t("Chaos resistance, more life, or ES that chaos does not bypass.",
                                    "Odporność na chaos, więcej życia albo ES, którego chaos nie omija.")}
                        .get(low, t(f"Maximum {name} resistance above 75% or more life/ES.",
                                    f"Maksymalna odporność ({name}) powyżej 75% albo więcej życia/ES."))],
                goals={"survive": 0.6}, data=hits))

    # ---- attributes
    for k, name in (("Str", "Strength"), ("Dex", "Dexterity"), ("Int", "Intelligence")):
        need, have = s.get(f"Req{k}", 0), s.get(k, 0)
        if need > have:
            F.append(Finding(
                id=f"attr-{k.lower()}", area="Attributes", severity="bad",
                title=t(f"Not enough {name}: you have {have}, you need {need}",
                        f"Za mało atrybutu {name}: masz {have}, potrzeba {need}"),
                why=t("Items or gems with unmet requirements do not work.",
                      "Itemy lub gemy z niespełnionymi wymaganiami nie działają."),
                effect=t("Meeting the requirements turns them back on.", "Spełnienie wymagań włączy je z powrotem."),
                action=[t(f"Find +{need - have} {name} (gear, passives or another item base).",
                          f"Znajdź +{need - have} {name} (gear, pasywki albo inna baza itemu).")],
                goals={"damage": 0.5, "survive": 0.5}))

    # ---- spirit
    free = s.get("SpiritUnreserved", 0)
    if free < 0:
        F.append(Finding(id="spirit-over", area="Spirit", severity="bad",
                         title=t(f"{-free} Spirit short for all auras/buffs", f"Brakuje {-free} Spirit na wszystkie aury/buffy"),
                         why=t("Some persistent skills cannot run at the same time.",
                               "Część trwałych skilli nie może działać naraz."),
                         effect=t("Once fixed, every buff you count on really runs.",
                                  "Po naprawie wszystkie buffy, na które liczysz, naprawdę działają."),
                         action=[t("Remove or shrink a reservation, or get more Spirit (body armour, sceptre, amulet).",
                                   "Usuń lub zmniejsz którąś rezerwację albo zdobądź więcej Spirit (zbroja, berło, amulet).")],
                         goals={"damage": 0.5, "survive": 0.5}))
    elif free >= 30:
        F.append(Finding(id="spirit-free", area="Spirit", severity="info",
                         title=t(f"{free} Spirit unused", f"{free} Spirit leży niewykorzystane"),
                         why=t("Free Spirit is wasted power.", "Wolny Spirit to zmarnowana moc."),
                         effect=t("Another buff, herald or minion fits.", "Zmieści się kolejny buff, herald albo minion."),
                         action=[t("Add a persistent skill that fits in the free Spirit.",
                                   "Dodaj trwały skill, który zmieści się w wolnym Spirit.")],
                         goals={"damage": 0.4, "survive": 0.4}))

    # ---- mana
    cost, regen, pool = s.get("ManaPerSecondCost", 0), s.get("ManaRegenRecovery", 0), s.get("Mana", 0)
    if cost > regen > -1 and cost > 0:
        secs = pool / (cost - regen) if cost > regen else 0
        F.append(Finding(
            id="mana-main", area="Mana", severity="warn" if secs < 10 else "info", certainty="likely",
            title=t(f"The main skill uses {cost:.0f} mana/s, you regenerate {regen:.0f}/s",
                    f"Główny skill zużywa {cost:.0f} many/s, a regenerujesz {regen:.0f}/s"),
            why=t(f"Using the skill non-stop drains {_n(pool)} mana in about {secs:.0f} s (without leech or flasks).",
                  f"Ciągłe używanie skilla opróżnia {_n(pool)} many w ok. {secs:.0f} s (bez leecha i flasek)."),
            effect=t("No mana gaps means no breaks in your damage.", "Bez braków many nie ma przerw w zadawaniu obrażeń."),
            action=[t("More mana regeneration or leech, a mana flask, or a cheaper set of supports.",
                      "Więcej regeneracji many lub leecha, flaska many albo tańszy zestaw supportów.")],
            goals={"mana": 1.0, "ease": 0.5}, data={"seconds": round(secs, 1)}))

    # ---- skill groups
    low_gems = []
    for g in pob.groups():
        if not g["enabled"]:
            continue
        own_gem = not g.get("slot") and not g.get("source")  # not granted by an item, the tree or ascendancy
        for gem in g["gems"]:
            if gem["support"] and gem["enabled"] and not gem.get("applies", True):
                target = ", ".join(g["skills"]) or t("this group", "tę grupę")
                F.append(Finding(
                    id=f"support-dead-{g['index']}-{gem['name']}", area="Skills", severity="warn",
                    title=t(f"{gem['name']} does not apply to {target}", f"{gem['name']} nie działa na {target}"),
                    why=_why_not_applied(gem),
                    effect=t("This socket gives 0 now. A working support in its place is a free gain.",
                             "Ten slot daje teraz 0. Działający support w jego miejscu to darmowy zysk."),
                    action=[t("Swap it for a support that fits this skill (Skills tab -> support optimizer).",
                              "Wymień go na support pasujący do tego skilla (zakładka Skille → optymalizator supportów).")],
                    goals={"damage": 0.7}))
            if own_gem and not gem["support"] and gem["valid"] and gem["enabled"] and gem["level"] < 20:
                low_gems.append({"group": g["index"], "gem": gem["name"], "level": gem["level"]})
    if low_gems:
        F.append(Finding(
            id="gem-levels", area="Skills", severity="info", certainty="likely",
            title=t(f"{len(low_gems)} skill gems below level 20", f"{len(low_gems)} gemów skilli poniżej poziomu 20"),
            why=t("A higher gem level means more damage and stronger buffs. Some low levels are on purpose "
                  "(cheaper reservation, helper skills).",
                  "Wyższy poziom gema to więcej obrażeń i mocniejsze buffy. Część niskich poziomów bywa celowa "
                  "(tańsza rezerwacja, skille pomocnicze)."),
            effect=t("The assistant calculates what raising a given skill gains.",
                     "Asystent policzy, ile da podniesienie konkretnego skilla."),
            action=[t("Level up the gems that matter (main skill, auras, minions).",
                      "Podnieś poziom gemów, które się liczą (główny skill, aury, miniony).")],
            goals={"damage": 0.4}, data={"gems": low_gems}))

    # ---- passive points
    pts = pob.points()
    if pts["unspent"] > 0:
        F.append(Finding(id="tree-unspent", area="Passives", severity="warn",
                         title=t(f"{pts['unspent']} unspent passive points", f"{pts['unspent']} niewydanych punktów pasywnych"),
                         why=t("Free points are free power.", "Wolne punkty to darmowa moc."),
                         effect=t("Spend them: Tree tab -> Worth taking.", "Wydaj je: zakładka Drzewko → Co warto wziąć."),
                         action=[t("The ranking shows the best gain per point.", "Ranking pokazuje najlepszy zysk na punkt.")],
                         goals={"damage": 0.5, "survive": 0.5}))
    inactive = [n for n in pob.allocated_nodes() if not n["active"]]
    if inactive:
        F.append(Finding(
            id="tree-inactive-set", area="Passives", severity="info", certainty="check",
            title=t(f"{len(inactive)} passives are on the other weapon set", f"{len(inactive)} pasywek jest na drugim zestawie broni"),
            why=t(f"They work only with weapon set {inactive[0]['weapon_set']}, and we calculate set {pts['active_weapon_set']}.",
                  f"Działają tylko przy zestawie broni {inactive[0]['weapon_set']}, a liczymy zestaw {pts['active_weapon_set']}."),
            effect=t("If you never swap weapons, these points can be moved.",
                     "Jeśli nigdy nie przełączasz broni, te punkty można przenieść."),
            action=[t("Check that you really use the other set before moving them.",
                      "Sprawdź, czy naprawdę używasz drugiego zestawu, zanim je przeniesiesz.")],
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
                title=t(f"{len(conditional)} passives work only under a condition switched off in PoB's config",
                        f"{len(conditional)} pasywek działa tylko pod warunkiem wyłączonym w configu PoB"),
                why=t("Their bonus needs e.g. a frozen/shocked enemy, a buff or a charge. That condition is off in "
                      "PoB's config, so it counts them as 0.",
                      "Ich bonus wymaga np. zamrożonego/porażonego wroga, buffa albo charge'a. "
                      "W configu PoB ten warunek jest wyłączony, więc liczy je jako 0."),
                effect=t("If the build really meets the condition in game, they are worth their full value.",
                         "Jeśli w grze build naprawdę spełnia ten warunek, są warte pełną wartość."),
                action=[t("Turn the condition on in PoB's config to see their value.",
                          "Włącz ten warunek w configu PoB, żeby zobaczyć ich wartość."),
                        t("If the build never meets it, the points can be moved.",
                          "Jeśli build nigdy go nie spełnia, punkty można przenieść.")],
                goals={"damage": 0.4}, data={"nodes": {n["name"]: n["stats"] for n in conditional}}))
        if dead:
            F.append(Finding(
                id="tree-dead", area="Passives", severity="warn", certainty="likely",
                title=t(f"{len(dead)} passives change no number in PoB", f"{len(dead)} pasywek nie zmienia żadnej liczby w PoB"),
                why=t("Removing any of them changes no number PoB calculates (damage, defence, ailments, resources, "
                      "attributes), and they have no condition.",
                      "Zdjęcie każdej z nich nie zmienia ani jednej liczby, którą liczy PoB (obrażenia, obrona, ailmenty, "
                      "zasoby, atrybuty), a nie mają żadnego warunku."),
                effect=t(f"Up to {len(dead)} points to move to something that works.",
                         f"Do {len(dead)} punktów do przeniesienia na coś, co działa."),
                action=[t("Refund them and spend the points as the Tree tab -> Worth taking suggests.",
                          "Zwolnij je i wydaj punkty według zakładki Drzewko → Co warto wziąć.")],
                goals={"damage": 0.6, "survive": 0.6}, data={"nodes": [n["name"] for n in dead]}))
        if unmodelled:
            F.append(Finding(
                id="tree-unmodelled", area="Passives", severity="info", certainty="check",
                title=t(f"{len(unmodelled)} passives have effects the calculator does not count",
                        f"{len(unmodelled)} pasywek ma efekty, których kalkulator nie liczy"),
                why=t("Their value cannot be measured here (slows, maim, triggers, movement effects...).",
                      "Ich wartości nie da się tu zmierzyć (spowolnienia, maim, triggery, efekty ruchu...)."),
                effect=t("Judge them by how you play. The effect is in the details, more on poe2wiki.net.",
                         "Oceń je po tym, jak grasz. Opis efektu jest w szczegółach, więcej na poe2wiki.net."),
                action=[t("Keep them if you feel the effect in game.", "Zostaw je, jeśli czujesz ten efekt w grze.")],
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
                title=t(f"{len(dead_mods)} gear mods change no number in PoB",
                        f"{len(dead_mods)} modów na gearze nie zmienia żadnej liczby w PoB"),
                why=t("Removing any of them changes no number PoB calculates. Rarity, utility mods and resistances "
                      "over the cap land here too.",
                      "Zdjęcie każdego z nich nie zmienia żadnej liczby, którą liczy PoB. Lądują tu też rarity, "
                      "mody użytkowe i odporności ponad cap."),
                effect=t("These slots are the first to recraft or replace.",
                         "Te sloty najlepiej przecraftować albo wymienić jako pierwsze."),
                action=[t("Start with the item that has the most of them (the Gear tab shows better mods).",
                          "Zacznij od itemu z największą liczbą takich modów (zakładka Gear pokaże lepsze mody).")],
                goals={"damage": 0.5, "survive": 0.5}, data={"mods": dead_mods}))

    for f in F:
        f.score = score(f, goals)
    F.sort(key=lambda f: f.score, reverse=True)
    return {"goals": goals, "findings": [asdict(f) for f in F],
            "credit": "Check-up format inspired by Exile Build Advisor (reytla, MIT)."}
