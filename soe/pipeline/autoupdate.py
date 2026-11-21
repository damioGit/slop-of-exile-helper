"""Keeps the helper's data current without anyone typing commands.

Checked when the web app starts and when a page asks for the data status (at most every CHECK_EVERY):
- Path of Building (PoE2): a newer GitHub release -> fetch, engine check on tests/builds, new knowledge base,
  patch report, poe2db refresh, then the running app swaps to the new engine (callback). A failed engine check
  keeps the old version (soe.pipeline.update does the rollback).
- knowledge base: built from another PoB version than POB_VERSION (or missing) -> rebuilt.
- poe2db: pages older than a week -> fetched again (mod weights, essences, desecrated mods).
- poe.ninja prices: refreshed when older than their TTL (on use).
- the app itself: a git checkout behind origin -> reported; `update_app()` pulls it when the player clicks.

SOE_AUTOUPDATE=0 switches the automatic part off (tests, offline play).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data" / "update_state.json"
LOCK = ROOT / "data" / "update.lock"
SETTINGS = ROOT / "data" / "user" / "settings.json"  # shared with scripts/self_update.py


def settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_setting(key: str, value) -> dict:
    s = settings()
    s[key] = value
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s


def update_source() -> str | None:
    f = ROOT / "UPDATE_SOURCE"
    return f.read_text(encoding="utf-8").split()[0] if f.exists() and f.read_text(encoding="utf-8").split() else None  # one updater at a time, also across app instances
CHECK_EVERY = 6 * 3600


def enabled() -> bool:
    return os.environ.get("SOE_AUTOUPDATE", "1") not in ("0", "off", "false")


def _git(*args, cwd=ROOT, timeout=60) -> str | None:
    if not shutil.which("git"):
        return None
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _age(ts: float | None) -> str | None:
    if not ts:
        return None
    s = time.time() - ts
    return f"{int(s // 60)} min temu" if s < 3600 else f"{s / 3600:.0f} h temu" if s < 2 * 86400 else f"{s / 86400:.0f} dni temu"


class Updater:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.step: str | None = None
        self.log: list[str] = []
        self.on_new_engine = None  # called after PoB / the knowledge base changed (the app reloads its session)
        self.state = self._load()

    # ---- state --------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(self):
        try:
            STATE.parent.mkdir(parents=True, exist_ok=True)
            STATE.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
        except OSError:
            pass

    def _log(self, msg: str):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        print(f"[update] {line}", flush=True)
        self.log = (self.log + [line])[-40:]

    # ---- what is installed ---------------------------------------------------------
    def local(self) -> dict:
        from soe.kb import poe2db
        from soe.kb.build import current_db_path

        pinned = (ROOT / "POB_VERSION").read_text().strip() if (ROOT / "POB_VERSION").exists() else None
        pob_ok = (ROOT / "vendor" / "PathOfBuilding-PoE2" / "src" / "HeadlessWrapper.lua").exists()
        kb_meta = {}
        try:
            from soe.kb.query import KB

            if current_db_path().exists():
                kb_meta = KB(current_db_path()).meta()
        except Exception:
            kb_meta = {}
        files = sorted(poe2db.DIR.glob("*.json")) if poe2db.DIR.exists() else []
        fetched = []
        for f in files:
            try:
                fetched.append(json.loads(f.read_text(encoding="utf-8")).get("fetched", 0))
            except (OSError, ValueError):
                pass
        stale = sum(1 for t in fetched if time.time() - t > poe2db.TTL)
        prices = sorted((ROOT / "data" / "prices").rglob("*.json")) if (ROOT / "data" / "prices").exists() else []
        newest_price = max((p.stat().st_mtime for p in prices), default=None)
        commit = _git("rev-parse", "--short", "HEAD")
        return {
            "pob": {"pinned": pinned, "installed": pob_ok},
            "kb": {"pob_version": kb_meta.get("pob_version"), "built_at": kb_meta.get("built_at"),
                   "tree": kb_meta.get("tree_version"), "matches": bool(kb_meta) and kb_meta.get("pob_version") == pinned},
            "poe2db": {"pages": len(fetched), "stale": stale, "oldest": _age(min(fetched)) if fetched else None,
                       "newest": _age(max(fetched)) if fetched else None},
            "prices": {"updated": _age(newest_price), "old": not newest_price or time.time() - newest_price > 6 * 3600},
            "app": {"commit": commit, "git": commit is not None, "source": update_source(),
                    "auto": bool(settings().get("auto_update_app", True))},
        }

    # ---- what is out there (network, cached) ---------------------------------------
    def remote(self, force: bool = False) -> dict:
        r = self.state.get("remote") or {}
        if not force and r.get("checked") and time.time() - r["checked"] < CHECK_EVERY:
            return r
        out = {"checked": time.time()}
        try:
            from soe.pipeline.update import latest_tag

            out["pob_latest"] = latest_tag()
        except Exception as e:
            out["pob_error"] = f"{type(e).__name__}: {e}"
        if _git("rev-parse", "--is-inside-work-tree") == "true":
            _git("fetch", "-q", timeout=60)
            behind = _git("rev-list", "--count", "HEAD..@{u}")
            out["app_behind"] = int(behind) if behind and behind.isdigit() else None
        self.state["remote"] = out
        self._save()
        return out

    def status(self) -> dict:
        loc = self.local()
        rem = self.state.get("remote") or {}
        latest = rem.get("pob_latest")
        loc["pob"]["latest"] = latest
        loc["pob"]["update"] = bool(latest and loc["pob"]["pinned"] and latest != loc["pob"]["pinned"])
        loc["app"]["behind"] = rem.get("app_behind")
        loc["checked"] = _age(rem.get("checked"))
        loc["updater"] = {"running": self.running, "step": self.step, "log": self.log[-12:],
                          "last": self.state.get("last_result"), "auto": enabled(), "git": shutil.which("git") is not None}
        try:
            from soe.kb import craft_rules

            rules = craft_rules.report()
            rules["checked"] = _age(rules.get("checked"))
        except Exception:
            rules = {"changes": [], "applied": [], "new_omens": [], "tracked": 0, "checked_items": 0, "checked": None}
        loc["rules"] = rules
        todo = []
        if not loc["pob"]["installed"]:
            todo.append("brak Path of Building")
        if loc["pob"]["update"]:
            todo.append(f"nowe PoB {latest}")
        if not loc["kb"]["matches"]:
            todo.append("baza wiedzy do przebudowania")
        if loc["poe2db"]["pages"] == 0 or loc["poe2db"]["stale"]:
            todo.append("dane poe2db do odświeżenia")
        if rules["changes"]:
            todo.append(f"zmiany zasad craftingu ({len(rules['changes'])})")
        if not rules["checked_items"]:
            todo.append("zasady craftingu niesprawdzone")
        if loc["prices"]["old"]:
            todo.append("ceny do odświeżenia")
        if loc["app"].get("behind"):
            todo.append(f"nowa wersja appki ({loc['app']['behind']} zmian)")
        loc["todo"] = todo
        loc["ok"] = not todo
        return loc

    # ---- doing it -----------------------------------------------------------------
    def maybe_start(self, force: bool = False) -> bool:
        """Start a background check + update if it is due (or forced). Returns True when one started."""
        if self.running or (not force and not enabled()):
            return False
        last = (self.state.get("remote") or {}).get("checked") or 0
        if not force and time.time() - last < CHECK_EVERY:
            return False
        threading.Thread(target=self.run, kwargs={"force": force}, daemon=True).start()
        return True

    def run(self, force: bool = False):
        with self.lock:
            if self.running:
                return
            try:
                if LOCK.exists() and time.time() - LOCK.stat().st_mtime < 3600:
                    return  # another instance is updating
                LOCK.parent.mkdir(parents=True, exist_ok=True)
                LOCK.write_text(str(os.getpid()))
            except OSError:
                return
            self.running = True
        changed_engine = False
        result = {"at": time.time(), "done": [], "errors": []}
        try:
            self.step = "sprawdzam wersje"
            rem = self.remote(force=True)
            loc = self.local()
            pinned = loc["pob"]["pinned"]
            latest = rem.get("pob_latest")
            git_ok = shutil.which("git") is not None
            if latest and pinned and latest != pinned:
                if not git_ok:
                    result["errors"].append("nowe PoB jest, ale brak gita do pobrania")
                else:
                    self.step = f"aktualizuję Path of Building {pinned} -> {latest}"
                    self._log(self.step)
                    from soe.pipeline import update as up

                    res = up.update(latest)
                    if res.get("ok"):
                        result["done"].append(f"PoB {pinned} -> {latest}")
                        changed_engine = True
                    else:
                        result["errors"].append(f"PoB {latest}: test silnika nie przeszedł, zostaje {pinned}")
            elif not loc["pob"]["installed"] and git_ok and pinned:
                self.step = f"pobieram Path of Building {pinned}"
                self._log(self.step)
                sys.path.insert(0, str(ROOT / "scripts"))
                from fetch_pob import fetch

                fetch(pinned)
                result["done"].append(f"PoB {pinned} pobrane")
                changed_engine = True
            if not changed_engine and not self.local()["kb"]["matches"]:
                self.step = "buduję bazę wiedzy"
                self._log(self.step)
                from soe.kb.build import build

                build()
                result["done"].append("baza wiedzy przebudowana")
                changed_engine = True
            self.step = "odświeżam dane poe2db"
            from soe.kb import poe2db
            from soe.kb.query import KB

            before = poe2db.status()
            info = poe2db.sync(KB(), refresh=False, log=lambda m: None)  # only missing or week-old pages
            if info["failed"]:
                result["errors"].append(f"poe2db: {len(info['failed'])} stron bez danych")
            if poe2db.status() != before:
                result["done"].append("poe2db odświeżone")
            self.step = "sprawdzam zasady craftingu (poe2db)"
            try:
                from soe.kb import craft_rules

                craft_rules.check()
                rep = craft_rules.report()
                if rep["changes"]:
                    result["errors"].append(f"zasady craftingu: {len(rep['changes'])} zmian na poe2db")
            except Exception as e:
                result["errors"].append(f"zasady craftingu: {e}")
            self.step = "odświeżam ceny"
            try:
                from soe.prices import ninja

                ninja.default_prices().status()
            except Exception as e:
                result["errors"].append(f"ceny: {e}")
            if changed_engine and self.on_new_engine:
                self.step = "przełączam appkę na nowe dane"
                self.on_new_engine()
        except Exception as e:
            traceback.print_exc()
            result["errors"].append(f"{type(e).__name__}: {e}")
        finally:
            self._log("gotowe: " + (", ".join(result["done"]) or "wszystko było aktualne")
                      + (f"; problemy: {', '.join(result['errors'])}" if result["errors"] else ""))
            self.state["last_result"] = {**result, "when": time.strftime("%Y-%m-%d %H:%M")}
            self._save()
            self.step = None
            self.running = False
            LOCK.unlink(missing_ok=True)

    def update_app(self) -> dict:
        """git pull + reinstall; the app has to start again afterwards."""
        if _git("rev-parse", "--is-inside-work-tree") != "true":
            return {"ok": False, "error": "To nie jest kopia z gita: pobierz nową paczkę ręcznie."}
        if _git("status", "--porcelain"):
            return {"ok": False, "error": "Masz lokalne zmiany w plikach appki: najpierw je zatwierdź albo cofnij."}
        out = _git("pull", "--ff-only", timeout=180)
        if out is None:
            return {"ok": False, "error": "git pull się nie udał (brak sieci albo rozjechane gałęzie)."}
        pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(ROOT)], capture_output=True, text=True)
        self.state.setdefault("remote", {})["app_behind"] = 0
        self._save()
        return {"ok": pip.returncode == 0, "pulled": out[-500:], "restart": True,
                "error": None if pip.returncode == 0 else pip.stderr[-500:]}


updater = Updater()
