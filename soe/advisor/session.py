"""Advisor session: one loaded build plus the knowledge base, with answers shaped for an LLM.

Everything returns plain JSON-able dicts. Numbers come from PoB; nothing here guesses.
"""
from __future__ import annotations

import threading
from pathlib import Path

from soe.engine.pob import PoB, SUMMARY_KEYS

METRICS = {
    "dps": "CombinedDPS", "hit_dps": "TotalDPS", "ehp": "TotalEHP", "life": "Life", "es": "EnergyShield",
    "mana": "Mana", "evasion": "Evasion", "armour": "Armour", "speed": "Speed",
    "phys_max_hit": "PhysicalMaximumHitTaken", "chaos_max_hit": "ChaosMaximumHitTaken",
    "movement": "MovementSpeedMod",
}

# operations allowed in try_changes / apply_changes, mapped to PoB methods
OPS = {
    "set_gem": "set_gem", "remove_gem": "remove_gem", "set_main_skill": "set_main_skill",
    "equip": "equip", "unequip": "unequip", "set_config": "set_config", "set_level": "set_level",
    "alloc_node": "alloc_node", "dealloc_node": "dealloc_node", "paste_gems": "paste_gems",
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
    def load(self, build: str, name: str = "build") -> dict:
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
                                                  "useEnduranceCharges", "conditionEnemyShocked", "conditionEnemyIgnited")}
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

    # ---- what-if (no change to the build) ------------------------------------------
    def whatif_passives(self, add=None, remove=None) -> dict:
        self._need_build()
        add_ids = [self.resolve_node(x, want_allocated=False) for x in (add or [])]
        rem_ids = [self.resolve_node(x, want_allocated=True) for x in (remove or [])]
        w = self.pob.whatif(add_nodes=add_ids or None, with_path=True, remove_nodes=rem_ids or None)
        return {"points": w.pop("points"),
                "nodes": [self.pob.node_info(i)["name"] for i in add_ids + rem_ids],
                "changes": diff(self.base, w)}

    def whatif_item(self, slot: str, item_text: str | None = None) -> dict:
        self._need_build()
        w = self.pob.whatif(slot=slot, item_raw=item_text)
        w.pop("points", None)
        return {"slot": self.pob.resolve_slot(slot), "changes": diff(self.base, w)}

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
            res = getattr(self.pob, OPS[op])(**st)
            if res is False or (op == "alloc_node" and res is None):
                notes.append(f"{op} {st} did not apply")
        return notes

    def try_changes(self, steps: list[dict]) -> dict:
        """Apply steps on a copy, report the changes, roll back."""
        self._need_build()
        with self.pob.trial():
            notes = self._apply_steps(steps)
            after = self.pob.summary()
        return {"changes": diff(self.base, after), "main_skill": after.get("main_skill"), "notes": notes}

    def apply_changes(self, steps: list[dict]) -> dict:
        """Apply steps for real; later comparisons are against the new state."""
        self._need_build()
        before = self.base
        notes = self._apply_steps(steps)
        self.base = self.pob.summary()
        return {"changes": diff(before, self.base), "notes": notes, "build_code": self.pob.export_code()}

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
            r["stats"] = self.pob.node_info(r["id"])["stats"]
        return rows[:limit]

    def export_code(self) -> str:
        self._need_build()
        return self.pob.export_code()
