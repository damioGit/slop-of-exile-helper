"""Assistant: a player's question in plain words -> a concrete, ordered to-do list measured in PoB.

Examples it understands (Polish or English):
  "nie jestem w stanie oneshotować moba, co zrobić żeby bić mocniej Comet"   -> bigger single hits of Comet
  "jak zwiększyć dps lightning bolt za 5 div"                             -> damage of Lightning Bolt, 5 div budget
  "ciągle umieram na bossach"                                               -> survivability
  "brakuje mi many"                                                         -> mana

Every step comes with its measured gain, its cost and, where possible, steps that can be applied.
Nothing is guessed: what PoB cannot calculate is said in words.
"""
from __future__ import annotations

import re
import time
import unicodedata

from soe.optimize.objective import Objective


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)).replace("ł", "l")


GOAL_WORDS = {
    "hit": [r"one ?shot", r"jednym (strzal|hit|uderzen|trafien)", r"od (razu|strzala)", r"burst",
            r"pojedyncz\w* (hit|traf|cios)", r"wiekszy hit", r"mocniejszy hit", r"big hit"],
    "survive": [r"umier", r"gin(e|ie|a)", r"zgon", r"przezy", r"tank", r"obron", r"defens", r"ehp", r"zycia",
                r"oneshot\w* mnie", r"zabija mnie", r"dostaje", r"\bdie\b", r"dying", r"survive"],
    "mana": [r"\bman[aey]\b", r"\bmanie\b", r"mana", r"sustain"],
    "speed": [r"szybciej (biega|chodz|porusz)", r"predkosc ruchu", r"movement", r"move speed"],
    "dps": [r"\bdps\b", r"obrazen", r"\bdmg\b", r"damage", r"bic (mocniej|wiecej|szybciej)", r"wiecej bic",
            r"mocniej", r"zabija(c|m)", r"za slab", r"bossy?", r"clear", r"czysci"],
}


def parse_question(text: str, skills: list[str]) -> dict:
    """{goal, skill, budget_divine, understood: [...]} from free text."""
    t = _fold(text)
    understood = []
    goal = None
    # "oneshot" about the player being one-shot is survival, about the monster is damage
    if re.search(r"(oneshot\w*|one ?shot\w*) (mnie|me)|(mnie|me) (oneshot|one ?shot)", t):
        goal = "survive"
        understood.append("ktoś Cię oneshotuje → przetrwanie")
    else:
        for g in ("hit", "survive", "mana", "speed", "dps"):
            if any(re.search(p, t) for p in GOAL_WORDS[g]):
                goal = g
                understood.append({"hit": "chodzi o pojedynczy, mocny hit (oneshot)", "survive": "chodzi o przetrwanie",
                                   "mana": "chodzi o manę", "speed": "chodzi o prędkość ruchu",
                                   "dps": "chodzi o obrażenia (DPS)"}[g])
                break
    goal = goal or "dps"
    # skill: longest skill name mentioned (also by a single distinctive word, e.g. "comet")
    skill = None
    by_len = sorted(set(skills), key=len, reverse=True)
    for s in by_len:
        if _fold(s) in t:
            skill = s
            break
    if not skill:
        for s in by_len:
            words = [w for w in re.findall(r"[a-z']+", _fold(s)) if len(w) >= 4 and w not in ("skill", "minion", "summon")]
            if any(re.search(rf"\b{re.escape(w)}", t) for w in words):
                skill = s
                break
    if skill:
        understood.append(f"skill: {skill}")
    budget = None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(div|divine|diw)", t)
    if m:
        budget = float(m.group(1).replace(",", "."))
        understood.append(f"budżet: {budget:g} div")
    else:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ex|exalt)", t)
        if m:
            from soe.prices import default_prices

            ex = default_prices().rates.get("exalted") or 0
            if ex:
                budget = float(m.group(1).replace(",", ".")) / ex
                understood.append(f"budżet: {m.group(1)} ex")
    if re.search(r"bez (wydawania|kasy|waluty|currency)|za darmo|free", t):
        budget = 0.0
        understood.append("bez wydawania waluty")
    return {"goal": goal, "skill": skill, "budget_divine": budget, "understood": understood}


