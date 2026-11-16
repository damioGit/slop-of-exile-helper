"""Real items from the official Path of Exile 2 trade site, priced and measured in PoB.

For a wanted mod on a slot (e.g. "+# to Level of all Lightning Spell Skills" on a staff) this:
1. finds the trade stat id for the mod text (trade2 /data/stats, cached a day),
2. searches the slot's item category for items with at least that value, cheapest first,
3. fetches the listings (price, item text, all mods),
4. converts each price to divine (poe.ninja rates) and drops the ones over budget,
5. puts every item in the build's slot with PoB's what-if calculator and ranks them by gain.

It sends at most two requests per search and backs off on rate limits. Nothing is bought; the result
links to the same search on the trade site.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.pathofexile.com/api/trade2"
SITE = "https://www.pathofexile.com/trade2/search/poe2"
UA = "slop-of-exile-helper/0.1 (local build helper)"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "prices"

CATEGORY = {
    "Ring": "accessory.ring", "Amulet": "accessory.amulet", "Belt": "accessory.belt",
    "Body Armour": "armour.chest", "Helmet": "armour.helmet", "Gloves": "armour.gloves", "Boots": "armour.boots",
    "Shield": "armour.shield", "Focus": "armour.focus", "Quiver": "armour.quiver", "Buckler": "armour.buckler",
    "Staff": "weapon.staff", "Warstaff": "weapon.warstaff", "Quarterstaff": "weapon.warstaff", "Wand": "weapon.wand",
    "Sceptre": "weapon.sceptre", "Bow": "weapon.bow", "Crossbow": "weapon.crossbow", "Spear": "weapon.spear",
    "One Hand Mace": "weapon.onemace", "Two Hand Mace": "weapon.twomace", "Flail": "weapon.flail",
    "Dagger": "weapon.dagger", "Claw": "weapon.claw", "One Hand Sword": "weapon.onesword",
    "Two Hand Sword": "weapon.twosword", "One Hand Axe": "weapon.oneaxe", "Two Hand Axe": "weapon.twoaxe",
    "Talisman": "weapon.talisman",
}
CURRENCY_NAME = {"divine": "Divine Orb", "exalted": "Exalted Orb", "chaos": "Chaos Orb", "regal": "Regal Orb",
                 "alch": "Orb of Alchemy", "annul": "Orb of Annulment", "vaal": "Vaal Orb", "aug": "Orb of Augmentation",
                 "transmute": "Orb of Transmutation", "mirror": "Mirror of Kalandra"}


class TradeError(RuntimeError):
    pass


def _req(url: str, body: dict | None = None, tries: int = 3):
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Content-Type": "application/json",
                                                             "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                wait = int(e.headers.get("Retry-After") or 10)
                time.sleep(min(wait, 60))
                continue
            if e.code in (403, 429):
                raise TradeError("the trade site is refusing requests right now (rate limit); try again in a minute") from e
            raise TradeError(f"trade site error {e.code}") from e
        except urllib.error.URLError as e:
            raise TradeError(f"trade site not reachable: {e.reason}") from e


def _norm(text: str) -> str:
    t = re.sub(r"\{[^}]*\}", "", text)
    t = re.sub(r"\(-?\d+(?:\.\d+)?--?\d+(?:\.\d+)?\)", "#", t)
    t = re.sub(r"-?\d+(?:\.\d+)?", "#", t)
    t = t.replace("+#", "#").replace("+", "")
    return re.sub(r"\s+", " ", t).strip().lower()


_STATS: dict | None = None


def stat_ids() -> dict[str, dict[str, str]]:
    """normalized mod text -> {stat type: trade stat id}."""
    global _STATS
    if _STATS is not None:
        return _STATS
    f = CACHE / "_trade_stats.json"
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        data = json.loads(f.read_text(encoding="utf-8"))
    else:
        data = _req(f"{API}/data/stats")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data), encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for grp in data.get("result", []):
        for e in grp.get("entries", []):
            out.setdefault(_norm(e["text"]), {})[e.get("type") or grp["id"]] = e["id"]
    _STATS = out
    return out


def stat_filter(mod_text: str, min_value: float | None = None) -> dict | None:
    """Trade filter for one mod line (explicit first), with the first number as minimum."""
    ids = stat_ids().get(_norm(mod_text))
    if not ids:
        return None
    sid = ids.get("explicit") or ids.get("fractured") or next(iter(ids.values()))
    if min_value is None:
        nums = re.findall(r"\d+(?:\.\d+)?", mod_text)
        min_value = float(nums[0]) if nums else None
    flt = {"id": sid}
    if min_value is not None:
        flt["value"] = {"min": min_value}
    return flt


def _raw_from_listing(item: dict) -> str:
    rarity = (item.get("rarity") or "Rare").upper()
    lines = [f"Rarity: {rarity}"]
    if item.get("name"):
        lines.append(item["name"])
    lines.append(item.get("typeLine") or item.get("baseType"))
    if item.get("ilvl"):
        lines.append(f"Item Level: {item['ilvl']}")
    for p in item.get("properties", []):
        if p.get("name") == "Quality" and p.get("values"):
            q = re.findall(r"\d+", p["values"][0][0])
            if q:
                lines.append(f"Quality: {q[0]}")
    granted = [f"Grants Skill: {v[0]}" for g in item.get("grantedSkills") or [] for v in (g.get("values") or [])]
    implicits = [*(item.get("enchantMods") or []), *(item.get("runeMods") or []), *(item.get("implicitMods") or []),
                 *granted]
    lines.append(f"Implicits: {len(implicits)}")
    lines += implicits
    lines += [*(item.get("fracturedMods") or []), *(item.get("explicitMods") or []),
              *(item.get("desecratedMods") or []), *(item.get("craftedMods") or [])]
    if item.get("corrupted"):
        lines.append("Corrupted")
    return "\n".join(_clean_markup(x) for x in lines if x)


def _clean_markup(s) -> str:
    # trade text uses [Tag|Shown] and [Tag] markup; some mod lists hold objects instead of strings
    if isinstance(s, dict):
        s = s.get("description") or s.get("text") or s.get("name") or ""
    return re.sub(r"\[([^\]|]*\|)?([^\]]*)\]", r"\2", str(s))


def key_mods(session, slot: str, objective=None, keep: int = 3, min_loss: float = 3.0) -> list[dict]:
    """The current item's explicit mods that matter most (removing one costs at least min_loss score)."""
    from soe.advisor.checkup import join_item, split_item
    from soe.items.craft import _clean
    from soe.optimize.objective import Objective

    obj = objective or Objective()
    cur = session.item(slot)
    if not cur:
        return []
    head, imp, exp = split_item(cur["raw"])
    rows = []
    for i, line in enumerate(exp):
        text = _clean(line).strip()
        if not text or text in ("Corrupted", "Mirrored") or not stat_ids().get(_norm(text)):
            continue
        w = session.pob.whatif(slot=slot, item_raw=join_item(head, imp, exp[:i] + exp[i + 1:]))
        loss = -obj.score(w, session.base)
        if loss >= min_loss:
            rows.append({"mod": text, "loss": round(loss, 1)})
    rows.sort(key=lambda r: r["loss"], reverse=True)
    return rows[:keep]


