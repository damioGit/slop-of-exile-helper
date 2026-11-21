"""Quick check-up for the web assistant: plain answers to the questions players ask most, computed in a few
seconds with PoB (no AI). Each card: level (ok / warn / bad / info), title, text, optional lines and the tab
where the player can act on it.
"""
from __future__ import annotations

from soe.optimize.objective import Objective

RES_CAP = 75
ELEMENTS = (("Fire", "Fire"), ("Cold", "Cold"), ("Lightning", "Lightning"), ("Chaos", "Chaos"))


def _card(cid, level, title, text, lines=None, tab=None, action=None):
    return {"id": cid, "level": level, "title": title, "text": text, "lines": lines or [], "tab": tab,
            "action": action}


def resist_card(b: dict) -> dict:
    short = [(name, RES_CAP - (b.get(f"{key}Resist") or 0)) for key, name in ELEMENTS[:3]
             if (b.get(f"{key}Resist") or 0) < RES_CAP]
    chaos = b.get("ChaosResist") or 0
    lines = [f"{name}: {b.get(f'{key}Resist')}%" for key, name in ELEMENTS]
    if short:
        miss = ", ".join(f"{n} -{v}%" for n, v in short)
        return _card("res", "bad", "Resy poniżej capu",
                     f"Brakuje: {miss}. Każdy brakujący procent to więcej obrażeń od żywiołów; to najtańszy EHP w grze.",
                     lines, "gear", "Gear: szukaj resów")
    if chaos < 0:
        return _card("res", "warn", "Żywioły na capie, chaos na minusie",
                     f"Chaos res {chaos}%: chaos bije Cię mocniej niż bez żadnej odporności.", lines, "gear")
    return _card("res", "ok", "Resy na capie", "Ogień, zimno i błyskawice mają 75%.", lines)


def attribute_card(b: dict) -> dict:
    miss = [(a, (b.get(f"Req{a}") or 0) - (b.get(a) or 0)) for a in ("Str", "Dex", "Int")
            if (b.get(f"Req{a}") or 0) > (b.get(a) or 0)]
    lines = [f"{a}: {b.get(a)} / wymagane {b.get(f'Req{a}')}" for a in ("Str", "Dex", "Int")]
    if miss:
        return _card("attr", "bad", "Za mało atrybutów",
                     "Brakuje: " + ", ".join(f"{a} {v}" for a, v in miss) +
                     ". Gem albo item z wymaganiem ponad Twoje atrybuty nie działa.", lines, "gear")
    spare = min((b.get(a) or 0) - (b.get(f"Req{a}") or 0) for a in ("Str", "Dex", "Int"))
    return _card("attr", "ok", "Atrybuty wystarczają",
                 f"Najmniejszy zapas: {spare}. Uważaj przy zmianie gearu z atrybutami.", lines)


def spirit_card(b: dict) -> dict:
    free = b.get("SpiritUnreserved")
    if free is None:
        return _card("spirit", "info", "Spirit", "PoB nie podał spirit dla tego buildu.")
    if free < 0:
        return _card("spirit", "bad", "Za mało spirit",
                     f"Brakuje {-free} spirit: któraś aura / herald / minion się nie włączy.", tab="skills")
    return _card("spirit", "ok" if free < 30 else "info", "Spirit",
                 f"Wolne: {free} z {b.get('Spirit')}." + (" Wystarczy na kolejny buff albo minion." if free >= 30 else ""),
                 tab="skills")


def mana_card(b: dict) -> dict:
    cost, regen = b.get("ManaPerSecondCost") or 0, b.get("ManaRegenRecovery") or 0
    if cost <= 0:
        return _card("mana", "info", "Mana", "Główny skill nie zużywa many na sekundę (albo PoB tego nie liczy).")
    if cost > regen:
        return _card("mana", "warn", "Mana się kończy",
                     f"Ciągłe używanie głównego skilla kosztuje {cost:.0f} many/s, a regeneracja daje {regen:.0f}/s. "
                     "Bez leech, flaszek albo przerw zabraknie many.", tab="assistant")
    return _card("mana", "ok", "Mana się trzyma", f"Koszt {cost:.0f}/s, regeneracja {regen:.0f}/s.")


def max_hit_card(b: dict) -> dict:
    hits = {n: b.get(f"{k}MaximumHitTaken") for k, n in (("Physical", "Fizyczne"), ("Fire", "Ogień"),
                                                          ("Cold", "Zimno"), ("Lightning", "Błyskawice"),
                                                          ("Chaos", "Chaos")) if b.get(f"{k}MaximumHitTaken")}
    if not hits:
        return _card("maxhit", "info", "Największy hit", "Brak danych z PoB.")
    weak = min(hits, key=hits.get)
    strong = max(hits.values())
    lines = [f"{n}: {v:,.0f}".replace(",", " ") for n, v in sorted(hits.items(), key=lambda x: x[1])]
    level = "warn" if hits[weak] < strong * 0.5 else "ok"
    return _card("maxhit", level, f"Najsłabiej znosisz: {weak}",
                 f"Największy hit {weak.lower()}, który przeżyjesz: {hits[weak]:,.0f}".replace(",", " ") +
                 (". To mniej niż połowa najlepszego typu: tu bossy Cię oneshotują." if level == "warn" else "."),
                 lines, "checkup")


def gear_card(session, obj) -> dict:
    from soe.items.gear import gear_audit

    g = gear_audit(session, obj)
    top = [x for x in g["slots"] if (x.get("realistic") or {}).get("score", 0) > 1][:3]
    if not top:
        return _card("gear", "ok", "Gear trzyma poziom",
                     f"Żaden slot nie przegrywa wyraźnie z realnym rare na lvl {g['level']}.", tab="gear")
    lines = []
    for x in top:
        r = x["realistic"]
        lines.append(f"{x['slot']}: {x['item'].split(',')[0]} -> {r['base']} (DPS {r['dps_pct']:+.1f}%, EHP {r['ehp_pct']:+.1f}%)")
    return _card("gear", "warn", "Co wymienić najpierw",
                 f"Realny rare na lvl {g['level']} dałby najwięcej w tych slotach:", lines, "gear", "Gear: przepisy na craft")


def passives_card(session) -> dict:
    lines = []
    for metric, label in (("dps", "DPS"), ("ehp", "EHP")):
        try:
            for r in session.rank_passives(metric=metric, limit=2):
                lines.append(f"{label}: {r['node']} ({r['points']} pkt) {r['gain_pct']:+.1f}%")
        except Exception:
            pass
    if not lines:
        return _card("tree", "info", "Pasywki", "Brak dobrych pasywek w zasięgu kilku punktów.", tab="tree")
    return _card("tree", "info", "Najlepsze pasywki w zasięgu", "Licząc ścieżkę od tego, co już masz:", lines, "tree",
                 "Drzewko")


def quick_check(session, objective: Objective | None = None) -> dict:
    session._need_build()
    b = session.base
    obj = objective or Objective()
    cards = [resist_card(b), attribute_card(b), spirit_card(b), mana_card(b), max_hit_card(b)]
    for fn in (lambda: gear_card(session, obj), lambda: passives_card(session)):
        try:
            cards.append(fn())
        except Exception as e:  # a slow or failing part must not hide the rest
            cards.append(_card("err", "info", "Nie policzyłem części", f"{type(e).__name__}: {e}"))
    order = {"bad": 0, "warn": 1, "info": 2, "ok": 3}
    cards.sort(key=lambda c: order[c["level"]])
    return {"cards": cards, "summary": {k: b.get(k) for k in ("CombinedDPS", "TotalEHP", "Life", "EnergyShield")}}
