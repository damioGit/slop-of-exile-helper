"""Passive tree optimizer: spend free points and move points from weak passives to strong ones.

Greedy, one move at a time, every number from PoB:
1. score every reachable notable/keystone (with its path) and every refundable allocated passive
   with PoB's what-if calculator (fast, nothing changes);
2. for the best additions, pick the cheapest refunds that pay for their points and score the
   whole move together;
3. verify the best move by really applying it (PoB recomputes paths), keep it if it still wins;
4. repeat until no move gains enough.
The build is restored at the end; the result is a list of moves plus the final build code.
Only shared passives are moved (weapon-set passives use a separate point pool); ascendancy,
jewel sockets and masteries are left alone.
"""
from __future__ import annotations

import time

from soe.optimize.objective import Objective

_SKIP_TYPES = {"Socket", "Mastery", "ClassStart", "AscendClassStart"}


def _scan_adds(pob, cur: dict, obj: Objective, max_cost: int, types) -> list[dict]:
    rows = []
    for t in types:
        for n in pob.reachable(t, 3000):
            if n["cost"] > max_cost:
                continue
            w = pob.whatif(add_nodes=[n["id"]], with_path=True)
            gain = obj.score(w, cur)
            if gain > 0:
                rows.append({"id": n["id"], "name": n["name"], "points": w["points"], "gain": gain,
                             "per_point": gain / max(w["points"], 1)})
    rows.sort(key=lambda r: r["per_point"], reverse=True)
    return rows


def _scan_refunds(pob, cur: dict, obj: Objective, protected: set[int]) -> list[dict]:
    rows = []
    for n in pob.allocated_nodes():
        if n.get("ascendancy") or n["weapon_set"] or n["type"] in _SKIP_TYPES or n["id"] in protected:
            continue
        w = pob.whatif(remove_nodes=[n["id"]])
        freed = -w["points"]
        if freed <= 0:
            continue
        loss = -obj.score(w, cur)
        rows.append({"id": n["id"], "name": n["name"], "freed": freed, "loss": loss, "per_point": loss / freed,
                     "unmodelled": bool(n["unsupported"])})
    rows.sort(key=lambda r: r["per_point"])
    return rows


def optimize_tree(session, objective: Objective | None = None, max_moves: int = 8, max_path: int = 5,
                  include_small: bool = False, keep_unmodelled: bool = True, min_gain: float = 0.3) -> dict:
    """Greedy passive moves. keep_unmodelled: never refund passives with effects PoB cannot calculate."""
    session._need_build()
    pob = session.pob
    obj = objective or Objective()
    types = ("Notable", "Keystone", "Normal") if include_small else ("Notable", "Keystone")
    t0 = time.perf_counter()
    snap = pob.snapshot()
    start = pob.summary()
    start_pts = pob.points()
    moves, protected = [], set()
    try:
        for _ in range(max_moves):
            cur = pob.summary()
            pts = pob.points()
            free = max(0, pts["available"] - pts["used"])
            adds = _scan_adds(pob, cur, obj, max_path, types)[:10]
            refunds = [r for r in _scan_refunds(pob, cur, obj, protected)
                       if not (keep_unmodelled and r["unmodelled"])]
            proposals = []
            for a in adds:
                need, chosen, got = a["points"] - free, [], 0
                for r in refunds:
                    if got >= need:
                        break
                    chosen.append(r)
                    got += r["freed"]
                if got < need:
                    continue
                w = pob.whatif(add_nodes=[a["id"]], with_path=True, remove_nodes=[r["id"] for r in chosen] or None)
                proposals.append((obj.score(w, cur), a, chosen))
            proposals.sort(key=lambda p: p[0], reverse=True)

            applied = False
            for est, a, chosen in proposals[:3]:
                if est < min_gain:
                    break
                with pob.trial():
                    ok = all(pob.dealloc_node(r["id"]) for r in chosen) and pob.alloc_node(a["id"]) is not None
                    after, after_pts = pob.summary(), pob.points()
                real = obj.score(after, cur) if ok else -1e9
                if real < min_gain or after_pts["used"] > max(pts["used"], pts["available"]):
                    continue
                for r in chosen:
                    pob.dealloc_node(r["id"])
                pob.alloc_node(a["id"])
                protected.update(pob.node_path(a["id"]) or [a["id"]])
                protected.add(a["id"])
                moves.append({"add": a["name"], "add_points": a["points"],
                              "refund": [r["name"] for r in chosen],
                              "gain": round(real, 2), **{k: v for k, v in obj.explain(pob.summary(), cur).items()
                                                         if k != "score"},
                              "steps": [{"op": "dealloc_node", "node": r["id"]} for r in chosen]
                                       + [{"op": "alloc_node", "node": a["id"]}]})
                applied = True
                break
            if not applied:
                break
        final = pob.summary()
        final_pts = pob.points()
        final_code = pob.export_code() if moves else None
    finally:
        pob.restore(snap)
    return {
        "moves": moves,
        "total": obj.explain(final, start),
        "points": {"before": start_pts["used"], "after": final_pts["used"], "available": start_pts["available"]},
        "apply_steps": [s for m in moves for s in m["steps"]],
        "final_build_code": final_code,
        "seconds": round(time.perf_counter() - t0, 1),
        "note": "Greedy local search on PoB numbers under the current config; conditional passives count only "
                "if their condition is on. Passives with effects PoB cannot calculate are "
                + ("kept." if keep_unmodelled else "treated as worthless."),
    }
