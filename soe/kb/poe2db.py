"""Mod data from poe2db.tw: the real spawn weights of every mod tier, the desecrated mod pools and the essences,
per item class (and per attribute for armour), as the game data has them.

poe2db pages like https://poe2db.tw/us/Body_Armours_int embed one JSON object (`new ModsView({...})`) with:
- normal: every prefix/suffix tier that can roll there, with DropChance (the spawn weight), Level, ModFamilyList
- desecrated: the special mods a Desecration (bone) can reveal
- essence / perfect_essence: what each essence guarantees there

Pages are saved in data/poe2db/<page>.json (slim) and refreshed after a week. `soe poe2db sync` fetches all of them;
the crafting code also fetches a missing page on first use. SOE_POE2DB=offline never touches the network
(tests), and then the code falls back to PoB's data with equal weights.
"""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "data" / "poe2db"
TTL = 7 * 24 * 3600
UA = "Mozilla/5.0 (slop-of-exile-helper; crafting odds)"
_lock = threading.Lock()
_mem: dict[str, dict] = {}
_last = [0.0]

SIMPLE = {"Ring": "Rings", "Amulet": "Amulets", "Belt": "Belts", "Quiver": "Quivers", "Wand": "Wands",
          "Sceptre": "Sceptres", "Bow": "Bows", "Crossbow": "Crossbows", "Spear": "Spears", "Talisman": "Talismans",
          "Dagger": "Daggers", "Claw": "Claws", "Flail": "Flails", "Focus": "Foci",
          "One Hand Mace": "One_Hand_Maces", "Two Hand Mace": "Two_Hand_Maces",
          "One Hand Sword": "One_Hand_Swords", "Two Hand Sword": "Two_Hand_Swords",
          "One Hand Axe": "One_Hand_Axes", "Two Hand Axe": "Two_Hand_Axes"}
ARMOUR = {"Body Armour": "Body_Armours", "Helmet": "Helmets", "Gloves": "Gloves", "Boots": "Boots"}
ATTRS = ("str_dex_int", "str_dex", "str_int", "dex_int", "str", "dex", "int")
BONE = {"weapon": "Jawbone", "armour": "Rib", "jewellery": "Collarbone"}


def offline() -> bool:
    return os.environ.get("SOE_POE2DB", "").lower() == "offline"


def page_for_base(base: dict) -> str | None:
    """poe2db page with the mod pool of a KB base row."""
    t, st, tags = base.get("type"), base.get("sub_type"), set(base.get("tags") or [])
    if t == "Staff":
        return "Quarterstaves" if st == "Warstaff" or "warstaff" in tags else "Staves"
    if t in SIMPLE:
        return SIMPLE[t]
    attr = next((a for a in ATTRS if f"{a}_armour" in tags), None)
    if t == "Shield":
        if "buckler" in tags:
            return "Bucklers"
        return f"Shields_{attr}" if attr else None
    if t in ARMOUR and attr:
        return f"{ARMOUR[t]}_{attr}"
    return None


def bone_kind(base: dict) -> str | None:
    t = base.get("type")
    if t in ("Ring", "Amulet", "Belt"):
        return "jewellery"
    if t in ARMOUR or t in ("Shield", "Focus"):
        return "armour"
    if t:
        return "weapon"
    return None


def all_pages(kb) -> list[str]:
    pages = set()
    for b in kb._rows("SELECT name, type, sub_type, tags FROM bases WHERE hidden = 0"):
        p = page_for_base(b)
        if p:
            pages.add(p)
    return sorted(pages)


# ---------------------------------------------------------------- fetch and parse

def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    s = html.unescape(s).replace("—", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip()


def _modsview(page_html: str) -> dict:
    i = page_html.index("new ModsView(") + len("new ModsView(")
    depth, in_str, esc = 0, False, False
    for k in range(i, len(page_html)):
        ch = page_html[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(page_html[i:k + 1])
    raise ValueError("ModsView JSON not closed")


def _side(m: dict) -> str | None:
    return {"1": "Prefix", "2": "Suffix"}.get(str(m.get("ModGenerationTypeID")))


def _mod_id(m: dict) -> str | None:
    hv = unquote(m.get("hover") or "")
    return hv.split("Mods/")[-1] if "Mods/" in hv else (m.get("Code") or None)


def parse(page: str, page_html: str) -> dict:
    d = _modsview(page_html)

    def mods(rows, kind):
        out = []
        for m in rows or []:
            side = _side(m)
            if not side:
                continue
            row = {"id": _mod_id(m), "type": side, "level": int(m.get("Level") or 1),
                   "weight": int(m.get("DropChance") or 0), "fams": list(m.get("ModFamilyList") or []),
                   "text": _clean(m.get("str", ""))}
            if kind == "essence":
                row["name"] = _clean(m.get("Name", ""))
                row["perfect"] = str(m.get("IsPerfect")) == "1"
                row["req"] = m.get("reqlvl")
            elif kind == "desecrated":
                row["name"] = _clean(m.get("Name", ""))
            out.append(row)
        return out

    return {"page": page, "fetched": time.time(), "class": (d.get("opt") or {}).get("ItemClassesCode"),
            "normal": mods(d.get("normal"), "normal"),
            "desecrated": mods(d.get("desecrated"), "desecrated"),
            "essence": mods((d.get("essence") or []) + (d.get("perfect_essence") or []), "essence")}


def _get(url: str) -> bytes:
    wait = 0.5 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def page_data(page: str, refresh: bool = False) -> dict | None:
    """The parsed page: from memory, data/poe2db, or poe2db.tw (when allowed and the copy is missing or old)."""
    with _lock:
        if page in _mem and not refresh:
            return _mem[page]
        f = DIR / f"{page}.json"
        data = None
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
        stale = data is None or refresh or time.time() - data.get("fetched", 0) > TTL
        if stale and not offline():
            try:
                fresh = parse(page, _get(f"https://poe2db.tw/us/{page}").decode("utf-8", "replace"))
                if fresh["normal"]:
                    DIR.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
                    data = fresh
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                pass  # keep the old copy (or none): the caller falls back to PoB's data
        if data:
            _mem[page] = data
        return data


def for_base(base: dict) -> dict | None:
    p = page_for_base(base)
    return page_data(p) if p else None


def sync(kb, refresh: bool = True, log=print) -> dict:
    pages = all_pages(kb)
    ok, bad = [], []
    for p in pages:
        d = page_data(p, refresh=refresh)
        (ok if d else bad).append(p)
        log(f"{p}: {len(d['normal']) if d else 0} mods" + ("" if d else " (failed)"))
    return {"pages": len(pages), "ok": len(ok), "failed": bad}


def status() -> dict:
    files = sorted(f for f in DIR.glob("*.json") if not f.name.startswith("_")) if DIR.exists() else []  # _rules.json is no page
    if not files:
        return {"pages": 0, "fetched": None}
    newest = max(json.loads(f.read_text(encoding="utf-8")).get("fetched", 0) for f in files)
    return {"pages": len(files), "fetched": time.strftime("%Y-%m-%d %H:%M", time.localtime(newest))}
