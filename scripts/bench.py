"""Throughput of what-if passive node evaluations: one instance vs a process pool.

python scripts/bench.py [build file] [workers]
"""
import os
import sys
import time

sys.path.insert(0, ".")
from soe.engine.pob import PoB  # noqa: E402
from soe.engine.pool import PoBPool  # noqa: E402


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "tests/builds/spirit_walker.txt"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else max(1, (os.cpu_count() or 2) - 1)
    code = open(path, encoding="utf-8").read()

    p = PoB()
    p.load_code(code)
    nodes = [n["id"] for n in p.reachable("Notable", 400) + p.reachable("Normal", 400)]
    print(f"{len(nodes)} reachable nodes, cpu {os.cpu_count()}")

    t = time.perf_counter()
    for n in nodes[:100]:
        p.whatif(add_nodes=[n], with_path=True)
    single = 100 / (time.perf_counter() - t)
    print(f"single instance: {single:.0f} what-if/s")

    t = time.perf_counter()
    pool = PoBPool(code, workers=workers)
    print(f"pool of {workers} booted in {time.perf_counter() - t:.1f}s")
    jobs = [{"call": "whatif", "kwargs": {"add_nodes": [n], "with_path": True}} for n in nodes]
    t = time.perf_counter()
    res = pool.run(jobs, chunksize=16)
    dt = time.perf_counter() - t
    pool.close()
    bad = [r for r in res if not r["ok"]]
    print(f"pool: {len(jobs) / dt:.0f} what-if/s ({len(jobs)} jobs in {dt:.1f}s), errors {len(bad)}")
    if bad:
        print(bad[0])


if __name__ == "__main__":
    main()
