"""Quick check-up for the web assistant: plain answers to the questions players ask most, computed in a few
seconds with PoB (no AI). Each card: level (ok / warn / bad / info), title, text, optional lines and the tab
where the player can act on it.
"""
from __future__ import annotations

from soe.i18n import t
from soe.optimize.objective import Objective

RES_CAP = 75
ELEMENTS = ("Fire", "Cold", "Lightning", "Chaos")


def _card(cid, level, title, text, lines=None, tab=None, action=None):
    return {"id": cid, "level": level, "title": title, "text": text, "lines": lines or [], "tab": tab,
            "action": action}


def _num(v) -> str:
    return f"{v:,.0f}".replace(",", " ")


def resist_card(b: dict) -> dict:
    short = [(k, RES_CAP - (b.get(f"{k}Resist") or 0)) for k in ELEMENTS[:3] if (b.get(f"{k}Resist") or 0) < RES_CAP]
    chaos = b.get("ChaosResist") or 0
    lines = [f"{k}: {b.get(f'{k}Resist')}%" for k in ELEMENTS]
    if short:
        miss = ", ".join(f"{n} -{v}%" for n, v in short)
        return _card("res", "bad", t("Resistances below cap", "Resy poniżej capu"),
                     t(f"Missing: {miss}. Every missing percent is more elemental damage taken; it is the cheapest EHP in the game.",
                       f"Brakuje: {miss}. Każdy brakujący procent to więcej obrażeń od żywiołów; to najtańszy EHP w grze."),
                     lines, "gear", t("Gear: find resistances", "Gear: szukaj resów"))
    if chaos < 0:
        return _card("res", "warn", t("Elements capped, chaos negative", "Żywioły na capie, chaos na minusie"),
                     t(f"Chaos res {chaos}%: chaos hits you harder than with no resistance at all.",
                       f"Chaos res {chaos}%: chaos bije Cię mocniej niż bez żadnej odporności."), lines, "gear")
    return _card("res", "ok", t("Resistances capped", "Resy na capie"),
                 t("Fire, cold and lightning are at 75%.", "Ogień, zimno i błyskawice mają 75%."), lines)


def attribute_card(b: dict) -> dict:
    attrs = ("Str", "Dex", "Int")
    miss = [(a, (b.get(f"Req{a}") or 0) - (b.get(a) or 0)) for a in attrs if (b.get(f"Req{a}") or 0) > (b.get(a) or 0)]
    lines = [t(f"{a}: {b.get(a)} / required {b.get(f'Req{a}')}", f"{a}: {b.get(a)} / wymagane {b.get(f'Req{a}')}")
             for a in attrs]
    if miss:
        m = ", ".join(f"{a} {v}" for a, v in miss)
        return _card("attr", "bad", t("Not enough attributes", "Za mało atrybutów"),
                     t(f"Missing: {m}. A gem or item that needs more than you have does not work.",
                       f"Brakuje: {m}. Gem albo item z wymaganiem ponad Twoje atrybuty nie działa."), lines, "gear")
    spare = min((b.get(a) or 0) - (b.get(f"Req{a}") or 0) for a in attrs)
    return _card("attr", "ok", t("Attributes are enough", "Atrybuty wystarczają"),
                 t(f"Smallest margin: {spare}. Careful when swapping gear with attributes.",
                   f"Najmniejszy zapas: {spare}. Uważaj przy zmianie gearu z atrybutami."), lines)


def spirit_card(b: dict) -> dict:
    free = b.get("SpiritUnreserved")
    if free is None:
        return _card("spirit", "info", "Spirit", t("PoB gave no spirit for this build.", "PoB nie podał spirit dla tego buildu."))
    if free < 0:
        return _card("spirit", "bad", t("Not enough spirit", "Za mało spirit"),
                     t(f"{-free} spirit short: an aura / herald / minion will not turn on.",
                       f"Brakuje {-free} spirit: któraś aura / herald / minion się nie włączy."), tab="skills")
    more = t(" Enough for another buff or minion.", " Wystarczy na kolejny buff albo minion.") if free >= 30 else ""
    return _card("spirit", "ok" if free < 30 else "info", "Spirit",
                 t(f"Free: {free} of {b.get('Spirit')}.", f"Wolne: {free} z {b.get('Spirit')}.") + more, tab="skills")


