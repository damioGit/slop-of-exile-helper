"""Launch-day update: one command from "PoB released new data" to "helper uses it".

    soe update            latest PoB release
    soe update v1.0.0     a given tag
    soe compare v0.22.0 v0.23.1   patch report between two versions (does not touch the current setup)

Steps of `update`:
1. find the tag (latest GitHub release unless given)
2. download it into vendor/ (old copy kept until the new one is complete)
3. engine check: boot PoB and calculate every build in tests/builds; on failure go back to the old version
4. build a new knowledge base and make it current
5. write a patch report (old vs new knowledge base) to data/patch-<old>-<new>.md and .json
6. pin the version in POB_VERSION
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_pob import DEST, fetch  # noqa: E402

from soe.kb.build import DATA_DIR, build, current_db_path  # noqa: E402
from soe.pipeline.diff import diff_kb, report_md  # noqa: E402

REPO_API = "https://api.github.com/repos/PathOfBuildingCommunity/PathOfBuilding-PoE2/releases/latest"
BUILDS = ROOT / "tests" / "builds"


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def latest_tag() -> str:
    req = urllib.request.Request(REPO_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "soe-update"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())["tag_name"]


def engine_check(pob_dir: Path = DEST) -> dict:
    """Boot PoB from pob_dir and calculate every reference build."""
    from soe.engine.pob import PoB

    res = {"ok": True, "builds": {}}
    t = time.perf_counter()
    try:
        pob = PoB(pob_dir)
    except Exception as e:
        return {"ok": False, "error": f"boot failed: {type(e).__name__}: {e}"}
    res["boot_seconds"] = round(time.perf_counter() - t, 1)
    for f in sorted(BUILDS.glob("*.txt")):
        try:
            pob.load_code(f.read_text(encoding="utf-8"))
            s = pob.summary()
            ok = (s.get("Life") or 0) > 0 and (s.get("CombinedDPS") or 0) > 0
            res["builds"][f.stem] = {"ok": ok, "main_skill": s.get("main_skill"), "dps": round(s.get("CombinedDPS") or 0),
                                     "ehp": round(s.get("TotalEHP") or 0)}
            res["ok"] &= ok
        except Exception as e:
            res["builds"][f.stem] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            res["ok"] = False
    return res


def _write_report(d: dict, name: str) -> tuple[Path, Path]:
    md, js = DATA_DIR / f"patch-{name}.md", DATA_DIR / f"patch-{name}.json"
    md.write_text(report_md(d), encoding="utf-8")
    js.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")
    return md, js


def update(tag: str | None = None, pin: bool = True) -> dict:
    t0 = time.perf_counter()
    old_tag = (ROOT / "POB_VERSION").read_text().strip()
    tag = tag or latest_tag()
    log(f"PoB: {old_tag} -> {tag}")
    old_kb = current_db_path()
    old_check = engine_check() if DEST.exists() else None

    fetch(tag)
    log("engine check on reference builds")
    check = engine_check()
    if not check["ok"]:
        log(f"engine check FAILED, going back to {old_tag}: {json.dumps(check)[:500]}")
        fetch(old_tag)
        return {"ok": False, "tag": tag, "engine_check": check, "rolled_back_to": old_tag}

    log("building knowledge base")
    info = build()
    report = None
    if old_kb.exists() and Path(info["path"]) != old_kb:
        d = diff_kb(old_kb, Path(info["path"]))
        md, _ = _write_report(d, f"{old_tag}-{tag}")
        report = {"path": str(md), "counts": d["counts"]}
        log(f"patch report: {md}")
    if pin:
        (ROOT / "POB_VERSION").write_text(tag + "\n")
    changes = {}
    if old_check:
        for k, v in check["builds"].items():
            o = old_check.get("builds", {}).get(k)
            if o and o.get("dps"):
                changes[k] = {"dps": [o["dps"], v["dps"], round((v["dps"] - o["dps"]) / o["dps"] * 100, 1)],
                              "ehp": [o["ehp"], v["ehp"]]}
    return {"ok": True, "from": old_tag, "to": tag, "engine_check": check, "reference_builds_change": changes,
            "kb": info, "report": report, "seconds": round(time.perf_counter() - t0, 1),
            "next": "Restart running MCP servers / web app so they load the new PoB and knowledge base; "
                    "run the tests (python -m pytest); re-check builds whose numbers moved a lot."}


def compare(old_tag: str, new_tag: str) -> dict:
    """Patch report between two PoB versions, without touching the current setup."""
    out = {}
    paths = {}
    for tag in (old_tag, new_tag):
        dest = ROOT / "vendor" / f"pob-{tag}"
        fetch(tag, dest)
        check = engine_check(dest)
        out[tag] = {"engine_check": check}
        kb = DATA_DIR / f"kb-compare-{tag}.sqlite"
        kb.unlink(missing_ok=True)
        log(f"knowledge base for {tag}")
        info = build(kb, pob_version=tag, pob_dir=dest)
        out[tag]["kb"] = {k: info[k] for k in ("gems", "mods", "uniques", "nodes", "tree_version")}
        paths[tag] = kb
    d = diff_kb(paths[old_tag], paths[new_tag])
    md, _ = _write_report(d, f"{old_tag}-{new_tag}")
    return {"report": str(md), "counts": d["counts"], **out}


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--no-pin", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(update(a.tag, pin=not a.no_pin), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
