"""Advisor session: one loaded build plus the knowledge base, with answers shaped for an LLM.

Everything returns plain JSON-able dicts. Numbers come from PoB; nothing here guesses.
"""
from __future__ import annotations

import threading
from pathlib import Path

from soe.engine.pob import PoB, SUMMARY_KEYS

METRICS = {
    "dps": "MainDPS", "combined_dps": "CombinedDPS", "hit_dps": "TotalDPS", "minion_dps": "MinionDPS", "ehp": "TotalEHP", "life": "Life", "es": "EnergyShield",
    "mana": "Mana", "evasion": "Evasion", "armour": "Armour", "speed": "Speed",
    "phys_max_hit": "PhysicalMaximumHitTaken", "chaos_max_hit": "ChaosMaximumHitTaken",
    "movement": "MovementSpeedMod",
}

# operations allowed in try_changes / apply_changes, mapped to PoB methods
OPS = {
    "set_gem": "set_gem", "remove_gem": "remove_gem", "set_main_skill": "set_main_skill",
    "equip": "equip", "unequip": "unequip", "set_config": "set_config", "set_level": "set_level",
    "alloc_node": "alloc_node", "dealloc_node": "dealloc_node", "paste_gems": "paste_gems",
    "set_stat_set": "set_stat_set",
}

_ROUND = 2


def _r(v):
    return round(v, _ROUND) if isinstance(v, float) else v


def diff(before: dict, after: dict, keys=SUMMARY_KEYS, min_change: float = 1e-6) -> dict:
    """Changed stats only: {stat: [before, after, delta, pct]}."""
    out = {}
    for k in keys:
        a, b = before.get(k), after.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and abs(b - a) > min_change:
            pct = round((b - a) / a * 100, 1) if a else None
            out[k] = [_r(a), _r(b), _r(b - a), pct]
    return out


def metric_key(metric: str) -> str:
    if metric in SUMMARY_KEYS:
        return metric
    try:
        return METRICS[metric.lower()]
    except KeyError:
        raise ValueError(f"unknown metric {metric!r}; use one of {sorted(METRICS)} or a stat name") from None