GOAL_LABEL = {"dps": "DPS", "hit": "średni hit", "survive": "EHP", "mana": "regeneracja many", "speed": "prędkość ruchu"}


def _objective(goal: str, base: dict) -> Objective:
    if goal == "hit":
        key = "AverageHit" if base.get("AverageHit") else "MainDPS"
        return Objective(damage=1, survive=0.1, speed=0.2, dps_key=key)
    if goal == "survive":
        return Objective(damage=0.15, survive=1, speed=0.2)
    if goal == "mana":
        return Objective(damage=0.1, survive=0.1, speed=0, dps_key="ManaRegenRecovery")
    if goal == "speed":
        return Objective(damage=0.2, survive=0.2, speed=1)
    return Objective(damage=1, survive=0.15, speed=0.3)


def _skill_list(pob) -> list[dict]:
    out = []
    for g in pob.groups():
        if not g["enabled"]:
            continue
        for j, name in enumerate(g["skills"], 1):
            out.append({"group": g["index"], "skill": j, "name": name, "main": g["main"] and j == g.get("main_skill_index", 1)})
    # same skill in several groups (e.g. once on its own, once in a trigger setup): tell them apart
    counts: dict[str, int] = {}
    for s in out:
        counts[s["name"]] = counts.get(s["name"], 0) + 1
    for s in out:
        s["label"] = f"{s['name']} (grupa {s['group']})" if counts[s["name"]] > 1 else s["name"]
    return out


def _gain_text(ex: dict, goal: str) -> str:
    parts = []
    main = ex.get("dps_pct")
    if main:
        parts.append(f"{GOAL_LABEL.get(goal, 'DPS') if goal != 'survive' else 'DPS'} {main:+.1f}%")
    if ex.get("ehp_pct"):
        parts.append(f"EHP {ex['ehp_pct']:+.1f}%")
    if ex.get("move_speed_pct"):
        parts.append(f"ruch {ex['move_speed_pct']:+.1f}%")
    return ", ".join(parts) or "bez zmian w liczbach"


