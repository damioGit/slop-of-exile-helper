"""Local web app: the same advisor session as the MCP server, behind a small JSON API and one page.

Run: soe web   (http://127.0.0.1:8765)
Single user, local only. Long calls (support optimizer, plan) block for their duration.
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from soe.advisor.session import Session

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Slop of Exile Helper", docs_url="/api/docs", redoc_url=None)
session = Session(os.environ.get("SOE_KB") or None)
# the build the player worked on last; loaded again on start, so a restart never swaps or loses it
LAST = Path(os.environ.get("SOE_LAST_BUILD") or Path(__file__).resolve().parents[2] / "data" / "user" / "last_session.json")


def _save_last():
    if not session.loaded:
        return
    try:
        LAST.parent.mkdir(parents=True, exist_ok=True)
        LAST.write_text(json.dumps({"code": session.export_code(), "name": session.name, "source": session.source,
                                    "original_code": session.original_code}), encoding="utf-8")
    except Exception:
        traceback.print_exc()


def _restore_last():
    if not LAST.exists():
        return
    try:
        d = json.loads(LAST.read_text(encoding="utf-8"))
        with session.lock:
            session.load(d["original_code"] or d["code"], d.get("name") or "build")
            if d.get("code") and d.get("code") != d.get("original_code"):  # changes the player applied
                session.pob.load_code(d["code"], session.name)
                session.base = session.pob.summary()
            session.source = d.get("source")
    except Exception:
        traceback.print_exc()


@app.middleware("http")
async def _build_header(request: Request, call_next):
    """Every answer says which build it was computed on; the page compares it with the build it shows."""
    resp = await call_next(request)
    if session.build_id:
        resp.headers["X-SOE-Build"] = session.build_id
    return resp


@app.exception_handler(Exception)
async def _errors(request: Request, exc: Exception):
    traceback.print_exc()
    return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, status_code=400)


def _goals(damage: float = 1, survive: float = 1, speed: float = 1):
    from soe.optimize.objective import Objective

    return Objective.from_goals({"damage": damage, "survive": survive, "speed": speed})


def locked(fn, *a, **kw):
    with session.lock:
        return fn(*a, **kw)


def _saved(result):
    with session.lock:
        _save_last()
    return result


@app.get("/")
def index():
    # no-cache: after an update the browser checks for the new page instead of showing the old one
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/status")
def status():
    meta = {}
    try:
        meta = session.kb.meta()
    except Exception as e:  # KB not built yet
        meta = {"error": str(e)}
    return {"loaded": session.loaded, "name": session.name, "kb": meta, "source": session.source,
            "build_id": session.build_id, "summary": session.base if session.loaded else None,
            "poe2db": __import__("soe.kb.poe2db", fromlist=["status"]).status()}


@app.post("/api/load")
def load(payload: dict = Body(...)):
    return _saved(locked(session.load, payload["code"], payload.get("name") or "build"))


@app.post("/api/ask")
def ask(payload: dict = Body(...)):
    from soe.advisor.assistant import ask as run

    return locked(run, session, payload.get("question") or "", payload.get("skill") or None,
                  payload.get("goal") or None, payload.get("budget"))


@app.post("/api/find_upgrade")
def find_upgrade(payload: dict = Body(...)):
    from soe.prices.trade import find_upgrade as run

    return locked(run, session, payload["slot"], payload.get("wanted") or None, payload.get("budget"),
                  _goals(payload.get("damage", 1), payload.get("survive", 1), payload.get("speed", 1)))


@app.post("/api/ai")
def ai_start(payload: dict = Body(...)):
    """Ask Claude (with the soe tools) about the build open in the app; poll /api/ai/{id}."""
    from soe.web.ai import jobs

    def run():
        session._need_build()
        return jobs.start(payload.get("question") or "", session.export_code(), session.base, payload.get("resume"))
    return locked(run)


@app.get("/api/ai/{job_id}")
def ai_poll(job_id: str):
    from soe.web.ai import jobs

    return jobs.view(job_id)


@app.get("/api/skills")
def skills():
    from soe.advisor.assistant import _skill_list

    return locked(lambda: _skill_list(session.pob))


@app.post("/api/main_skill")
def main_skill(payload: dict = Body(...)):
    return _saved(locked(session.apply_changes, [{"op": "set_main_skill", "group": payload["group"], "skill": payload["skill"]}]))


_TREE_CACHE: dict = {}


@app.get("/api/tree")
def tree():
    """Passive tree geometry (from the knowledge base) + what this build has allocated."""
    def build():
        asc = session.base.get("ascendancy")
        key = (session.kb.meta().get("built_at"), asc)
        if key not in _TREE_CACHE:
            nodes = session.kb._rows("SELECT id, name, type, ascendancy, stats, linked, x, y FROM nodes")
            _TREE_CACHE.clear()
            _TREE_CACHE[key] = [n for n in nodes if n["x"] is not None and (not n["ascendancy"] or n["ascendancy"] == asc)
                                and n["type"] not in ("ClassStart",)]
        alloc = {n["id"]: n["weapon_set"] for n in session.pob.allocated_nodes()}
        return {"nodes": _TREE_CACHE[key], "allocated": alloc,
                "active_weapon_set": session.pob.points()["active_weapon_set"]}
    return locked(build)


@app.get("/api/node_path")
def node_path(id: int):
    def run():
        info = session.pob.node_info(id)
        return {"path": session.pob.node_path(id), "node": info}
    return locked(run)


@app.post("/api/import")
def import_character(payload: dict = Body(...)):
    return _saved(locked(session.import_character, payload["ref"], payload.get("name") or None))


@app.post("/api/resync")
def resync():
    return _saved(locked(session.resync))


@app.post("/api/reset")
def reset():
    return _saved(locked(session.reset))


@app.get("/api/export")
def export():
    return {"code": locked(session.export_code)}


@app.get("/api/overview")
def overview(all_skills: bool = True):
    return locked(session.overview, all_skills)


@app.get("/api/item")
def item(slot: str):
    return locked(session.item, slot)


@app.get("/api/config")
def config(search: str | None = None, only_set: bool = True):
    return locked(session.config, search, only_set)


@app.get("/api/checkup")
def checkup(damage: float = 2, survive: float = 2, mana: float = 1, ease: float = 1, speed: float = 1,
            deep: bool = True):
    from soe.advisor.checkup import run_checkup

    return locked(run_checkup, session, {"damage": damage, "survive": survive, "mana": mana, "ease": ease,
                                         "speed": speed}, deep)


@app.get("/api/stat_weights")
def stat_weights(damage: float = 1, survive: float = 1, speed: float = 1):
    from soe.optimize.stat_weights import stat_weights as sw

    return locked(lambda: sw(session.pob, session.base, _goals(damage, survive, speed)))


@app.get("/api/rank_passives")
def rank_passives(metric: str = "dps", max_cost: int = 6, limit: int = 15):
    return locked(session.rank_passives, metric, ("Notable", "Keystone"), max_cost, limit)


@app.get("/api/rank_respec")
def rank_respec(metric: str = "dps", limit: int = 15):
    return locked(session.rank_respec, metric, limit)


@app.post("/api/whatif_passives")
def whatif_passives(payload: dict = Body(...)):
    return locked(session.whatif_passives, payload.get("add"), payload.get("remove"))


@app.post("/api/whatif_item")
def whatif_item(payload: dict = Body(...)):
    return locked(session.whatif_item, payload["slot"], payload.get("item_text"))


@app.post("/api/try")
def try_changes(payload: dict = Body(...)):
    return locked(session.try_changes, payload["steps"])


@app.post("/api/apply")
def apply_changes(payload: dict = Body(...)):
    return _saved(locked(session.apply_changes, payload["steps"]))


@app.get("/api/optimize_supports")
def optimize_supports(group: int | None = None, damage: float = 1, survive: float = 1, speed: float = 1,
                      budget: float | None = None):
    from soe.optimize.supports import optimize_supports as opt

    return locked(opt, session, group, _goals(damage, survive, speed), budget_divine=budget)


@app.get("/api/optimize_tree")
def optimize_tree(damage: float = 1, survive: float = 1, speed: float = 1, max_moves: int = 6):
    from soe.optimize.tree import optimize_tree as opt

    return locked(opt, session, _goals(damage, survive, speed), max_moves)


@app.get("/api/plan")
def plan(damage: float = 1, survive: float = 1, speed: float = 1, top: int = 12, budget: float | None = None):
    from soe.optimize.plan import improvement_plan

    return locked(improvement_plan, session, {"damage": damage, "survive": survive, "speed": speed}, top=top,
                  budget_divine=budget)


@app.get("/api/uniques")
def uniques(slot: str, damage: float = 1, survive: float = 1, limit: int = 15):
    from soe.items.uniques import rank_uniques

    return locked(rank_uniques, session, slot, _goals(damage, survive), limit)


@app.get("/api/try_unique")
def try_unique(name: str, slot: str | None = None, damage: float = 1, survive: float = 1):
    from soe.items.uniques import try_unique as tu

    return locked(tu, session, name, slot, _goals(damage, survive))


@app.get("/api/mod_upgrades")
def mod_upgrades(slot: str, damage: float = 1, survive: float = 1, limit: int = 8):
    from soe.items.craft import mod_upgrades as mu

    return locked(mu, session, slot, _goals(damage, survive), limit)


@app.get("/api/gear_audit")
def gear_audit(damage: float = 1, survive: float = 1):
    from soe.items.gear import gear_audit as ga

    return locked(ga, session, _goals(damage, survive))


@app.get("/api/item_analysis")
def item_analysis(slot: str, damage: float = 1, survive: float = 1):
    from soe.items.gear import item_analysis as ia

    return locked(ia, session, slot, _goals(damage, survive))


@app.get("/api/skill_groups")
def skill_groups():
    """Socket groups with every gem's game text (description, stats at its level cap, tags, requirements)
    and why a support does nothing when it does not apply."""
    from soe.advisor.assistant import explain_not_applied

    def run():
        session._need_build()
        dps = {}
        for d in session.skill_dps():
            k = (d.get("group"), d.get("base_name") or d.get("name"))
            dps[k] = max(dps.get(k, 0), d.get("TotalDPS") or 0, d.get("MinionDPS") or 0, d.get("TotalDotDPS") or 0)
        out = []
        for g in session.pob.groups():
            if not g.get("gems"):
                continue
            gems = []
            for x in g["gems"]:
                kb = session.kb.gem(x["name"]) or {}
                gems.append({**{k: x.get(k) for k in ("name", "support", "level", "quality", "enabled", "applies")},
                             "why_not": explain_not_applied(x["not_applied"]) if x.get("not_applied") else None,
                             "description": kb.get("description"), "stats": kb.get("stats_text") or [],
                             "tags": kb.get("tag_string"), "max_level": kb.get("max_level"),
                             "req": {a: kb.get(f"req_{a}") for a in ("str", "dex", "int") if kb.get(f"req_{a}")}})
            out.append({"index": g["index"], "main": g.get("main"), "enabled": g.get("enabled"), "label": g.get("label"),
                        "skills": g.get("skills") or [], "slot": g.get("slot"), "gems": gems,
                        "dps": max([v for (gi, _), v in dps.items() if gi == g["index"]] or [0])})
        return {"groups": out}
    return locked(run)


@app.get("/api/craft_plan")
def craft_plan(slot: str, damage: float = 1, survive: float = 1):
    from soe.items.craftplan import craft_plan as cp

    return locked(cp, session, slot, _goals(damage, survive))


# Crafting tab: KB only (no build, no PoB lock), works before a build is loaded.
@app.get("/api/craft/bases")
def craft_bases(type: str | None = None, q: str | None = None):
    from soe.items.crafter import CRAFT_TYPES, craft_bases as run

    return {"types": list(CRAFT_TYPES), "bases": run(session.kb, type, q)}


@app.get("/api/craft/pool")
def craft_pool(base: str, ilvl: int = 82):
    from soe.items.crafter import craft_pool as run

    return run(session.kb, base, ilvl)


@app.post("/api/craft/routes")
def craft_routes(payload: dict = Body(...)):
    from soe.items.crafter import craft_routes as run

    return run(session.kb, payload["base"], int(payload.get("ilvl") or 82), payload.get("wanted") or [],
               sims=int(payload.get("sims") or 2000))


_ICON_POOL = None


@app.get("/api/icon")
async def icon(name: str, kind: str = "item", fallback: str | None = None):
    """Icon of an item, base or gem from poe2db (cached in data/icons). fallback: tried when name has none
    (a rare's own name -> its base). Runs on its own two threads, so a page full of new icons never queues
    the PoB calculations behind poe2db downloads."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    from soe.web.icons import icon_file

    global _ICON_POOL
    if _ICON_POOL is None:
        _ICON_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="icons")
    loop = asyncio.get_running_loop()
    for n in [name, fallback]:
        if n:
            p = await loop.run_in_executor(_ICON_POOL, icon_file, n, kind)
            if p:
                return FileResponse(p, headers={"Cache-Control": "public, max-age=604800"})
    raise HTTPException(404, "no icon")


