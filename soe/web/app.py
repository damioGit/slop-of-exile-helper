"""Local web app: the same advisor session as the MCP server, behind a small JSON API and one page.

Run: soe web   (http://127.0.0.1:8765)
Single user, local only. Long calls (support optimizer, plan) block for their duration.
"""
from __future__ import annotations

import os
import traceback
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from soe.advisor.session import Session

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Slop of Exile Helper", docs_url="/api/docs", redoc_url=None)
session = Session(os.environ.get("SOE_KB") or None)


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/status")
def status():
    meta = {}
    try:
        meta = session.kb.meta()
    except Exception as e:  # KB not built yet
        meta = {"error": str(e)}
    return {"loaded": session.loaded, "name": session.name, "kb": meta,
            "summary": session.base if session.loaded else None}


@app.post("/api/load")
def load(payload: dict = Body(...)):
    return locked(session.load, payload["code"], payload.get("name") or "build")


@app.post("/api/reset")
def reset():
    return locked(session.reset)


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
    return locked(session.apply_changes, payload["steps"])


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

    print(f"Slop of Exile Helper: {url}  (zamknij to okno, żeby wyłączyć)")
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    import sys

    main(open_browser="--open" in sys.argv)