def ask(session, question: str, skill: str | None = None, goal: str | None = None,
        budget_divine: float | None = None, deep: bool = True) -> dict:
    """Answer a free-text question with a measured to-do list. Takes ~20-60 s with deep=True."""
    from soe.combo.mechanics import config_check, profile
    from soe.items.craft import mod_upgrades
    from soe.items.uniques import rank_uniques
    from soe.optimize.stat_weights import stat_weights
    from soe.optimize.supports import optimize_supports
    from soe.optimize.tree import optimize_tree

    session._need_build()
    t0 = time.perf_counter()
    pob = session.pob
    skills = _skill_list(pob)
    parsed = parse_question(question or "", [s["name"] for s in skills])
    goal = goal or parsed["goal"]
    skill = skill or parsed["skill"]
    budget = budget_divine if budget_divine is not None else parsed["budget_divine"]
    understood = parsed["understood"]

    # switch the calculation to the asked skill for the analysis, put the old main skill back after
    prev = next((s for s in skills if s["main"]), None)
    target = None
    if skill and re.fullmatch(r"\d+:\d+", skill):  # "group:skill" from the app's skill list
        g, k = map(int, skill.split(":"))
        target = next((s for s in skills if s["group"] == g and s["skill"] == k), None)
        # a skill named in the question wins over the default selection in the list
        named = parsed["skill"] and next((s for s in skills if s["name"].lower() == parsed["skill"].lower()), None)
        if named and target and target["main"] and named["name"] != target["name"]:
            target = named
    elif skill:
        target = next((s for s in skills if s["name"].lower() == skill.lower()), None)
    target = target or prev
    switched = target and prev and (target["group"], target["skill"]) != (prev["group"], prev["skill"])
    if switched:
        session.apply_changes([{"op": "set_main_skill", "group": target["group"], "skill": target["skill"]}])
    # multi-part skills (a wall and its explosion, a slash and its whirlwind): analyse the part that hits hardest
    prev_set, best_set = None, None
    if target:
        n_sets = pob.set_stat_set(target["group"], target["skill"], None)
        if n_sets > 1:
            prev_set = pob.get_stat_set(target["group"], target["skill"])
            best = (-1, prev_set)
            for k in range(1, n_sets + 1):
                pob.set_stat_set(target["group"], target["skill"], k)
                sm = pob.summary()
                best = max(best, ((sm.get("MainDPS") or 0) + (sm.get("AverageHit") or 0), k))
            best_set = best[1]
            session.apply_changes([{"op": "set_stat_set", "group": target["group"], "skill": target["skill"],
                                    "stat_set": best_set}])
            if best_set != prev_set:
                understood.append(f"liczę część skilla nr {best_set} (ta zadaje obrażenia)")
    steps: list[dict] = []
    warnings: list[str] = []
    try:
        base = session.base
        obj = _objective(goal, base)
        skill_name = target["name"] if target else base.get("main_skill")
        group = pob.groups()[target["group"] - 1] if target else None

        # 1. the skill gem's own level
        if group:
            for i, gem in enumerate(group["gems"], 1):
                if not gem["support"] and gem["valid"] and gem["level"] < 20 and not group.get("slot"):
                    with pob.trial():
                        pob.set_gem(group["index"], i, level=20)
                        ex = obj.explain(pob.summary(), base)
                    if ex["score"] > 0.3:
                        from soe.prices import safe_price

                        pr = safe_price("Uncut Skill Gem (Level 20)")
                        steps.append({"kind": "gem", "title": f"Podnieś {gem['name']} z poziomu {gem['level']} na 20",
                                      "how": "Nowy gem z Uncut Skill Gem poziomu 20 albo dalsze levelowanie.",
                                      "gain": _gain_text(ex, goal), "score": ex["score"],
                                      "cost": pr["text"] if pr else "Uncut Skill Gem 20",
                                      "apply": [{"op": "set_gem", "group": group["index"], "gem": i, "level": 20}]})

        # 2. supports that do nothing for this skill (PoB's own rule), with the reason in words
        if group:
            for gem in group["gems"]:
                na = gem.get("not_applied")
                if gem["support"] and gem["enabled"] and not gem["applies"] and na:
                    steps.append({"kind": "dead_support", "title": f"{gem['name']} nie działa na {skill_name}",
                                  "how": explain_not_applied(na), "gain": "wolny slot na lepszy support",
                                  "score": 5.0, "cost": "-", "apply": None})

        # 3. support swaps (damage goals)
        combo = None
        if deep and goal in ("dps", "hit") and group and any(x["support"] for x in group["gems"]):
            sup = optimize_supports(session, target["group"], obj, budget_divine=budget)
            combo = sup.get("best_combination")
            singles = {(r["replace"], r["with"]): r for rows in sup["best_per_slot"].values() for r in rows}
            for sw, st in zip((combo or {}).get("swaps", []), (combo or {}).get("apply_steps", [])):
                row = singles.get((sw["replace"], sw["with"]))
                if not row or row["score"] <= 0.5:
                    continue
                steps.append({"kind": "support", "title": f"Zamień support {sw['replace']} na {sw['with']}",
                              "how": f"W grupie {skill_name}.", "gain": _gain_text(row, goal), "score": row["score"],
                              "cost": sw["price"]["text"] if sw.get("price") else "zwykły support (tani)",
                              "apply": [st]})
            for s in sup.get("current_supports_that_lower_the_score", []):
                warnings.append(f"Bez supportu {s['support']} PoB liczy więcej ({_gain_text(s, goal)}). Pewnie dajesz "
                                "go dla czegoś, czego PoB nie liczy (obrona, więcej celów, wygoda). Sprawdź, zanim wymienisz.")

        # 4. passive tree: refund weak, take strong
        tree = None
        if deep:
            tree = optimize_tree(session, obj, max_moves=4)
            for m in tree["moves"]:
                refund = f" Zwolnij: {', '.join(m['refund'])}." if m["refund"] else ""
                steps.append({"kind": "tree", "title": f"Drzewko: weź {m['add']} ({m['add_points']} pkt)",
                              "how": "Ścieżka liczona od Twojego drzewka." + refund, "gain": _gain_text(m, goal),
                              "score": m["gain"], "cost": "respec" if m["refund"] else "wolne punkty",
                              "apply": m["steps"], "node": m["add"]})

        # 5. gear: best single mod change per slot, and uniques that beat what you wear
        for it in pob.items(active_only=True):
            if it["slot"].startswith(("Flask", "Charm")):
                continue
            try:
                up = mod_upgrades(session, it["slot"], obj, limit=1)
            except Exception:
                continue
            if up["upgrades"] and not up["corrupted"] and up["upgrades"][0]["score"] > 1:
                u = up["upgrades"][0]
                ess = f" Esencja: {', '.join(u['essence'])}." if u["essence"] else ""
                steps.append({"kind": "gear", "title": f"{up['slot']}: zamień „{u['replace']}” na „{u['with']}”",
                              "how": f"Na {it['name'].split(',')[0]}.{ess}", "gain": _gain_text(u, goal),
                              "score": u["score"], "cost": "craft / nowy item", "apply": None})
        if deep:
            for it in pob.items(active_only=True):
                if it["slot"].startswith(("Flask", "Charm")):
                    continue
                try:
                    ru = rank_uniques(session, it["slot"], obj, limit=2)
                except Exception:
                    continue
                for u in ru["ranking"]:
                    if u["score"] > 2 and not u["penalty"] and (budget is None or not u.get("price")
                                                                 or u["price"]["divine"] <= budget):
                        steps.append({"kind": "unique", "title": f"{ru['slot']}: załóż {u['unique']} zamiast {ru['current'].split(',')[0]}",
                                      "how": "Policzone ze średnimi rollami unikatu." + (
                                          " Część efektów PoB nie liczy." if u.get("not_calculated") else ""),
                                      "gain": _gain_text(u, goal), "score": u["score"],
                                      "cost": u["price"]["text"] if u.get("price") else "brak ceny na poe.ninja",
                                      "apply": None})

        # 6. what to look for on new gear
        weights = stat_weights(pob, base, obj)["weights"][:6]
        look_for = [f"{w['stat']} ({_gain_text(w, goal)})" for w in weights if w["score"] > 0.3]

        # 7. config assumptions that inflate the numbers
        for c in config_check(session, profile(session)):
            warnings.append(f"PoB liczy, jakby {MECH_PL.get(c['mechanic'], c['mechanic'])} było cały czas aktywne, "
                            "a nic w buildzie tego nie robi. Realne obrażenia mogą być niższe.")

        steps.sort(key=lambda s: s["score"], reverse=True)

        # everything that can be applied, measured together
        together = None
        bundle = [st for s in steps if s.get("apply") for st in s["apply"]]
        if bundle:
            with pob.trial():
                notes = session._apply_steps(bundle)
                together = {**obj.explain(pob.summary(), base), "steps": bundle, "notes": notes}
            together["gain"] = _gain_text(together, goal)

        head = {"skill": skill_name, "goal": goal, "goal_label": GOAL_LABEL[goal],
                "now": {"dps": round(base.get("MainDPS") or 0), "average_hit": round(base.get("AverageHit") or 0),
                        "crit_chance": round(base.get("CritChance") or 0, 1), "ehp": round(base.get("TotalEHP") or 0)}}
        if goal == "hit":
            head["explain"] = ("Na oneshot liczy się pojedyncze trafienie, a nie DPS. Wszystko niżej jest "
                               "posortowane według tego, ile dokłada do średniego hitu "
                               f"(teraz {head['now']['average_hit']:,}, crit {head['now']['crit_chance']}%). "
                               "Mocniej niż szybkość ataku działają tu: obrażenia bazowe, „more” z supportów, "
                               "crit i penetracja.").replace(",", " ")
    finally:
        if best_set is not None and best_set != prev_set:
            session.apply_changes([{"op": "set_stat_set", "group": target["group"], "skill": target["skill"],
                                    "stat_set": prev_set}])
        if switched:
            session.apply_changes([{"op": "set_main_skill", "group": prev["group"], "skill": prev["skill"]}])
    return {"question": question, "understood": understood or ["nie rozpoznałem celu: liczę obrażenia"],
            **head, "budget_divine": budget, "steps": steps[:12], "all_together": together,
            "look_for_on_gear": look_for, "warnings": warnings, "skills": [s["name"] for s in skills],
            "seconds": round(time.perf_counter() - t0, 1)}