def _relaxed(text: str, factor: float = 0.8) -> str:
    """Same mod line with its first number lowered (accept a slightly worse roll than yours)."""
    m = re.search(r"\d+(?:\.\d+)?", text)
    if not m:
        return text
    v = float(m.group())
    nv = max(1, int(v * factor)) if v >= 2 else v
    return text[:m.start()] + f"{nv:g}" + text[m.end():]


def find_upgrade(session, slot: str, wanted: str | None = None, budget_divine: float | None = None,
                 objective=None) -> dict:
    """Search the market for an upgrade of the item in `slot`: keep what makes the current item strong
    (its key mods at ~80% of your rolls) and add the wanted mod. Loosens the search once if nothing is listed."""
    keys = key_mods(session, slot, objective)
    must = [_relaxed(k["mod"]) for k in keys]
    attempts = [must + ([wanted] if wanted else []), must[:max(0, len(must) - 1)] + ([wanted] if wanted else [])]
    last = None
    for mods in attempts:
        if not mods:
            continue
        last = search_items(session, slot, mods, budget_divine, objective)
        last["searched_mods"] = mods
        last["kept_from_current"] = keys
        if last["items"]:
            break
    return last or {"slot": slot, "items": [], "found": 0, "searched_mods": []}


def search_items(session, slot: str, mods: list[str], budget_divine: float | None = None, objective=None,
                 limit: int = 10, league: str | None = None) -> dict:
    """Cheapest listed items for the slot with the given mod lines (minimums from their numbers),
    each measured in the loaded build."""
    from soe.optimize.objective import Objective
    from soe.prices import default_prices
    from soe.advisor.session import diff

    session._need_build()
    obj = objective or Objective()
    pob, kb = session.pob, session.kb
    cur = session.item(slot)
    base = kb.base(cur["base"]) if cur else None
    cat = CATEGORY.get(base["type"]) if base else None
    if not cat:
        raise TradeError(f"no trade category for the item in {slot}")
    filters, unknown = [], []
    for m in mods:
        f = stat_filter(m)
        (filters.append(f) if f else unknown.append(m))
    if not filters:
        raise TradeError("none of the wanted mods is known to the trade site: " + "; ".join(unknown))
    prices = default_prices()
    league = league or prices.league
    query = {"query": {"status": {"option": "securable"},
                       "stats": [{"type": "and", "filters": filters}],
                       "filters": {"type_filters": {"filters": {"category": {"option": cat},
                                                                 "rarity": {"option": "nonunique"}}}}},
             "sort": {"price": "asc"}}
    res = _req(f"{API}/search/poe2/{urllib.parse.quote(league)}", query)
    ids, qid = res.get("result", []), res.get("id")
    link = f"{SITE}/{urllib.parse.quote(league)}/{qid}" if qid else None
    if not ids:
        return {"slot": slot, "league": league, "found": 0, "items": [], "link": link, "unknown_mods": unknown}
    fetched = _req(f"{API}/fetch/{','.join(ids[:limit])}?query={qid}&realm=poe2")
    rates = prices.rates
    items = []
    for r in fetched.get("result", []):
        if not r:
            continue
        price = (r.get("listing") or {}).get("price") or {}
        amount, cur_name = price.get("amount"), price.get("currency")
        div = None
        if amount is not None and cur_name:
            if cur_name == "divine":
                div = amount
            else:
                p = prices.price(CURRENCY_NAME.get(cur_name, cur_name))
                div = amount * p["divine"] if p else None
        if budget_divine is not None and div is not None and div > budget_divine:
            continue
        it = r["item"]
        raw = _raw_from_listing(it)
        try:
            w = pob.whatif(slot=slot, item_raw=raw)
        except Exception:
            continue
        w.pop("points", None)
        ex = obj.explain(w, session.base)
        grants = [v[0] for g in it.get("grantedSkills") or [] for v in (g.get("values") or [])]
        items.append({"name": f"{it.get('name') or ''} {it.get('typeLine') or ''}".strip(), "ilvl": it.get("ilvl"),
                      "grants_skill": grants,
                      "price": f"{amount:g} {cur_name}" if amount is not None else "?",
                      "price_divine": round(div, 3) if div is not None else None,
                      "mods": [_clean_markup(x) for x in (it.get("explicitMods") or [])],
                      "implicits": [_clean_markup(x) for x in (it.get("implicitMods") or [])],
                      "corrupted": bool(it.get("corrupted")), **ex, "changes": diff(session.base, w),
                      "seller_online": bool(((r.get("listing") or {}).get("account") or {}).get("online"))})
    items.sort(key=lambda x: x["score"], reverse=True)
    warn = None
    if cur:
        own = [ln.split(":", 1)[1].strip() for ln in cur["raw"].split("\n") if ln.split("}")[-1].startswith("Grants Skill:")]
        if own:
            warn = (f"Twój obecny item daje skill: {', '.join(own)}. Item bez tego skilla go zabierze; "
                    "liczby niżej już to uwzględniają.")
    return {"slot": session.pob.resolve_slot(slot), "league": league, "found": len(ids), "items": items[:5],
            "link": link, "unknown_mods": unknown, "warning": warn,
            "note": "Cheapest listings with these mods, each measured in PoB in your slot. Prices are what sellers "
                    "ask; check the listing before buying."}