def mana_card(b: dict) -> dict:
    cost, regen = b.get("ManaPerSecondCost") or 0, b.get("ManaRegenRecovery") or 0
    if cost <= 0:
        return _card("mana", "info", "Mana", t("The main skill costs no mana per second (or PoB does not calculate it).",
                                               "Główny skill nie zużywa many na sekundę (albo PoB tego nie liczy)."))
    if cost > regen:
        return _card("mana", "warn", t("Mana runs out", "Mana się kończy"),
                     t(f"Using the main skill non-stop costs {cost:.0f} mana/s, regeneration gives {regen:.0f}/s. "
                       "Without leech, flasks or pauses you run dry.",
                       f"Ciągłe używanie głównego skilla kosztuje {cost:.0f} many/s, a regeneracja daje {regen:.0f}/s. "
                       "Bez leech, flaszek albo przerw zabraknie many."), tab="assistant")
    return _card("mana", "ok", t("Mana holds up", "Mana się trzyma"),
                 t(f"Cost {cost:.0f}/s, regeneration {regen:.0f}/s.", f"Koszt {cost:.0f}/s, regeneracja {regen:.0f}/s."))


def max_hit_card(b: dict) -> dict:
    names = {"Physical": t("Physical", "Fizyczne"), "Fire": t("Fire", "Ogień"), "Cold": t("Cold", "Zimno"),
             "Lightning": t("Lightning", "Błyskawice"), "Chaos": "Chaos"}
    hits = {names[k]: b.get(f"{k}MaximumHitTaken") for k in names if b.get(f"{k}MaximumHitTaken")}
    if not hits:
        return _card("maxhit", "info", t("Biggest hit", "Największy hit"), t("No data from PoB.", "Brak danych z PoB."))
    weak = min(hits, key=hits.get)
    strong = max(hits.values())
    lines = [f"{n}: {_num(v)}" for n, v in sorted(hits.items(), key=lambda x: x[1])]
    level = "warn" if hits[weak] < strong * 0.5 else "ok"
    tail = t(". Less than half of your best type: this is where bosses one-shot you.",
             ". To mniej niż połowa najlepszego typu: tu bossy Cię oneshotują.") if level == "warn" else "."
    return _card("maxhit", level, t(f"Weakest against: {weak}", f"Najsłabiej znosisz: {weak}"),
                 t(f"Biggest {weak.lower()} hit you survive: {_num(hits[weak])}",
                   f"Największy hit {weak.lower()}, który przeżyjesz: {_num(hits[weak])}") + tail, lines, "checkup")


def gear_card(session, obj) -> dict:
    from soe.items.gear import gear_audit

    g = gear_audit(session, obj)
    top = [x for x in g["slots"] if (x.get("realistic") or {}).get("score", 0) > 1][:3]
    if not top:
        return _card("gear", "ok", t("Gear keeps up", "Gear trzyma poziom"),
                     t(f"No slot clearly loses to a realistic rare for level {g['level']}.",
                       f"Żaden slot nie przegrywa wyraźnie z realnym rare na lvl {g['level']}."), tab="gear")
    lines = []
    for x in top:
        r = x["realistic"]
        lines.append(f"{x['slot']}: {x['item'].split(',')[0]} -> {r['base']} (DPS {r['dps_pct']:+.1f}%, EHP {r['ehp_pct']:+.1f}%)")
    return _card("gear", "warn", t("What to replace first", "Co wymienić najpierw"),
                 t(f"A realistic rare for level {g['level']} would gain the most in these slots:",
                   f"Realny rare na lvl {g['level']} dałby najwięcej w tych slotach:"),
                 lines, "gear", t("Gear: craft recipes", "Gear: przepisy na craft"))


def passives_card(session) -> dict:
    lines = []
    for metric, label in (("dps", "DPS"), ("ehp", "EHP")):
        try:
            for r in session.rank_passives(metric=metric, limit=2):
                lines.append(t(f"{label}: {r['node']} ({r['points']} pts) {r['gain_pct']:+.1f}%",
                               f"{label}: {r['node']} ({r['points']} pkt) {r['gain_pct']:+.1f}%"))
        except Exception:
            pass
    if not lines:
        return _card("tree", "info", t("Passives", "Pasywki"),
                     t("No good passives within a few points.", "Brak dobrych pasywek w zasięgu kilku punktów."), tab="tree")
    return _card("tree", "info", t("Best passives in reach", "Najlepsze pasywki w zasięgu"),
                 t("Counting the path from what you already have:", "Licząc ścieżkę od tego, co już masz:"),
                 lines, "tree", t("Tree", "Drzewko"))


def quick_check(session, objective: Objective | None = None) -> dict:
    session._need_build()
    b = session.base
    obj = objective or Objective()
    cards = [resist_card(b), attribute_card(b), spirit_card(b), mana_card(b), max_hit_card(b)]
    for fn in (lambda: gear_card(session, obj), lambda: passives_card(session)):
        try:
            cards.append(fn())
        except Exception as e:  # a slow or failing part must not hide the rest
            cards.append(_card("err", "info", t("Part not calculated", "Nie policzyłem części"), f"{type(e).__name__}: {e}"))
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    cards.sort(key=lambda c: order[c["level"]])
    return {"cards": cards, "summary": {k: b.get(k) for k in ("CombinedDPS", "TotalEHP", "Life", "EnergyShield")}}
