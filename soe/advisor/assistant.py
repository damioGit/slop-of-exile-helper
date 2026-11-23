"""Assistant: a player's question in plain words -> a concrete, ordered to-do list measured in PoB.

Examples it understands (English or Polish; answers in the language of the request, soe.i18n):
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

from soe.i18n import t
from soe.optimize.objective import Objective


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)).replace("ł", "l")


GOAL_WORDS = {
    "hit": [r"one ?shot", r"jednym (strzal|hit|uderzen|trafien)", r"od (razu|strzala)", r"burst",
            r"pojedyncz\w* (hit|traf|cios)", r"wiekszy hit", r"mocniejszy hit", r"big(ger)? hits?", r"single hit",
            r"hit harder"],
    "survive": [r"umier", r"gin(e|ie|a)", r"zgon", r"przezy", r"tank", r"obron", r"defen[cs]", r"ehp", r"zycia",
                r"oneshot\w* mnie", r"zabija mnie", r"dostaje", r"\bdie\b", r"\bdies\b", r"dying", r"surviv",
                r"get(ting)? killed", r"squishy"],
    "mana": [r"\bman[aey]\b", r"\bmanie\b", r"mana", r"sustain"],
    "clear": [r"clear", r"czysc", r"mapy", r"mapowa", r"mapping", r"\bmaps?\b", r"farm"],
    "speed": [r"szybciej (biega|chodz|porusz)", r"predkosc ruchu", r"movement", r"move speed", r"run faster"],
    "dps": [r"\bdps\b", r"obrazen", r"\bdmg\b", r"damage", r"bic (mocniej|wiecej|szybciej)", r"wiecej bic",
            r"mocniej", r"zabija(c|m)", r"za slab", r"bossy?", r"clear", r"czysci", r"stronger", r"kill faster",
            r"too weak"],
}


def parse_question(text: str, skills: list[str]) -> dict:
    """{goal, skill, budget_divine, understood: [...]} from free text."""
    q = _fold(text)
    understood = []
    goal = None
    # "oneshot" about the player being one-shot is survival, about the monster is damage
    if re.search(r"(oneshot\w*|one ?shot\w*) (mnie|me)|(mnie|me) (oneshot|one ?shot)|i get one ?shot", q):
        goal = "survive"
        understood.append(t("something one-shots you -> survival", "ktoś Cię oneshotuje → przetrwanie"))
    else:
        for g in ("hit", "survive", "mana", "clear", "speed", "dps"):
            if any(re.search(pat, q) for pat in GOAL_WORDS[g]):
                goal = g
                understood.append({"hit": t("about a single, strong hit (one-shot)", "chodzi o pojedynczy, mocny hit (oneshot)"),
                                   "survive": t("about survival", "chodzi o przetrwanie"),
                                   "mana": t("about mana", "chodzi o manę"),
                                   "speed": t("about movement speed", "chodzi o prędkość ruchu"),
                                   "clear": t("about clearing maps", "chodzi o czyszczenie map (clear)"),
                                   "dps": t("about damage (DPS)", "chodzi o obrażenia (DPS)")}[g])
                break
    goal = goal or "dps"
    # skill: longest skill name mentioned (also by a single distinctive word, e.g. "comet")
    skill = None
    by_len = sorted(set(skills), key=len, reverse=True)
    for s in by_len:
        if _fold(s) in q:
            skill = s
            break
    if not skill:
        for s in by_len:
            words = [w for w in re.findall(r"[a-z']+", _fold(s)) if len(w) >= 4 and w not in ("skill", "minion", "summon")]
            if any(re.search(rf"\b{re.escape(w)}", q) for w in words):
                skill = s
                break
    if skill:
        understood.append(f"skill: {skill}")
    budget = None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(div|divine|diw)", q)
    if m:
        budget = float(m.group(1).replace(",", "."))
        understood.append(t(f"budget: {budget:g} div", f"budżet: {budget:g} div"))
    else:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(ex|exalt)", q)
        if m:
            from soe.prices import default_prices

            ex = default_prices().rates.get("exalted") or 0
            if ex:
                budget = float(m.group(1).replace(",", ".")) / ex
                understood.append(t(f"budget: {m.group(1)} ex", f"budżet: {m.group(1)} ex"))
    if re.search(r"bez (wydawania|kasy|waluty|currency)|za darmo|free|no currency|without spending", q):
        budget = 0.0
        understood.append(t("without spending currency", "bez wydawania waluty"))
    return {"goal": goal, "skill": skill, "budget_divine": budget, "understood": understood}


def goal_label(goal: str) -> str:
    return {"dps": "DPS", "hit": t("average hit", "średni hit"), "survive": "EHP",
            "mana": t("mana regeneration", "regeneracja many"), "speed": t("movement speed", "prędkość ruchu"),
            "clear": t("clear (DPS + projectiles + area + movement)", "clear (DPS + pociski + obszar + ruch)")}[goal]


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
    if goal == "clear":
        # clearing maps: damage still first, then more projectiles / bigger area / projectile speed / moving faster
        return Objective(damage=1, survive=0.1, speed=0.6,
                         extra={"ProjectileCount": 0.5, "AreaOfEffectRadiusMetres": 0.5, "ProjectileSpeedMod": 0.2})
    return Objective(damage=1, survive=0.15, speed=0.3)


def _exalt_divine() -> float | None:
    from soe.prices import safe_price

    p = safe_price("Exalted Orb")
    return p["divine"] if p else None


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
        s["label"] = t(f"{s['name']} (group {s['group']})", f"{s['name']} (grupa {s['group']})") if counts[s["name"]] > 1 else s["name"]
    return out


def _gain_text(ex: dict, goal: str) -> str:
    parts = []
    main = ex.get("dps_pct")
    if main:
        parts.append(f"{goal_label(goal) if goal in ('hit', 'mana') else 'DPS'} {main:+.1f}%")
    if ex.get("ehp_pct"):
        parts.append(f"EHP {ex['ehp_pct']:+.1f}%")
    if ex.get("move_speed_pct"):
        parts.append(t("movement", "ruch") + f" {ex['move_speed_pct']:+.1f}%")
    if ex.get("ProjectileCount_pct"):
        parts.append(t("projectiles", "pociski") + f" {ex['ProjectileCount_pct']:+.0f}%")
    if ex.get("AreaOfEffectRadiusMetres_pct"):
        parts.append(t("area", "obszar") + f" {ex['AreaOfEffectRadiusMetres_pct']:+.0f}%")
    return ", ".join(parts) or t("no change in the numbers", "bez zmian w liczbach")


def ask(session, question: str, skill: str | None = None, goal: str | None = None,
        budget_divine: float | None = None, deep: bool = True, market: bool = True) -> dict:
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
                understood.append(t(f"calculating part {best_set} of the skill (the one that deals damage)",
                                    f"liczę część skilla nr {best_set} (ta zadaje obrażenia)"))
    steps: list[dict] = []
    beyond: list[dict] = []  # real gains that the budget does not cover (lotteries, expensive items)
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
                        steps.append({"kind": "gem", "title": t(f"Raise {gem['name']} from level {gem['level']} to 20",
                                                                f"Podnieś {gem['name']} z poziomu {gem['level']} na 20"),
                                      "how": t("A new gem from a level 20 Uncut Skill Gem, or keep levelling.",
                                               "Nowy gem z Uncut Skill Gem poziomu 20 albo dalsze levelowanie."),
                                      "gain": _gain_text(ex, goal), "score": ex["score"],
                                      "cost": pr["text"] if pr else "Uncut Skill Gem 20",
                                      "apply": [{"op": "set_gem", "group": group["index"], "gem": i, "level": 20}]})

        # 2. supports that do nothing for this skill (PoB's own rule), with the reason in words
        if group:
            for gem in group["gems"]:
                na = gem.get("not_applied")
                if gem["support"] and gem["enabled"] and not gem["applies"] and na:
                    steps.append({"kind": "dead_support", "title": t(f"{gem['name']} does not apply to {skill_name}",
                                                                     f"{gem['name']} nie działa na {skill_name}"),
                                  "how": explain_not_applied(na),
                                  "gain": t("a free socket for a better support", "wolny slot na lepszy support"),
                                  "score": 5.0, "cost": "-", "apply": None})

        # 3. support swaps (damage goals)
        combo = None
        if deep and goal in ("dps", "hit", "clear") and group and any(x["support"] for x in group["gems"]):
            sup = optimize_supports(session, target["group"], obj, budget_divine=budget)
            combo = sup.get("best_combination")
            singles = {(r["replace"], r["with"]): r for rows in sup["best_per_slot"].values() for r in rows}
            for sw, st in zip((combo or {}).get("swaps", []), (combo or {}).get("apply_steps", [])):
                row = singles.get((sw["replace"], sw["with"]))
                if not row or row["score"] <= 0.5:
                    continue
                steps.append({"kind": "support", "title": t(f"Swap the support {sw['replace']} for {sw['with']}",
                                                            f"Zamień support {sw['replace']} na {sw['with']}"),
                              "how": t(f"In the {skill_name} group.", f"W grupie {skill_name}."),
                              "gain": _gain_text(row, goal), "score": row["score"],
                              "cost": sw["price"]["text"] if sw.get("price") else t("a common support (cheap)", "zwykły support (tani)"),
                              "apply": [st]})
            for s in sup.get("current_supports_that_lower_the_score", []):
                warnings.append(t(f"Without the support {s['support']} PoB calculates more ({_gain_text(s, goal)}). You probably "
                                  "use it for something PoB does not count (defence, more targets, comfort). Check before swapping.",
                                  f"Bez supportu {s['support']} PoB liczy więcej ({_gain_text(s, goal)}). Pewnie dajesz "
                                  "go dla czegoś, czego PoB nie liczy (obrona, więcej celów, wygoda). Sprawdź, zanim wymienisz."))

        # 4. passive tree: refund weak, take strong
        tree = None
        if deep:
            tree = optimize_tree(session, obj, max_moves=4)
            for m in tree["moves"]:
                refund = t(f" Refund: {', '.join(m['refund'])}.", f" Zwolnij: {', '.join(m['refund'])}.") if m["refund"] else ""
                steps.append({"kind": "tree", "title": t(f"Tree: take {m['add']} ({m['add_points']} pts)",
                                                         f"Drzewko: weź {m['add']} ({m['add_points']} pkt)"),
                              "how": t("Path counted from your tree.", "Ścieżka liczona od Twojego drzewka.") + refund,
                              "gain": _gain_text(m, goal),
                              "score": m["gain"], "cost": "respec" if m["refund"] else t("free points", "wolne punkty"),
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
                ess = t(f" Essence: {', '.join(u['essence'])}.", f" Esencja: {', '.join(u['essence'])}.") if u["essence"] else ""
                odds = u.get("odds") or {}
                exalts = round(100 / odds["family_pct"]) if odds.get("family_pct") else None
                ex_price = _exalt_divine()
                est = exalts * ex_price if exalts and ex_price else None
                top = u.get("top") or {}
                top_txt = t(f" The best possible roll (\"{top.get('with')}\", needs item level {top.get('level')}) would give "
                            f"{_gain_text(top, goal)}, but its chance is about {odds.get('top_tier_pct', '?')}% per exalt:"
                            " a lottery or an expensive market item.",
                            f" Najlepszy możliwy roll („{top.get('with')}”, wymaga item level {top.get('level')}) dałby "
                            f"{_gain_text(top, goal)}, ale szansa na niego to ok. {odds.get('top_tier_pct', '?')}% na exalta:"
                            " loteria albo drogi item z rynku.") if top and top.get("with") != u["with"] else ""
                step = {"kind": "gear", "slot": up["slot"], "wanted": u["with"],
                        "title": t(f"{up['slot']}: replace \"{u['replace']}\" with \"{u['with']}\" ({u.get('with_tier', '')})",
                                   f"{up['slot']}: zamień „{u['replace']}” na „{u['with']}” ({u.get('with_tier', '')})"),
                        "how": t(f"On {it['name'].split(',')[0]}. A realistic roll (middle tier).{ess}{top_txt} "
                                 "First the old mod has to go (annul is random), or buy an item with this mod.",
                                 f"Na {it['name'].split(',')[0]}. Realny roll (środkowy tier).{ess}{top_txt} "
                                 "Najpierw trzeba usunąć stary mod (annul jest losowy) albo kupić item z tym modem."),
                        "gain": _gain_text(u, goal), "score": u["score"],
                        "cost": (t(f"craft: about {exalts} exalts to hit this mod family", f"craft: ok. {exalts} exaltów na trafienie tej rodziny modów")
                                 + (f" (≈{est:.1f} div)" if est and est >= 1 else "") + t(", estimate", ", szacunek"))
                                if exalts else t("craft / new item", "craft / nowy item"),
                        "apply": None}
                if budget is not None and est is not None and est > budget:
                    beyond.append(step)
                else:
                    steps.append(step)
        if deep:
            for it in pob.items(active_only=True):
                if it["slot"].startswith(("Flask", "Charm")):
                    continue
                try:
                    ru = rank_uniques(session, it["slot"], obj, limit=2)
                except Exception:
                    continue
                for u in ru["ranking"]:
                    if u["score"] > 2 and not u["penalty"]:
                        cur_name = ru["current"].split(",")[0]
                        step = {"kind": "unique", "title": t(f"{ru['slot']}: wear {u['unique']} instead of {cur_name}",
                                                             f"{ru['slot']}: załóż {u['unique']} zamiast {cur_name}"),
                                "how": t("Calculated with the unique's average rolls.", "Policzone ze średnimi rollami unikatu.") + (
                                    t(" PoB does not count some of its effects.", " Część efektów PoB nie liczy.")
                                    if u.get("not_calculated") else ""),
                                "gain": _gain_text(u, goal), "score": u["score"],
                                "cost": u["price"]["text"] if u.get("price") else t("no price on poe.ninja", "brak ceny na poe.ninja"),
                                "apply": None}
                        over = budget is not None and u.get("price") and u["price"]["divine"] > budget
                        (beyond if over else steps).append(step)

        # 6. what to look for on new gear
        weights = stat_weights(pob, base, obj)["weights"][:6]
        look_for = [f"{w['stat']} ({_gain_text(w, goal)})" for w in weights if w["score"] > 0.3]

        # 7. config assumptions that inflate the numbers
        for c in config_check(session, profile(session)):
            mech = mech_name(c["mechanic"])
            warnings.append(t(f"PoB calculates as if {mech} were always active, and nothing in the build does it. "
                              "Real damage may be lower.",
                              f"PoB liczy, jakby {mech} było cały czas aktywne, a nic w buildzie tego nie robi. "
                              "Realne obrażenia mogą być niższe."))

        steps.sort(key=lambda s: s["score"], reverse=True)

        # real items on the trade site for the two best gear ideas: priced, measured, within budget
        if deep and market:
            from soe.prices.trade import TradeError, find_upgrade

            for st in [s for s in steps + beyond if s["kind"] == "gear"][:2]:
                try:
                    m = find_upgrade(session, st["slot"], st["wanted"], budget, obj)
                except TradeError as e:
                    st["market"] = {"error": str(e)}
                    continue
                best = next((x for x in m["items"] if x["score"] > 0.5), None)
                st["market"] = {"link": m.get("link"), "searched": m.get("searched_mods", []), "found": m.get("found", 0),
                                "warning": m.get("warning"),
                                "best": {k: best[k] for k in ("name", "price", "price_divine", "mods", "implicits",
                                                               "grants_skill", "dps_pct", "ehp_pct", "score")} if best else None,
                                "verdict": (t(f"On the market: {best['name']} for {best['price']} gives {_gain_text(best, goal)}.",
                                              f"Na rynku: {best['name']} za {best['price']} daje {_gain_text(best, goal)}.")
                                            if best else
                                            t("Nothing on the market right now within budget keeps the strength of your "
                                              "current item and adds this mod. Better craft it or save more currency.",
                                              "Na rynku nie ma teraz itemu w budżecie, który zachowa siłę Twojego obecnego "
                                              "i doda ten mod. Lepiej craftować albo odłożyć więcej waluty."))}

        # everything that can be applied, measured together
        together = None
        bundle = [st for s in steps if s.get("apply") for st in s["apply"]]
        if bundle:
            with pob.trial():
                notes = session._apply_steps(bundle)
                together = {**obj.explain(pob.summary(), base), "steps": bundle, "notes": notes}
            together["gain"] = _gain_text(together, goal)

        head = {"skill": skill_name, "goal": goal, "goal_label": goal_label(goal),
                "now": {"dps": round(base.get("MainDPS") or 0), "average_hit": round(base.get("AverageHit") or 0),
                        "crit_chance": round(base.get("CritChance") or 0, 1), "ehp": round(base.get("TotalEHP") or 0)}}
        if goal == "hit":
            hit = f"{head['now']['average_hit']:,}".replace(",", " ")
            head["explain"] = t("For a one-shot the single hit counts, not DPS. Everything below is sorted by how much "
                                f"it adds to the average hit (now {hit}, crit {head['now']['crit_chance']}%). Base damage, "
                                "\"more\" from supports, crit and penetration work better here than attack speed.",
                                "Na oneshot liczy się pojedyncze trafienie, a nie DPS. Wszystko niżej jest "
                                "posortowane według tego, ile dokłada do średniego hitu "
                                f"(teraz {hit}, crit {head['now']['crit_chance']}%). "
                                "Mocniej niż szybkość ataku działają tu: obrażenia bazowe, „more” z supportów, "
                                "crit i penetracja.")
    finally:
        if best_set is not None and best_set != prev_set:
            session.apply_changes([{"op": "set_stat_set", "group": target["group"], "skill": target["skill"],
                                    "stat_set": prev_set}])
        if switched:
            session.apply_changes([{"op": "set_main_skill", "group": prev["group"], "skill": prev["skill"]}])
    return {"question": question, "understood": understood or [t("goal not recognised: calculating damage",
                                                                  "nie rozpoznałem celu: liczę obrażenia")],
            **head, "budget_divine": budget, "steps": steps[:12], "beyond_budget": beyond[:6], "all_together": together,
            "look_for_on_gear": look_for, "warnings": warnings, "skills": [s["name"] for s in skills],
            "seconds": round(time.perf_counter() - t0, 1)}


MECH = {"Shock": ("shocking the enemy", "porażenie wroga (shock)"), "Ignite": ("igniting the enemy", "podpalenie wroga"),
        "Chill": ("chilling the enemy", "schłodzenie wroga (chill)"), "Freeze": ("freezing the enemy", "zamrożenie wroga"),
        "Bleeding": ("the enemy bleeding", "krwawienie wroga"), "Poison": ("poisoning the enemy", "zatrucie wroga"),
        "Blind": ("blinding the enemy", "oślepienie wroga"), "Maim": ("maiming the enemy", "okaleczenie wroga"),
        "Electrocute": ("electrocute", "electrocute"),
        "Power Charge": ("maximum power charges", "maksimum power charge'ów"),
        "Frenzy Charge": ("maximum frenzy charges", "maksimum frenzy charge'ów"),
        "Endurance Charge": ("maximum endurance charges", "maksimum endurance charge'ów"),
        "Onslaught": ("onslaught", "onslaught"), "Arcane Surge": ("arcane surge", "arcane surge"), "Rage": ("rage", "rage"),
        "Armour Break": ("broken enemy armour", "rozbity pancerz wroga"), "Exposure": ("exposure on the enemy", "exposure na wrogu"),
        "Heavy Stun": ("heavy stun", "heavy stun"), "Pin": ("pin", "przygwożdżenie"), "Daze": ("daze", "daze"),
        "Curse": ("a curse on the enemy", "klątwa na wrogu")}


def mech_name(m: str) -> str:
    return t(*MECH[m]) if m in MECH else m


TYPES = {
    "Triggered": ("is triggered automatically, and this support works only on skills you use yourself",
                  "jest wyzwalany automatycznie (triggered), a ten support działa tylko na skille rzucane samemu"),
    "Persistent": ("is persistent (aura/buff), and this support does not handle it", "jest trwały (aura/buff), a ten support go nie obsługuje"),
    "Channel": ("is channelled", "jest kanałowany"),
    "Instant": ("is instant", "jest natychmiastowy"),
    "HasSeals": ("already has seals", "już ma pieczęcie (seals)"),
    "Cooldown": ("has a cooldown", "ma cooldown"),
    "UsedByProxy": ("is used by something else (totem/minion/trap)", "jest używany przez coś innego (totem/minion/pułapka)"),
    "Minion": ("is a minion skill", "jest skillem miniona"),
    "Spell": ("is not a spell", "nie jest czarem"), "Attack": ("is not an attack", "nie jest atakiem"),
    "Damage": ("does not deal damage directly", "nie zadaje obrażeń bezpośrednio"),
    "Projectile": ("fires no projectiles", "nie wystrzeliwuje pocisków"), "Area": ("has no area of effect", "nie ma obszaru działania"),
    "Melee": ("is not a melee attack", "nie jest atakiem wręcz"),
    "Duration": ("has no duration", "nie ma czasu trwania"), "Unleashable": ("cannot use seals", "nie może korzystać z pieczęci"),
}
REQUIRES = {"Spell": ("spells", "czarem"), "Attack": ("attacks", "atakiem"), "Damage": ("damaging skills", "skillem zadającym obrażenia"),
            "Projectile": ("projectile skills", "pociskiem"), "Area": ("area skills", "skillem obszarowym"),
            "Melee": ("melee attacks", "atakiem wręcz"), "Duration": ("skills with a duration", "skillem z czasem trwania"),
            "Minion": ("minion skills", "skillem miniona"), "Totem": ("totems", "totemem"), "Trap": ("traps", "pułapką"),
            "Warcry": ("warcries", "okrzykiem")}


def explain_not_applied(na: dict) -> str:
    ex = [t(*TYPES[x]) if x in TYPES else x for x in (na.get("excluded_by") or [])]
    miss = na.get("missing") or []
    if ex:
        return t("The skill " + "; ".join(ex) + ". A game rule, not a bug: the support gives 0.",
                 "Skill " + "; ".join(ex) + ". To zasada gry, nie błąd: support daje 0.")
    if miss:
        names = [t(*REQUIRES[m]) if m in REQUIRES else m for m in miss]
        return t("The support works only on " + " or ".join(names) + ". This skill is not one, so the support gives 0.",
                 "Support działa tylko na skille, które są " + " albo ".join(names)
                 + ". Ten skill taki nie jest, więc support daje 0.")
    return t("PoB does not apply this support to this skill.", "PoB nie stosuje tego supportu do tego skilla.")