@app.get("/api/equipment")
def equipment():
    """Equipped items (the active weapon set) with their mod lines, for the gear view."""
    from soe.advisor.checkup import split_item
    from soe.items.craft import _clean

    def run():
        session._need_build()
        out = []
        for it in session.pob.items(active_only=True):
            head, imp, exp = split_item(it["raw"])
            flags = lambda ln: [t for t in ("fractured", "desecrated", "crafted", "rune", "enchant") if "{" + t + "}" in ln]
            out.append({"slot": it["slot"], "name": it["name"], "base": it.get("base"), "rarity": it.get("rarity"),
                        "implicits": [{"text": _clean(x), "flags": flags(x)} for x in imp if x.strip()],
                        "mods": [{"text": _clean(x), "flags": flags(x)} for x in exp if x.strip()]})
        return {"level": session.base.get("level"), "items": out}
    return locked(run)


@app.post("/api/search_items")
def search_items(payload: dict = Body(...)):
    """Trade listings with these mods (minimums at ~80% of the given values), each measured in PoB."""
    from soe.prices.trade import _relaxed, search_items as run

    mods = [_relaxed(m) for m in payload["mods"]]
    r = locked(run, session, payload["slot"], mods, payload.get("budget"),
               _goals(payload.get("damage", 1), payload.get("survive", 1), payload.get("speed", 1)))
    r["searched_mods"] = mods
    return r


