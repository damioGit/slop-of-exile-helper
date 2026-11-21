"""Item prices from poe.ninja (Path of Exile 2), with a disk cache.

Two poe.ninja endpoints:
  /poe2/api/economy/exchange/current/overview?league=..&type=Currency|Essences|LineageSupportGems|...
  /poe2/api/economy/stash/current/item/overview?league=..&type=UniqueArmours|...
Both quote `primaryValue` in Divine Orbs; `core.rates` gives exalted/chaos per divine.

League: SOE_LEAGUE env var, else the newest softcore league poe.ninja indexes (not Standard).
Cache: data/prices/<league>/<type>.json, refreshed after `ttl` seconds; when poe.ninja cannot be
reached, the last cached copy is used and marked stale. Prices are never invented: unknown = None.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "prices"
API = "https://poe.ninja/poe2/api"
UA = "Mozilla/5.0 (compatible; slop-of-exile-helper)"

EXCHANGE_TYPES = ["Currency", "Essences", "Runes", "Fragments", "SoulCores", "UncutGems", "LineageSupportGems",
                  "Abyss", "Ritual", "Expedition", "Delirium", "Breach"]
UNIQUE_TYPES = ["UniqueWeapons", "UniqueArmours", "UniqueAccessories", "UniqueFlasks", "UniqueCharms", "UniqueJewels"]


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


class Prices:
    def __init__(self, league: str | None = None, ttl: int = 3600, offline: bool = False, cache_dir: Path = CACHE):
        self.ttl, self.offline, self.cache_dir = ttl, offline, cache_dir
        self._league = league or os.environ.get("SOE_LEAGUE")
        self._league_pinned = bool(self._league)
        self._league_at = 0.0
        self._index: dict[str, dict] | None = None
        self._built_at = 0.0
        self.rates = {"exalted": None, "chaos": None}
        self.stale: list[str] = []
        self.errors: list[str] = []

    # ---- league -----------------------------------------------------------------
    @property
    def league(self) -> str:
        # a new league (e.g. a launch) shows up within a day without restarting the app
        if self._league and (self._league_pinned or self.offline or time.time() - self._league_at < 86400):
            return self._league
        self._league_at = time.time()
        cached = self.cache_dir / "_league.json"
        try:
            if self.offline:
                raise OSError("offline")
            state = _get(f"{API}/data/index-state")
            leagues = [lg["name"] for lg in state.get("economyLeagues", [])
                       if lg.get("indexed") and not lg.get("hardcore") and lg["name"] != "Standard"]
            self._league = leagues[0] if leagues else "Standard"
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps({"league": self._league, "at": time.time()}), encoding="utf-8")
        except Exception:
            self._league = json.loads(cached.read_text(encoding="utf-8"))["league"] if cached.exists() else "Standard"
        return self._league

    # ---- fetching ------------------------------------------------------------------
    def _file(self, kind: str, typ: str) -> Path:
        return self.cache_dir / re.sub(r"\W+", "_", self.league) / f"{kind}-{typ}.json"

    def _load(self, kind: str, typ: str) -> dict | None:
        f = self._file(kind, typ)
        fresh = f.exists() and time.time() - f.stat().st_mtime < self.ttl
        if fresh or self.offline:
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
        url = f"{API}/economy/{kind}/current/{'overview' if kind == 'exchange' else 'item/overview'}?" + \
              urllib.parse.urlencode({"league": self.league, "type": typ})
        try:
            data = _get(url)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as e:
            self.errors.append(f"{typ}: {type(e).__name__}")
            if f.exists():
                self.stale.append(typ)
                return json.loads(f.read_text(encoding="utf-8"))
            return None

    def _build_index(self):
        jobs = [("exchange", t) for t in EXCHANGE_TYPES] + [("stash", t) for t in UNIQUE_TYPES]
        with ThreadPoolExecutor(6) as ex:
            results = list(ex.map(lambda kt: (kt, self._load(*kt)), jobs))
        idx: dict[str, dict] = {}
        for (kind, typ), data in results:
            if not data:
                continue
            rates = data.get("core", {}).get("rates", {})
            if rates.get("exalted") and not self.rates["exalted"]:
                self.rates = {"exalted": rates.get("exalted"), "chaos": rates.get("chaos")}
            if kind == "exchange":
                names = {i["id"]: i["name"] for i in data.get("items", [])}
                for ln in data.get("lines", []):
                    name = names.get(ln["id"])
                    if name and ln.get("primaryValue") is not None:
                        idx.setdefault(_norm(name), {"name": name, "divine": ln["primaryValue"], "type": typ,
                                                     "volume": ln.get("volumePrimaryValue")})
            else:
                for ln in data.get("lines", []):
                    if ln.get("primaryValue") is None:
                        continue
                    rec = {"name": ln["name"], "base": ln.get("baseType"), "divine": ln["primaryValue"], "type": typ,
                           "listings": ln.get("listingCount"), "corrupted": ln.get("corrupted")}
                    key = _norm(ln["name"])
                    # several variants: keep the cheapest uncorrupted listing as "the price"
                    old = idx.get(key)
                    if old is None or (rec["divine"] < old["divine"] and not rec["corrupted"]):
                        idx[key] = rec
        # Divine Orb itself is the unit
        idx.setdefault("divine orb", {"name": "Divine Orb", "divine": 1.0, "type": "Currency"})
        self._index = idx

    @property
    def index(self) -> dict[str, dict]:
        # rebuilt after the cache TTL, so an app that runs for days still shows today's prices
        if self._index is None or (not self.offline and time.time() - self._built_at > self.ttl):
            self.stale, self.errors = [], []
            self._build_index()
            self._built_at = time.time()
        return self._index

    # ---- lookups -------------------------------------------------------------------
    def price(self, name: str) -> dict | None:
        """{'name', 'divine', 'exalted', 'chaos', 'text', 'type'} or None when poe.ninja has no price."""
        rec = self.index.get(_norm(name))
        if not rec:
            return None
        return {**rec, **self.convert(rec["divine"])}

    def convert(self, divine: float | None) -> dict:
        if divine is None:
            return {"text": "?"}
        ex, ch = self.rates.get("exalted"), self.rates.get("chaos")
        res = {"exalted": round(divine * ex, 1) if ex else None, "chaos": round(divine * ch, 1) if ch else None}
        res["text"] = self.fmt(divine)
        return res

    def fmt(self, divine: float | None) -> str:
        if divine is None:
            return "?"
        if divine >= 1:
            return f"{divine:,.1f} div".replace(",", " ")
        ex = self.rates.get("exalted")
        return f"{divine * ex:,.0f} ex".replace(",", " ") if ex else f"{divine:.3f} div"

    def status(self) -> dict:
        idx = self.index
        return {"league": self.league, "items": len(idx), "divine_in_exalted": self.rates.get("exalted"),
                "divine_in_chaos": self.rates.get("chaos"), "stale_types": self.stale, "errors": self.errors,
                "source": "poe.ninja"}


_default: Prices | None = None


def default_prices() -> Prices:
    global _default
    if _default is None:
        _default = Prices(offline=os.environ.get("SOE_PRICES_OFFLINE") == "1",
                          cache_dir=Path(os.environ["SOE_PRICES_DIR"]) if os.environ.get("SOE_PRICES_DIR") else CACHE)
    return _default
