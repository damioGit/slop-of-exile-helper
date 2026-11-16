"""Support gem optimizer: try compatible supports in the support slots of a skill, in parallel.

Every candidate is a real PoB recalculation in a pool of processes (gem swapped, recalculated,
swapped back), so conversions, triggers and conditional supports count exactly as PoB counts them.

Two stages keep it fast:
1. every candidate goes into the weakest current slot (the support whose removal costs least);
2. the best candidates are then tried in every slot, and the best set of swaps is checked together.

Rules respected: a support once per skill, and no two supports of the same gem family
(e.g. Magnified Area I and II) on one skill.
"""
from __future__ import annotations

import time

from soe.optimize.objective import Objective


def _main_group(pob) -> dict:
    main = next((g for g in pob.groups() if g["main"]), None)
    if main is None:
        raise RuntimeError("build has no main skill group")
    return main


def _family(kb, name: str) -> set:
    row = kb.gem(name)
    return set(row.get("family") or []) if row else set()


def candidates(kb, active_gem: str, group_gems: list[dict], slot_gem: dict) -> list[str]:
    """Supports allowed in place of slot_gem, given the other gems of the group."""
    others = [g for g in group_gems if g is not slot_gem]
    taken = {g["name"] for g in others}
    families = set()
    for g in others:
        if g["support"]:
            families |= _family(kb, g["name"])
    return [s["name"] for s in kb.supports_for(active_gem)
            if s["name"] not in taken and s["name"] != slot_gem["name"]
            and not (families & set(s.get("family") or []))]


def _swap_job(group: int, idx: int, old: dict, new_name: str | None) -> dict:
    if new_name is None:  # value of the current support = disable it
        do = [["set_gem", {"group": group, "gem": idx, "enabled": False}]]
        undo = [["set_gem", {"group": group, "gem": idx, "enabled": old["enabled"]}]]
    else:
        do = [["set_gem", {"group": group, "gem": idx, "name": new_name}]]
        undo = [["set_gem", {"group": group, "gem": idx, "name": old["name"], "level": old["level"],
                             "quality": old["quality"], "enabled": old["enabled"]}]]
    return {"do": do, "undo": undo}


def optimize_supports(session, group: int | None = None, objective: Objective | None = None,
                      top: int = 5, finalists: int = 12) -> dict:
    """Best support swaps for one skill group (default: main skill)."""
    session._need_build()
    pob, kb = session.pob, session.kb
    obj = objective or Objective()
    g = _main_group(pob) if group is None else pob.groups()[group - 1]
    gi, gems = g["index"], g["gems"]
    active = next((x for x in gems if not x["support"]), None)
    if active is None:
        raise ValueError(f"group {gi} has no active skill gem")
    slots = [(i, x) for i, x in enumerate(gems, 1) if x["support"]]
    if not slots:
        raise ValueError(f"group {gi} has no support gems to swap")
    pool = session.pool()
    t = time.perf_counter()
    n_eval = 0

    def run(jobs):
        nonlocal n_eval
        n_eval += len(jobs)
        return pool.run(jobs, chunksize=4)

    # value of each current support
    res = run([_swap_job(gi, idx, gem, None) for idx, gem in slots])
    current = {gem["name"]: obj.explain(r["result"], session.base) for (idx, gem), r in zip(slots, res) if r["ok"]}
    weakest_idx, weakest = max(slots, key=lambda s: current.get(s[1]["name"], {}).get("score", 0))

    # stage 1: every candidate in the weakest slot
    cands = candidates(kb, active["name"], gems, weakest)
    res = run([_swap_job(gi, weakest_idx, weakest, c) for c in cands])
    stage1 = sorted(((c, obj.explain(r["result"], session.base)) for c, r in zip(cands, res) if r["ok"]),
                    key=lambda x: x[1]["score"], reverse=True)
    best_names = [c for c, ex in stage1[:finalists] if ex["score"] > 0.05]

    # stage 2: finalists in every slot
    per_slot: dict[int, list] = {idx: [] for idx, _ in slots}
    jobs, meta = [], []
    for idx, gem in slots:
        allowed = set(candidates(kb, active["name"], gems, gem))
        for c in best_names:
            if c in allowed:
                if idx == weakest_idx:
                    per_slot[idx].append({"replace": gem["name"], "with": c, **dict(stage1)[c]})
                else:
                    jobs.append(_swap_job(gi, idx, gem, c))
                    meta.append((idx, gem["name"], c))
    for (idx, old, c), r in zip(meta, run(jobs)):
        if r["ok"]:
            per_slot[idx].append({"replace": old, "with": c, **obj.explain(r["result"], session.base)})
    for idx in per_slot:
        per_slot[idx].sort(key=lambda x: x["score"], reverse=True)

    # best set of swaps: greedy assignment (each slot once, each gem once), then checked together
    pairs = sorted(((idx, row) for idx, rows in per_slot.items() for row in rows if row["score"] > 0.05),
                   key=lambda x: x[1]["score"], reverse=True)
    used_slots, used_gems, chosen = set(), set(), []
    for idx, row in pairs:
        fam = _family(kb, row["with"])
        if idx in used_slots or row["with"] in used_gems or any(fam & _family(kb, c["with"]) for _, c in chosen):
            continue
        chosen.append((idx, row))
        used_slots.add(idx)
        used_gems.add(row["with"])
    combo = None
    if chosen:
        gem_at = dict(slots)
        do = [["set_gem", {"group": gi, "gem": idx, "name": row["with"]}] for idx, row in chosen]
        undo = [["set_gem", {"group": gi, "gem": idx, "name": gem_at[idx]["name"], "level": gem_at[idx]["level"],
                             "quality": gem_at[idx]["quality"], "enabled": gem_at[idx]["enabled"]}]
                for idx, _ in chosen]
        r = run([{"do": do, "undo": undo}])[0]
        if r["ok"]:
            from soe.prices import safe_price

            combo = {"swaps": [{"replace": row["replace"], "with": row["with"], "price": safe_price(row["with"])}
                               for _, row in chosen],
                     **obj.explain(r["result"], session.base),
                     "apply_steps": [{"op": "set_gem", **kw} for _, kw in do]}

    from soe.prices import safe_price

    return {
        "group": gi, "skill": active["name"], "evaluated": n_eval, "seconds": round(time.perf_counter() - t, 1),
        "current_supports": current,
        "stage1_top": [{"support": c, **ex, "price": safe_price(c)} for c, ex in stage1[:top * 2]],
        "best_per_slot": {per_slot[idx][0]["replace"] if per_slot[idx] else gem["name"]: per_slot[idx][:top]
                          for idx, gem in slots},
        "best_combination": combo,
        "note": "score ≈ % gain on the weighted DPS/EHP objective minus penalties. A current support worth 0 "
                "is either not modelled by PoB or useless here. price comes from poe.ninja (lineage supports); "
                "None = regular support (cut from an uncut support gem, cheap) or not listed.",
    }
