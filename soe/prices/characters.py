"""Import a character from poe.ninja (Path of Exile 2): account + character name, or a poe.ninja link.

poe.ninja keeps public characters with a ready Path of Building export. The character endpoint needs
the league's snapshot version, so the importer tries the current leagues (or the one in the link)
until it finds the character. Only public characters that poe.ninja has seen can be imported; private
profiles and characters it never indexed are not there. (Path of Building itself logs in to GGG's
official API with its own registered app id; that route needs this tool to be registered with GGG.)
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://poe.ninja/poe2/api"
UA = "Mozilla/5.0 (compatible; slop-of-exile-helper)"
_LINK = re.compile(r"poe\.ninja/poe2/builds/(?P<league>[^/]+)/character/(?P<account>[^/]+)/(?P<name>[^/?#]+)")


def _get(url: str, tries: int = 3):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def normalize_account(account: str) -> str:
    """'Gracz#1234' (in-game) -> 'Gracz-1234' (poe.ninja)."""
    return account.strip().replace("#", "-")


def parse_ref(ref: str, name: str | None = None) -> tuple[str, str, str | None]:
    """(account, character, league url or None) from a poe.ninja link or 'account' + name."""
    m = _LINK.search(ref)
    if m:
        return (urllib.parse.unquote(m["account"]), urllib.parse.unquote(m["name"]), m["league"])
    if name:
        return normalize_account(ref), name.strip(), None
    if "/" in ref:
        acc, nm = ref.split("/", 1)
        return normalize_account(acc), nm.strip(), None
    raise ValueError("give a poe.ninja character link, or an account (Name#1234) and a character name")


class Blocked(ValueError):
    """poe.ninja refused the request (rate limit or its bot check). Never worked around: wait and retry."""


def _state() -> dict:
    """poe.ninja league index; the last good copy is kept on disk for when poe.ninja refuses requests."""
    from soe.prices.ninja import CACHE

    f = CACHE / "_index-state.json"
    try:
        state = _get(f"{API}/data/index-state")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(state), encoding="utf-8")
        return state
    except urllib.error.HTTPError as e:
        if e.code in (403, 429) and f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        if e.code in (403, 429):
            raise Blocked("poe.ninja is refusing requests right now (rate limit / bot check after many requests). "
                          "Try again later, or paste the PoB code from the character page.") from e
        raise


def _snapshots(league_url: str | None) -> list[dict]:
    state = _state()
    snaps = state.get("snapshotVersions", [])
    if league_url:
        return [s for s in snaps if s["url"] == league_url] or snaps
    # softcore trade leagues first, then the rest (hc, ssf, standard, private)
    return sorted(snaps, key=lambda s: ("(PL" in s["name"], "hc" in s["url"], "ssf" in s["url"], s["url"] == "standard"))


def fetch_character(ref: str, name: str | None = None, max_leagues: int = 8) -> dict:
    """{account, name, league, class, level, code, updated} or a ValueError saying why not found."""
    account, char, league_url = parse_ref(ref, name)
    tried = []
    for snap in _snapshots(league_url)[:max_leagues]:
        q = urllib.parse.urlencode({"account": account, "name": char, "overview": snap["snapshotName"],
                                    "timeMachine": ""})
        try:
            c = _get(f"{API}/builds/{snap['version']}/character?{q}")
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked("poe.ninja is refusing requests right now (rate limit / bot check). Try again later, "
                              "or open the character on poe.ninja and paste its PoB code.") from e
            tried.append(f"{snap['name']} ({e.code})")
            continue
        if c and c.get("pathOfBuildingExport"):
            return {"account": c.get("account", account), "name": c.get("name", char), "league": c.get("league"),
                    "class": c.get("class"), "level": c.get("level"), "code": c["pathOfBuildingExport"],
                    "updated": c.get("updatedUtc"), "last_checked": c.get("lastCheckedUtc"),
                    "source": "poe.ninja"}
        tried.append(snap["name"])
    raise ValueError(f"{account}/{char} not found on poe.ninja (checked: {', '.join(tried)}). The profile may be "
                     "private, the character too low level, or not indexed yet.")
