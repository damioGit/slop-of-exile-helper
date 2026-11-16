"""Improvement plan: the best concrete changes for a build, ranked, with steps that can be applied.

Combines the support optimizer (main skill), the passive tree optimizer, gem levels of the main
skill, and stat weights (what to look for on gear). Every gain is a PoB number; the final block
checks all gem and passive changes together, because gains do not simply add up.
"""
from __future__ import annotations

import time

from soe.optimize.objective import Objective
from soe.optimize.stat_weights import stat_weights
from soe.optimize.supports import optimize_supports
from soe.optimize.tree import optimize_tree

COST = {
    "gem_swap": "a support gem (cheap unless it is a lineage support)",
    "gem_level": "a higher level gem or Uncut Skill Gem",
    "respec": "regret orbs / gold for refunds",
    "gear": "a crafted or bought item",
}


def improvement_plan(session, goals: dict | None = None, use_supports: bool = True, use_tree: bool = True,
                     tree_moves: int = 6, top: int = 10) -> dict:
    session._need_build()
    t0 = time.perf_counter()
    obj = Objective.from_goals(goals)
    base = session.base
    pob = session.pob
    items: list[dict] = []

    if use_supports:
        sup = optimize_supports(session, objective=obj)
        best_combo = sup["best_combination"]
        # one row per swap of the best set, each with its own (single swap) gain
        singles = {(r["replace"], r["with"]): r for rows in sup["best_per_slot"].values() for r in rows}
        for swap, step in zip((best_combo or {}).get("swaps", []), (best_combo or {}).get("apply_steps", [])):
            row = singles[(swap["replace"], swap["with"])]
            alts = [r["with"] for r in sup["best_per_slot"].get(swap["replace"], []) if r["with"] != swap["with"]][:3]
            items.append({"kind": "gem_swap", "what": f"{sup['skill']}: {swap['replace']} -> {swap['with']}",
                          "score": row["score"], "dps_pct": row["dps_pct"], "ehp_pct": row["ehp_pct"],
                          "cost": COST["gem_swap"], "alternatives": alts, "steps": [step]})
    else:
        best_combo = None

    # main skill gem level
    main = next((g for g in pob.groups() if g["main"]), None)
    if main:
        for i, gem in enumerate(main["gems"], 1):
            if not gem["support"] and gem["valid"] and gem["level"] < 20:
                with pob.trial():
                    pob.set_gem(main["index"], i, level=20)
                    ex = obj.explain(pob.summary(), base)
                if ex["score"] > 0.3:
                    items.append({"kind": "gem_level", "what": f"{gem['name']} level {gem['level']} -> 20",
                                  **{k: ex[k] for k in ("score", "dps_pct", "ehp_pct")}, "cost": COST["gem_level"],
                                  "steps": [{"op": "set_gem", "group": main["index"], "gem": i, "level": 20}]})

    tree = None
    if use_tree:
        tree = optimize_tree(session, obj, max_moves=tree_moves)
        for m in tree["moves"]:
            items.append({"kind": "respec", "what": f"passives: +{m['add']} ({m['add_points']} pts)"
                                                    + (f", refund {', '.join(m['refund'])}" if m["refund"] else ""),
                          "score": m["gain"], "dps_pct": m["dps_pct"], "ehp_pct": m["ehp_pct"],
                          "cost": COST["respec"], "steps": m["steps"]})

    # gear: best single mod change per equipped slot
    from soe.items.craft import mod_upgrades

    for it in pob.items(active_only=True):
        if it["slot"].startswith(("Flask", "Charm", "Weapon")):
            continue
        try:
            up = mod_upgrades(session, it["slot"], obj, limit=1)
        except Exception:
            continue
        if up["upgrades"] and not up["corrupted"]:
            u = up["upgrades"][0]
            items.append({"kind": "gear", "what": f"{up['slot']} ({it['name']}): {u['replace']} -> {u['with']}",
                          "score": u["score"], "dps_pct": u["dps_pct"], "ehp_pct": u["ehp_pct"],
                          "cost": COST["gear"] + (f"; essence: {', '.join(u['essence'])}" if u["essence"] else ""),
                          "steps": []})

    weights = stat_weights(pob, base, obj)
    gear_targets = [{"stat": w["stat"], "score": w["score"], "dps_pct": w["dps_pct"], "ehp_pct": w["ehp_pct"]}
                    for w in weights["weights"][:8]]

    items.sort(key=lambda x: x["score"], reverse=True)
    items = items[:top]

    # everything gem + tree together: gains interact, so measure the bundle
    together = None
    bundle = []
    if best_combo:
        bundle += best_combo["apply_steps"]
    if tree and tree["apply_steps"]:
        bundle += tree["apply_steps"]
    if bundle:
        with pob.trial():
            notes = session._apply_steps(bundle)
            after = pob.summary()
        together = {**obj.explain(after, base), "steps": bundle, "notes": notes,
                    "includes": (["support set"] if best_combo else []) + (["tree moves"] if tree and tree["moves"] else [])}

    return {
        "goals": {"damage": obj.damage, "survive": obj.survive},
        "top_changes": items,
        "all_together": together,
        "gear_stat_priorities": gear_targets,
        "seconds": round(time.perf_counter() - t0, 1),
        "note": "Gains are PoB numbers under the current config (check conditions: charges, enemy distance, "
                "boss type). Apply with apply_changes using the steps; gear priorities tell what to look for "
                "on the next item (whatif_item measures a real one).",
    }