@app.get("/api/ideal_item")
def ideal_item(slot: str, damage: float = 1, survive: float = 1):
    from soe.items.craft import ideal_item as ii

    return locked(ii, session, slot, _goals(damage, survive))


@app.get("/api/combos")
def combos(damage: float = 1, survive: float = 1):
    from soe.combo.mechanics import suggest_combos

    return locked(suggest_combos, session, _goals(damage, survive))


@app.get("/api/prices")
def prices(names: str = ""):
    from soe.prices import default_prices

    p = default_prices()
    return {"status": p.status(), "prices": {n: p.price(n) for n in names.split("|") if n}}


@app.get("/api/kb/search")
def kb_search(q: str, kind: str | None = None, limit: int = 20):
    return session.kb.search(q, kind, limit)


@app.get("/api/kb/gem")
def kb_gem(name: str):
    return session.kb.gem(name)


@app.get("/api/kb/unique")
def kb_unique(name: str):
    return session.kb.unique(name)


def _already_running(url: str) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(url + "/api/status", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def main(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False):
    import threading
    import time
    import webbrowser

    import uvicorn

    url = f"http://{host}:{port}"
    if _already_running(url):  # second click on the launcher: just show the app
        print(f"Slop of Exile Helper już działa: {url}")
        if open_browser:
            webbrowser.open(url)
        return

    if open_browser:
        def opener():
            for _ in range(120):
                if _already_running(url):
                    webbrowser.open(url)
                    return
                time.sleep(0.5)
        threading.Thread(target=opener, daemon=True).start()

    _restore_last()
    print(f"Slop of Exile Helper: {url}  (zamknij to okno, żeby wyłączyć)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    import sys

    main(open_browser="--open" in sys.argv)
