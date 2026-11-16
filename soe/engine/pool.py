"""Many PoB instances in parallel: one process per instance, all loaded with the same build.

Jobs are plain dicts so they cross process boundaries:
    {"call": "whatif", "kwargs": {...}}                     -> any PoB method, result returned as is
    {"trial": [["set_gem", {...}], ["equip", {...}]]}       -> apply steps, return summary(), roll back
    {"trial": [...], "then": "all_skill_dps"}               -> same, but return another method's result

Usage:
    with PoBPool(build_code) as pool:
        results = pool.run([{"call": "whatif", "kwargs": {"add_nodes": [123], "with_path": True}}, ...])
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor

_pob = None  # per-process instance


def _init(xml: str):
    global _pob
    from soe.engine.pob import PoB

    _pob = PoB()
    _pob.load_xml(xml)


def _run(job: dict):
    try:
        if "call" in job:
            return {"ok": True, "result": getattr(_pob, job["call"])(**job.get("kwargs", {}))}
        with _pob.trial():
            for name, kwargs in job["trial"]:
                getattr(_pob, name)(**kwargs)
            then = job.get("then", "summary")
            return {"ok": True, "result": getattr(_pob, then)()}
    except Exception as e:  # one bad job must not kill the batch
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


class PoBPool:
    def __init__(self, build_code: str | None = None, *, xml: str | None = None, workers: int | None = None):
        from soe.engine.pob import decode_build_code

        if xml is None:
            if build_code is None:
                raise ValueError("give build_code or xml")
            xml = decode_build_code(build_code)
        self.workers = workers or max(1, (os.cpu_count() or 2) - 1)
        self._ex = ProcessPoolExecutor(max_workers=self.workers, initializer=_init, initargs=(xml,))
        # boot every worker now, so the first real batch is not slowed down by startup
        list(self._ex.map(_run, [{"call": "recalc"}] * self.workers))

    def run(self, jobs: list[dict], chunksize: int = 4) -> list[dict]:
        """Run jobs in parallel; results come back in the same order: {"ok", "result"} or {"ok": False, "error"}."""
        return list(self._ex.map(_run, jobs, chunksize=chunksize))

    def close(self):
        self._ex.shutdown(cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
