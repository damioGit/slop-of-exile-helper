import json
import sys
import time

sys.path.insert(0, ".")
from soe.engine.pob import PoB  # noqa: E402
from tests.fixtures_synthetic import make_sorc  # noqa: E402

p = PoB()
print(f"boot {p.boot_seconds:.1f}s")
t = time.perf_counter()
spent = make_sorc(p)
print(f"assemble {time.perf_counter() - t:.2f}s, points {spent}")
s1 = p.summary()
print(json.dumps(s1, indent=1))
code = p.export_code()
print("code len", len(code))
q = PoB()
q.load_code(code)
s2 = q.summary()
diff = {k: (s1[k], s2.get(k)) for k in s1 if s1[k] != s2.get(k)}
print("roundtrip diff:", diff or "NONE")
t = time.perf_counter()
n = 30
for _ in range(n):
    p.recalc()
print(f"recalc {n / (time.perf_counter() - t):.1f}/s")