MECH_PL = {"Shock": "porażenie wroga (shock)", "Ignite": "podpalenie wroga", "Chill": "schłodzenie wroga (chill)",
           "Freeze": "zamrożenie wroga", "Bleeding": "krwawienie wroga", "Poison": "zatrucie wroga",
           "Blind": "oślepienie wroga", "Maim": "okaleczenie wroga", "Electrocute": "electrocute",
           "Power Charge": "maksimum power charge'ów", "Frenzy Charge": "maksimum frenzy charge'ów",
           "Endurance Charge": "maksimum endurance charge'ów", "Onslaught": "onslaught",
           "Arcane Surge": "arcane surge", "Rage": "rage", "Armour Break": "rozbity pancerz wroga",
           "Exposure": "exposure na wrogu", "Heavy Stun": "heavy stun", "Pin": "przygwożdżenie", "Daze": "daze",
           "Curse": "klątwa na wrogu"}

TYPE_PL = {
    "Triggered": "jest wyzwalany automatycznie (triggered), a ten support działa tylko na skille rzucane samemu",
    "Persistent": "jest trwały (aura/buff), a ten support go nie obsługuje",
    "Channel": "jest kanałowany",
    "Instant": "jest natychmiastowy",
    "HasSeals": "już ma pieczęcie (seals)",
    "Cooldown": "ma cooldown",
    "UsedByProxy": "jest używany przez coś innego (totem/minion/pułapka)",
    "Minion": "jest skillem miniona",
    "Spell": "nie jest czarem", "Attack": "nie jest atakiem", "Damage": "nie zadaje obrażeń bezpośrednio",
    "Projectile": "nie wystrzeliwuje pocisków", "Area": "nie ma obszaru działania", "Melee": "nie jest atakiem wręcz",
    "Duration": "nie ma czasu trwania", "Unleashable": "nie może korzystać z pieczęci",
}


def explain_not_applied(na: dict) -> str:
    ex = [TYPE_PL.get(t, t) for t in (na.get("excluded_by") or [])]
    miss = na.get("missing") or []
    if ex:
        return "Skill " + "; ".join(ex) + ". To zasada gry, nie błąd: support daje 0."
    if miss:
        req = {"Spell": "czarem", "Attack": "atakiem", "Damage": "skillem zadającym obrażenia", "Projectile": "pociskiem",
               "Area": "skillem obszarowym", "Melee": "atakiem wręcz", "Duration": "skillem z czasem trwania",
               "Minion": "skillem miniona", "Totem": "totemem", "Trap": "pułapką", "Warcry": "okrzykiem"}
        return ("Support działa tylko na skille, które są " + " albo ".join(req.get(m, m) for m in miss)
                + ". Ten skill taki nie jest, więc support daje 0.")
    return "PoB nie stosuje tego supportu do tego skilla."
