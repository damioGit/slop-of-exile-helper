"""Crafting rules sensor: what the orbs, omens and bones the Kuźnia simulates actually do, read from poe2db.

The routes in soe.items.crafter are written for today's rules (an Exalted Orb adds one mod, Greater Exalted only
mods of level 35+, ...). This module fetches each tracked item's page, keeps its effect text and "Minimum Modifier
Level", and compares them with the copy the player last accepted:

- a changed minimum level is applied automatically (min_levels() feeds the simulation);
- a changed effect text is reported until the player accepts it: the routes may be outdated until the code follows;
- omens that appear on poe.ninja but did not exist at the first check are listed as new (the Kuźnia does not use them).

Saved in data/poe2db/_rules.json. SOE_POE2DB=offline never fetches (tests).
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error

from soe.kb import poe2db

FILE = poe2db.DIR / "_rules.json"
TTL = 7 * 24 * 3600

# item -> what the simulation assumes (Polish, shown next to a change)
TRACKED = {
    "Orb of Transmutation": "zwykły -> magic z 1 modem",
    "Orb of Augmentation": "dodaje mod do magic (max 2)",
    "Regal Orb": "magic -> rare, +1 mod",
    "Orb of Alchemy": "zwykły -> rare z 4 modami",
    "Exalted Orb": "dodaje 1 losowy mod do rare",
    "Greater Exalted Orb": "jak Exalted, mody od min. poziomu",
    "Perfect Exalted Orb": "jak Exalted, mody od min. poziomu",
    "Chaos Orb": "usuwa losowy mod i dodaje losowy",
    "Orb of Annulment": "usuwa losowy mod",
    "Omen of Sinistral Exaltation": "Exalt dodaje tylko prefix",
    "Omen of Dextral Exaltation": "Exalt dodaje tylko suffix",
    "Omen of Sinistral Annulment": "Annul usuwa tylko prefix",
    "Omen of Dextral Annulment": "Annul usuwa tylko suffix",
    "Omen of Sinistral Crystallisation": "Perfect Essence usuwa tylko prefix",
    "Omen of Dextral Crystallisation": "Perfect Essence usuwa tylko suffix",
    "Omen of Sinistral Necromancy": "desecration dodaje tylko prefix",
    "Omen of Dextral Necromancy": "desecration dodaje tylko suffix",
    "Omen of Abyssal Echoes": "jedno przelosowanie opcji przy odsłanianiu",
    "Omen of Light": "Annul usuwa tylko mod desecrated",
    "Essence of the Body": "magic -> rare z pewnym modem",
    "Perfect Essence of the Body": "na rare: usuwa losowy mod, dodaje pewny",
    "Preserved Rib": "desecration zbroi",
    "Ancient Rib": "desecration zbroi, mody od min. poziomu",
    "Preserved Collarbone": "desecration biżuterii",
    "Ancient Collarbone": "desecration biżuterii, mody od min. poziomu",
    "Preserved Jawbone": "desecration broni",
    "Ancient Jawbone": "desecration broni, mody od min. poziomu",
}
# the minimum modifier levels the code was written with (used when poe2db has nothing)
DEFAULT_MIN = {"Greater Exalted Orb": 35, "Perfect Exalted Orb": 50,
               "Ancient Rib": 40, "Ancient Collarbone": 40, "Ancient Jawbone": 40}


def page_name(name: str) -> str:
    return name.replace("'", "").replace(" ", "_")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def parse_item(page_html: str) -> dict:
    """Effect lines and minimum modifier level of the first item box on a poe2db page."""
    i = page_html.find('class="property"')
    if i < 0:
        return {}
    block = page_html[i:i + 6000]
    end = block.find('class="secDescrText"')
    if end > 0:
        block = block[:end]
    props = [_clean(x) for x in re.findall(r'<div class="property">(.*?)</div>', block, re.S)]
    mods = [_clean(x) for x in re.findall(r'<div class="explicitMod">(.*?)</div>', block, re.S)]
    lvl = next((int(m.group(1)) for p in props if (m := re.search(r"Minimum Modifier Level\s*:\s*(\d+)", p))), None)
    return {"effect": mods[0] if mods else None, "min_level": lvl}


def _load() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(d: dict):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text(json.dumps(d, indent=1, ensure_ascii=False), encoding="utf-8")


def _omens_now() -> list[str]:
    try:
        from soe.prices.ninja import default_prices

        return sorted({v["name"] for v in default_prices().index.values() if v["name"].startswith("Omen of")})
    except Exception:
        return []


def check(force: bool = False, fetch=None) -> dict:
    """Fetch the tracked pages (weekly) and compare. `fetch(url) -> bytes` can be replaced in tests."""
    d = _load()
    if not force and time.time() - d.get("checked", 0) < TTL:
        return d
    if poe2db.offline() and fetch is None:
        return d
    fetch = fetch or poe2db._get
    items = d.setdefault("items", {})
    for name in TRACKED:
        try:
            got = parse_item(fetch(f"https://poe2db.tw/us/{page_name(name)}").decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, TimeoutError, ValueError):
            continue  # keep what we had: a network error is no rules change
        rec = items.setdefault(name, {})
        if not got.get("effect"):
            rec["missing"] = True
            continue
        rec.pop("missing", None)
        rec["current"] = got
        rec.setdefault("accepted", got)  # first sight: this is the baseline
    omens = _omens_now()
    if omens:
        d.setdefault("known_omens", omens)
        d["omens_now"] = omens
    d["checked"] = time.time()
    _save(d)
    return d


def accept() -> dict:
    """The player saw the changes: today's texts become the baseline, new omens become known."""
    d = _load()
    for rec in d.get("items", {}).values():
        if rec.get("current"):
            rec["accepted"] = rec["current"]
    if d.get("omens_now"):
        d["known_omens"] = d["omens_now"]
    _save(d)
    return report()


def min_levels() -> dict[str, int]:
    """Minimum modifier levels for the simulation: poe2db's current value, else the default."""
    out = dict(DEFAULT_MIN)
    for name, rec in _load().get("items", {}).items():
        lvl = (rec.get("current") or {}).get("min_level")
        if lvl is not None and name in DEFAULT_MIN:
            out[name] = lvl
    return out


def report() -> dict:
    d = _load()
    changes, applied = [], []
    for name, rec in d.get("items", {}).items():
        cur, acc = rec.get("current") or {}, rec.get("accepted") or {}
        if rec.get("missing"):
            changes.append({"item": name, "kind": "missing", "assumes": TRACKED.get(name),
                            "text": f"{name}: nie ma już opisu na poe2db (usunięte albo przemianowane?)"})
            continue
        if cur.get("effect") and acc.get("effect") and cur["effect"] != acc["effect"]:
            changes.append({"item": name, "kind": "effect", "assumes": TRACKED.get(name), "old": acc["effect"],
                            "new": cur["effect"], "text": f"{name}: zmienił się opis działania"})
        if cur.get("min_level") is not None and name in DEFAULT_MIN and cur["min_level"] != DEFAULT_MIN[name]:
            applied.append(f"{name}: minimalny poziom moda {DEFAULT_MIN[name]} -> {cur['min_level']} (Kuźnia już liczy z nowym)")
    known = set(d.get("known_omens") or [])
    new_omens = [o for o in d.get("omens_now") or [] if known and o not in known]
    return {"tracked": len(TRACKED), "checked_items": len(d.get("items", {})), "changes": changes,
            "applied": applied, "new_omens": new_omens,
            "checked": d.get("checked")}