class Session:
    def __init__(self, kb_path: Path | None = None):
        self._pob: PoB | None = None
        self._kb = None
        self._kb_path = kb_path
        self.lock = threading.RLock()
        self.loaded = False
        self.name = None
        self.base: dict = {}
        self.original_code: str | None = None

    # ---- process pool (parallel full recalculations) ------------------------------
    _pool = None
    _pool_xml = None
    pool_workers: int | None = None

    def pool(self):
        """Pool of PoB processes loaded with the current build state (rebuilt when the build changed)."""
        from soe.engine.pool import PoBPool

        self._need_build()
        xml = self.pob.export_xml()
        if self._pool is None or self._pool_xml != xml:
            self.close_pool()
            self._pool = PoBPool(xml=xml, workers=self.pool_workers)
            self._pool_xml = xml
        return self._pool

    def close_pool(self):
        if self._pool is not None:
            self._pool.close()
            self._pool = None

    # ---- lazy resources ----------------------------------------------------------
    @property
    def pob(self) -> PoB:
        if self._pob is None:
            self._pob = PoB()
        return self._pob

    @property
    def kb(self):
        if self._kb is None:
            from soe.kb import KB

            self._kb = KB(self._kb_path) if self._kb_path else KB()
        return self._kb

    def _need_build(self):
        if not self.loaded:
            raise RuntimeError("no build loaded; call load_build first")

    # ---- build -------------------------------------------------------------------
    source: dict | None = None  # where the loaded build came from (poe.ninja import), for re-sync

    def import_character(self, ref: str, name: str | None = None) -> dict:
        """Load a public character from poe.ninja: a character link, or account (Name#1234) + character name."""
        from soe.prices.characters import fetch_character

        c = fetch_character(ref, name)
        summary = self.load(c["code"], c["name"])
        self.source = {k: c[k] for k in ("account", "name", "league", "class", "level", "updated", "source")}
        return {"character": self.source, "summary": summary}

    def resync(self) -> dict:
        """Fetch the imported character again (after playing / changing gear) and reload it."""
        if not self.source:
            raise RuntimeError("the build was not imported from poe.ninja; use import_character first")
        return self.import_character(self.source["account"], self.source["name"])

    def load(self, build: str, name: str = "build") -> dict:
        self.source = None  # set again by import_character
        text = build.strip()
        if len(text) < 300 and Path(text).exists():
            text = Path(text).read_text(encoding="utf-8").strip()
        if text.startswith("<"):
            self.pob.load_xml(text, name)
        else:
            self.pob.load_code(text, name)
        self.loaded, self.name = True, name
        self.original_code = self.pob.export_code()
        self.base = self.pob.summary()
        return self.base

    def reset(self) -> dict:
        """Back to the build as it was loaded (drops apply_changes)."""
        self._need_build()
        self.pob.load_code(self.original_code, self.name)
        self.base = self.pob.summary()
        return self.base

    def overview(self, with_all_skills: bool = True) -> dict:
        self._need_build()
        p = self.pob
        res = {"summary": self.base}
        res["skill_groups"] = [
            {"group": g["index"], "main": g["main"], "enabled": g["enabled"], "slot": g.get("slot"),
             "skills": g["skills"],
             "gems": [f"{x['name']} {x['level']}/{x['quality']}" + ("" if x["enabled"] else " (disabled)")
                     + ("" if x.get("applies", True) or not x["enabled"] else " (nie działa na ten skill)")
                     for x in g["gems"]]}
            for g in p.groups()
        ]
        if with_all_skills:
            res["skill_dps"] = [
                {k: _r(v) for k, v in d.items() if v or k in ("group", "name")}
                for d in p.all_skill_dps()
                if d["TotalDPS"] or d["TotalDotDPS"] or d["MinionDPS"]
            ]
        res["items"] = [{"slot": i["slot"], "name": i["name"], "rarity": i["rarity"]} for i in p.items(active_only=True)]
        res["weapon_set"] = "second (swap)" if p.resolve_slot("Weapon 1").endswith("Swap") else "first"
        opts = {o["var"]: o.get("value") for o in p.config_options()}
        res["config"] = {k: opts.get(k) for k in ("enemyIsBoss", "enemyLevel", "usePowerCharges", "useFrenzyCharges",
                                                  "useEnduranceCharges", "conditionEnemyShocked", "conditionEnemyIgnited",
                                                  "enemyDistance")}
        res["enemy"] = p.enemy_resists()
        res["passive_points"] = p.points()
        if res["passive_points"]["unspent"] < 0:
            res["passive_points"]["note"] = ("more points allocated than PoB's maximum for this level; the character may "
                                             "have a point source PoB does not know, or the tree is over budget")
        return res

    def item(self, slot: str) -> dict | None:
        self._need_build()
        real = self.pob.resolve_slot(slot)
        return next((i for i in self.pob.items() if i["slot"] == real), None)

    def config(self, search: str | None = None, only_set: bool = False) -> list[dict]:
        self._need_build()
        res = []
        for o in self.pob.config_options():
            if only_set and o.get("value") in (None, False):
                continue
            if search and search.lower() not in (o.get("label") or "").lower() and search.lower() not in o["var"].lower():
                continue
            res.append(o)
        return res

    # ---- passive nodes -----------------------------------------------------------
    def resolve_node(self, ref, want_allocated: bool | None = None) -> int:
        """Node id from an id or a name. Same-named nodes: the allocated one if want_allocated,
        otherwise the cheapest unallocated one to reach."""
        if isinstance(ref, int) or str(ref).isdigit():
            return int(ref)
        cands = []
        for n in self.kb.node(str(ref)):
            info = self.pob.node_info(n["id"])
            if not info:
                continue
            if want_allocated is True and not info["alloc"]:
                continue
            if want_allocated is False and info["alloc"]:
                continue
            cands.append((info.get("cost") or 10_000, n["id"]))
        if not cands:
            raise ValueError(f"no passive node named {ref!r}" + (" that is allocated" if want_allocated else ""))
        return min(cands)[1]

    # ---- explanations ----------------------------------------------------------------
    NO_CHANGE = ("PoB shows no stat change. Either the effect is conditional and the condition is off in the config "
                 "(check build_config), or PoB does not model this mechanic, or it really does nothing for this build.")

    def _node_notes(self, ids: list[int]) -> list[str]:
        notes = []
        active_set = self.pob.points()["active_weapon_set"]
        for i in ids:
            n = self.pob.node_info(i)
            if not n:
                continue
            if n["alloc"] and n["weapon_set"] and n["weapon_set"] != active_set:
                notes.append(f"{n['name']}: allocated to weapon set {n['weapon_set']}, but the build calculates "
                             f"weapon set {active_set}, so it counts for nothing here")
            if n["unsupported"]:
                notes.append(f"{n['name']}: PoB does not calculate: " + "; ".join(n["unsupported"]))
        return notes

    # ---- what-if (no change to the build) ------------------------------------------
    def whatif_passives(self, add=None, remove=None) -> dict:
        self._need_build()
        add_ids = [self.resolve_node(x, want_allocated=False) for x in (add or [])]
        rem_ids = [self.resolve_node(x, want_allocated=True) for x in (remove or [])]
        w = self.pob.whatif(add_nodes=add_ids or None, with_path=True, remove_nodes=rem_ids or None)
        changes = diff(self.base, w)
        notes = self._node_notes(add_ids + rem_ids)
        if not changes:
            notes.append(self.NO_CHANGE)
        return {"points": w.pop("points"),
                "nodes": [self.pob.node_info(i)["name"] for i in add_ids + rem_ids],
                "changes": changes, "notes": notes}

    def whatif_item(self, slot: str, item_text: str | None = None) -> dict:
        self._need_build()
        w = self.pob.whatif(slot=slot, item_raw=item_text)
        w.pop("points", None)
        changes = diff(self.base, w)
        return {"slot": self.pob.resolve_slot(slot), "changes": changes,
                "notes": [] if changes else [self.NO_CHANGE]}

    MAX_GEMS_PER_GROUP = 6  # 1 skill gem + up to 5 support sockets in PoE2

    def _apply_steps(self, steps: list[dict]) -> list[str]:
        notes = []
        for st in steps:
            st = dict(st)
            op = st.pop("op", None)
            if op not in OPS:
                raise ValueError(f"unknown op {op!r}; allowed: {sorted(OPS)}")
            if op in ("alloc_node", "dealloc_node"):
                ref = st.pop("node", None) or st.pop("node_id", None)
                st = {"node_id": self.resolve_node(ref, want_allocated=(op == "dealloc_node"))}
            if op == "set_gem":
                groups = self.pob.groups()
                gi = st.get("group")
                if not gi or gi > len(groups):
                    raise ValueError(f"no skill group {gi}; build_overview lists them")
                g = groups[gi - 1]
                if st.get("gem", 0) > len(g["gems"]) and len(g["gems"]) >= self.MAX_GEMS_PER_GROUP and not g.get("slot"):
                    notes.append(f"group {gi} already has {len(g['gems'])} gems; a PoE2 skill gem has at most 5 support "
                                 f"sockets, so this extra gem is not possible in game")
            res = getattr(self.pob, OPS[op])(**st)
            if res is False or (op == "alloc_node" and res is None):
                notes.append(f"{op} {st} did not apply (wrong name, unreachable node or invalid gem)")
        return notes

    def _points_note(self, before_pts: dict, after_pts: dict) -> dict:
        return {"used": [before_pts["used"], after_pts["used"]], "available": after_pts["available"],
                "weapon_set_1": [before_pts["weapon_set_1"], after_pts["weapon_set_1"]],
                "weapon_set_2": [before_pts["weapon_set_2"], after_pts["weapon_set_2"]]}

    def try_changes(self, steps: list[dict]) -> dict:
        """Apply steps on a copy, report the changes, roll back."""
        self._need_build()
        before_pts = self.pob.points()
        with self.pob.trial():
            notes = self._apply_steps(steps)
            after = self.pob.summary()
            after_pts = self.pob.points()
        changes = diff(self.base, after)
        if not changes:
            notes.append(self.NO_CHANGE)
        res = {"changes": changes, "main_skill": after.get("main_skill"), "notes": notes}
        if before_pts != after_pts:
            res["passive_points"] = self._points_note(before_pts, after_pts)
        return res

    def apply_changes(self, steps: list[dict]) -> dict:
        """Apply steps for real; later comparisons are against the new state."""
        self._need_build()
        before = self.base
        before_pts = self.pob.points()
        notes = self._apply_steps(steps)
        self.base = self.pob.summary()
        res = {"changes": diff(before, self.base), "notes": notes, "build_code": self.pob.export_code()}
        after_pts = self.pob.points()
        if before_pts != after_pts:
            res["passive_points"] = self._points_note(before_pts, after_pts)
        return res

    # ---- ranking -------------------------------------------------------------------
    def rank_passives(self, metric: str = "dps", node_types=("Notable", "Keystone"), max_cost: int = 6,
                      limit: int = 15, also=("dps", "ehp")) -> list[dict]:
        """Every reachable notable/keystone within max_cost points, scored by metric gain per point."""
        self._need_build()
        key = metric_key(metric)
        extra = [metric_key(a) for a in also if metric_key(a) != key]
        rows = []
        for t in node_types:
            for n in self.pob.reachable(t, 2000):
                if n["cost"] > max_cost:
                    continue
                w = self.pob.whatif(add_nodes=[n["id"]], with_path=True)
                gain = w[key] - self.base.get(key, 0)
                rows.append({
                    "node": n["name"], "id": n["id"], "type": t, "points": w["points"],
                    "gain": _r(gain), "gain_pct": round(gain / self.base[key] * 100, 2) if self.base.get(key) else None,
                    "per_point": _r(gain / max(w["points"], 1)),
                    **{f"d_{e}": _r(w[e] - self.base.get(e, 0)) for e in extra},
                })
        rows.sort(key=lambda r: r["per_point"], reverse=True)
        for r in rows[:limit]:
            info = self.pob.node_info(r["id"])
            r["stats"] = info["stats"]
            if info["unsupported"]:
                r["not_calculated"] = info["unsupported"]
        return rows[:limit]

    def rank_respec(self, metric: str = "dps", limit: int = 15, also=("dps", "ehp"),
                    include_inactive_set: bool = True) -> dict:
        """Allocated passives ordered by how little you lose per point if you refund them
        (a node plus everything that only connects through it). Cheapest refunds first."""
        self._need_build()
        key = metric_key(metric)
        extra = [metric_key(a) for a in also if metric_key(a) != key]
        rows, inactive = [], []
        for n in self.pob.allocated_nodes():
            if n.get("ascendancy"):
                continue
            if not n["active"]:
                inactive.append({"node": n["name"], "id": n["id"], "weapon_set": n["weapon_set"]})
                continue
            w = self.pob.whatif(remove_nodes=[n["id"]])
            freed = -w["points"]
            if freed <= 0:
                continue
            loss = self.base.get(key, 0) - w[key]
            row = {"node": n["name"], "id": n["id"], "type": n["type"], "points_freed": freed,
                   "loss": _r(loss), "loss_pct": round(loss / self.base[key] * 100, 2) if self.base.get(key) else None,
                   "loss_per_point": _r(loss / freed),
                   **{f"d_{e}": _r(w[e] - self.base.get(e, 0)) for e in extra}}
            if n["unsupported"]:
                row["not_calculated"] = n["unsupported"]
            rows.append(row)
        # cheapest refunds first; among equal loss, the ones that also cost less on the other metrics
        rows.sort(key=lambda r: (r["loss_per_point"], *[-r[f"d_{e}"] for e in extra]))
        res = {"metric": key, "points": self.pob.points(), "cheapest_refunds": rows[:limit]}
        if include_inactive_set:
            res["inactive_weapon_set_nodes"] = inactive
        return res

    def export_code(self) -> str:
        self._need_build()
        return self.pob.export_code()
