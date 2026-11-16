"""What "better" means for the optimizers.

score = damage_weight * ln(DPS ratio) + survive_weight * ln(EHP ratio), in percent-like units,
minus penalties for things that break a build: resistances falling below what it had (up to the cap),
unmet attribute requirements and over-reserved Spirit. Log ratios make +10% DPS worth the same no
matter how big the build is, and make DPS and EHP trade off multiplicatively.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

RES_CAP = 75


@dataclass
class Objective:
    damage: float = 1.0
    survive: float = 1.0
    speed: float = 1.0            # movement speed (mapping comfort); 0 to ignore
    dps_key: str = "MainDPS"            # own DPS, or minion DPS for minion main skills
    ehp_key: str = "TotalEHP"
    speed_key: str = "MovementSpeedMod"
    res_penalty: float = 2.0      # per resistance point lost below min(before, cap)
    attr_penalty: float = 50.0    # flat, per attribute with an unmet requirement
    spirit_penalty: float = 50.0  # flat, if Spirit becomes over-reserved
    extra: dict | None = None     # more stats in the goal, {stat key: weight}, e.g. projectiles for clear speed

    @classmethod
    def from_goals(cls, goals: dict | None) -> "Objective":
        g = goals or {}
        return cls(damage=float(g.get("damage", 1)), survive=float(g.get("survive", 1)),
                   speed=float(g.get("speed", 1)))

    def _ratio(self, after: float, before: float) -> float:
        if before <= 0:
            return 0.0 if after <= 0 else 1.0  # from nothing to something: count as a big win
        return math.log(max(after, 1e-9) / before)

    def score(self, after: dict, base: dict) -> float:
        """Improvement of `after` over `base`; 0 = same, ~1 = +1% on a weight-1 goal."""
        s = 100 * (self.damage * self._ratio(after.get(self.dps_key, 0), base.get(self.dps_key, 0))
                   + self.survive * self._ratio(after.get(self.ehp_key, 0), base.get(self.ehp_key, 0)))
        if self.speed and base.get(self.speed_key):
            s += 100 * self.speed * self._ratio(after.get(self.speed_key, 0), base[self.speed_key])
        for key, weight in (self.extra or {}).items():
            if base.get(key):
                s += 100 * weight * self._ratio(after.get(key, 0), base[key])
        return s - self.penalty(after, base)

    def penalty(self, after: dict, base: dict) -> float:
        p = 0.0
        for e in ("Fire", "Cold", "Lightning", "Chaos"):
            floor = min(base.get(f"{e}Resist", 0), RES_CAP)
            lost = floor - after.get(f"{e}Resist", 0)
            if lost > 0:
                p += self.res_penalty * lost
        for k in ("Str", "Dex", "Int"):
            if after.get(f"Req{k}", 0) > after.get(k, 0) and not base.get(f"Req{k}", 0) > base.get(k, 0):
                p += self.attr_penalty
        if after.get("SpiritUnreserved", 0) < 0 <= base.get("SpiritUnreserved", 0):
            p += self.spirit_penalty
        return p

    def explain(self, after: dict, base: dict) -> dict:
        def pct(k):
            b = base.get(k, 0)
            return round((after.get(k, 0) - b) / b * 100, 2) if b else None
        res = {"score": round(self.score(after, base), 2), "dps_pct": pct(self.dps_key),
               "ehp_pct": pct(self.ehp_key), "penalty": round(self.penalty(after, base), 2)}
        ms = pct(self.speed_key)
        if ms:
            res["move_speed_pct"] = ms
        for key in self.extra or {}:
            v = pct(key)
            if v:
                res[f"{key}_pct"] = v
        return res
