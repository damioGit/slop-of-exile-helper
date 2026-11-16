"""Run every advisor tool on every character in data/corpus/ and compare numbers with poe.ninja.

python scripts/run_corpus.py [--quick] [--only NAME]
Writes data/corpus_report.json and data/corpus_report.md. --quick skips the slow optimizers.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CORPUS = ROOT / "data" / "corpus"

# poe.ninja defensiveStats key -> our summary key
COMPARE = {
    "life": "Life", "energyShield": "EnergyShield", "mana": "Mana", "spirit": "Spirit",
    "evasionRating": "Evasion", "armour": "Armour", "evadeChance": "EvadeChance", "deflectChance": "DeflectChance",
    "strength": "Str", "dexterity": "Dex", "intelligence": "Int",
    "fireResistance": "FireResist", "coldResistance": "ColdResist", "lightningResistance": "LightningResist",
    "chaosResistance": "ChaosResist", "effectiveHealthPool": "TotalEHP",
    "physicalMaximumHitTaken": "PhysicalMaximumHitTaken", "fireMaximumHitTaken": "FireMaximumHitTaken",
}


def close(a, b, rel=0.02, abs_=1.5) -> bool:
    if a is None or b is None:
        return True
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


def run_one(path: Path, quick: bool) -> dict:
    from soe.advisor.checkup import run_checkup
    from soe.advisor.session import Session
    from soe.combo.mechanics import suggest_combos
    from soe.items.craft import ideal_item, mod_upgrades
    from soe.items.uniques import rank_uniques
    from soe.optimize.objective import Objective
    from soe.optimize.plan import improvement_plan
    from soe.optimize.stat_weights import stat_weights
    from soe.optimize.supports import optimize_supports
    from soe.optimize.tree import optimize_tree

    rec = json.loads(path.read_text(encoding="utf-8"))
    out = {"file": path.name, "class": rec["class"], "name": rec["name"], "level": rec["level"],
           "league": rec.get("league"), "tools": {}, "errors": {}, "mismatch": {}}
    s = Session()
    s.pool_workers = 6

    def tool(name, fn):
        t = time.perf_counter()
        try:
            res = fn()
            out["tools"][name] = round(time.perf_counter() - t, 2)
            return res
        except Exception as e:
            out["errors"][name] = f"{type(e).__name__}: {e}"
            out["tools"][name] = None
            out.setdefault("tracebacks", {})[name] = traceback.format_exc()[-1500:]
            return None

    base = tool("load", lambda: s.load(rec["code"], rec["name"]))
    if base is None:
        return out
    out["main_skill"] = base.get("main_skill")
    out["dps"] = round(base.get("MainDPS") or 0)
    out["minion_main"] = not base.get("CombinedDPS") and bool(base.get("MinionDPS"))

    # numbers vs poe.ninja
    from soe.engine.pob import IMMUNE

    nd = rec.get("ninja_defensive") or {}
    for nk, ok in COMPARE.items():
        if nk in nd and ok in base and not close(nd[nk], base[ok]):
            if nk.endswith("MaximumHitTaken") and nd[nk] > 1e9:
                continue
            if ok == "ChaosResist" and base.get("ChaosMaximumHitTaken", 0) >= IMMUNE:
                continue  # chaos immune: ninja shows 100%, PoB keeps the resistance number
            out["mismatch"][ok] = [nd[nk], round(base[ok], 1)]
    ninja_skills = [x for x in rec.get("ninja_skills") or [] if x.get("dps")]
    ours = tool("all_skill_dps", s.pob.all_skill_dps) or []
    # poe.ninja splits hit DPS (`dps`, minions included) and damage over time (`dotDps`)
    hits, dots = {}, {}
    for d in ours:
        key = d.get("base_name") or d["name"]
        hits.setdefault(key, []).append(max(d["TotalDPS"], d.get("MinionDPS") or 0))
        dots.setdefault(key, []).append(d.get("TotalDotDPS") or 0)
    matched, unmatched = 0, []
    for n in ninja_skills:
        h = hits.get(n["name"])
        if h:
            ok_hit = any(close(n["dps"], v, rel=0.03, abs_=50) for v in h)
            ok_dot = not n.get("dotDps") or any(close(n["dotDps"], v, rel=0.03, abs_=50) for v in dots[n["name"]])
            if ok_hit and ok_dot:
                matched += 1
            else:
                out["mismatch"][f"dps:{n['name']}"] = [[n["dps"], n.get("dotDps")], [round(max(h)), round(max(dots[n["name"]]))]]
        elif any(close(n["dps"], v, rel=0.01, abs_=5) for vs in hits.values() for v in vs):
            matched += 1  # same number under another name (minion skill vs its summon gem)
        else:
            unmatched.append(f"{n['name']} {n['dps']:.0f}")
    out["ninja_skills_matched"] = matched
    out["ninja_skills_unmatched"] = unmatched[:8]

    obj = Objective()
    tool("overview", lambda: s.overview(with_all_skills=False))
    ck = tool("checkup", lambda: run_checkup(s))
    if ck:
        out["checkup"] = [f["id"] for f in ck["findings"]]
    tool("rank_passives", lambda: s.rank_passives("dps", ("Notable", "Keystone"), 6, 10))
    tool("rank_respec", lambda: s.rank_respec("dps", 10))
    tool("stat_weights", lambda: stat_weights(s.pob, s.base, obj))
    for it in s.pob.items(active_only=True):
        slot = it["slot"]
        if slot.startswith(("Flask", "Charm")):
            continue
        tool(f"mod_upgrades:{slot}", lambda slot=slot: mod_upgrades(s, slot, obj, 3))
        tool(f"rank_uniques:{slot}", lambda slot=slot: rank_uniques(s, slot, obj, 3))
    ring = next((i["slot"] for i in s.pob.items(active_only=True) if i["slot"].startswith("Ring")), None)
    if ring:
        tool("ideal_item", lambda: ideal_item(s, ring, obj))
    tool("try_changes", lambda: s.try_changes([{"op": "set_config", "var": "enemyIsBoss", "value": "None"}]))
    if not quick:
        tool("suggest_combos", lambda: suggest_combos(s, obj))
        tree = tool("optimize_tree", lambda: optimize_tree(s, obj, max_moves=3))
        if tree:
            out["tree_gain"] = tree["total"]
        sup = tool("optimize_supports", lambda: optimize_supports(s, objective=obj))
        if sup and sup.get("best_combination"):
            out["support_gain"] = {k: sup["best_combination"][k] for k in ("dps_pct", "ehp_pct")}
    out["unchanged_after_tools"] = s.pob.summary() == s.base
    s.close_pool()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    files = sorted(CORPUS.glob("*.json"))
    if a.only:
        files = [f for f in files if a.only.lower() in f.name.lower()]
    results = []
    for f in files:
        t = time.perf_counter()
        r = run_one(f, a.quick)
        r["seconds"] = round(time.perf_counter() - t, 1)
        results.append(r)
        print(f"{r['class']:<22} {r['name'][:24]:<24} {r.get('main_skill') or '-':<24} errors={len(r['errors'])} "
              f"mismatch={len(r['mismatch'])} {r['seconds']}s", flush=True)
    (ROOT / "data" / "corpus_report.json").write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    lines = ["# Corpus run", "", "| Ascendancy | Character | Main skill | DPS | Errors | Mismatches vs poe.ninja |",
             "|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['class']} | {r['name']} | {r.get('main_skill')} | {r.get('dps', '-')} | "
                     f"{'; '.join(f'{k}: {v}' for k, v in r['errors'].items()) or '-'} | "
                     f"{'; '.join(f'{k} ninja {v[0]} / ours {v[1]}' for k, v in r['mismatch'].items()) or '-'} |")
    (ROOT / "data" / "corpus_report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(results)} characters, {sum(bool(r['errors']) for r in results)} with errors, "
          f"{sum(bool(r['mismatch']) for r in results)} with mismatches")


if __name__ == "__main__":
    main()
