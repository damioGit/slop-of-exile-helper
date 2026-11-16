"""Manual check of the phase 1 API on the Spirit Walker reference build."""
import json
import sys
import time

sys.path.insert(0, ".")
from soe.engine.pob import PoB  # noqa: E402

p = PoB()
p.load_code(open("tests/builds/spirit_walker.txt", encoding="utf-8").read())
base = p.summary()
print("base DPS", round(base["TotalDPS"]), "EHP", round(base["TotalEHP"]))

t = time.perf_counter()
dps = p.all_skill_dps()
print(f"all_skill_dps {time.perf_counter() - t:.2f}s")
for d in dps:
    print(f"  g{d['group']:>2} {d['name']:<28} {d['TotalDPS']:>12.0f}  dot {d['TotalDotDPS']:.0f}  minion {d['MinionDPS']:.0f}")
print("main after restore:", p.summary()["main_skill"], round(p.summary()["TotalDPS"]))

print("\nGROUPS")
for g in p.groups():
    print(f"  {g['index']:>2} main={g['main']!s:5} {g.get('slot')!s:12} skills={g['skills']} gems={[x['name'] for x in g['gems']]}")

print("\nITEMS")
for it in p.items():
    print(f"  {it['slot']:<14} {it['rarity']:<7} {it['name']}")

cand = p.reachable("Notable", 8)
t = time.perf_counter()
for c in cand:
    w = p.whatif(add_nodes=[c["id"]], with_path=True)
    print(f"  +{c['name']:<30} pts {w['points']}  dDPS {w['TotalDPS'] - base['TotalDPS']:>+10.0f}  dEHP {w['TotalEHP'] - base['TotalEHP']:>+8.0f}")
n = len(cand)
print(f"whatif nodes {n / (time.perf_counter() - t):.1f}/s")

items = p.items()
weapon = next(i for i in items if i["slot"] == "Weapon 1")
t = time.perf_counter()
w = p.whatif(slot="Weapon 1")
print(f"\nwithout weapon: DPS {w['TotalDPS']:.0f} ({time.perf_counter() - t:.3f}s)")
w = p.whatif(slot="Weapon 1", item_raw=weapon["raw"])
print(f"same weapon again: DPS {w['TotalDPS']:.0f} (base {base['TotalDPS']:.0f})")

t = time.perf_counter()
snap = p.snapshot()
t1 = time.perf_counter()
p.restore(snap)
t2 = time.perf_counter()
print(f"\nsnapshot {t1 - t:.3f}s restore {t2 - t1:.3f}s, same after restore: {p.summary() == base}")

opts = {o["var"]: o for o in p.config_options()}
print("config options:", len(opts), "enemyIsBoss =", opts["enemyIsBoss"]["value"], opts["enemyIsBoss"]["choices"])
with p.trial():
    p.set_config("enemyIsBoss", "None")
    print("vs non-boss DPS", round(p.summary()["TotalDPS"]))
print("after trial DPS", round(p.summary()["TotalDPS"]))
print(json.dumps(p.groups()[0], indent=1)[:600])
