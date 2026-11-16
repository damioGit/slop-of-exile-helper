"""Fetch public ladder characters from poe.ninja (PoE2) into data/corpus/ for testing.

One character per ascendancy (the highest on the ladder), plus extra ones up to --max.
Saved per character: the PoB code and poe.ninja's own numbers (skills DPS, defensive stats) to
compare against. Other players' characters are kept out of the repository (data/ is gitignored).

python scripts/fetch_corpus.py [--per-class 1] [--max 40]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "corpus"
API = "https://poe.ninja/poe2/api"
UA = "Mozilla/5.0 (compatible; slop-of-exile-helper)"
DELAY = 6.0  # seconds between requests; poe.ninja rate-limits hard


def get(url: str, raw: bool = False, tries: int = 4):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == tries - 1:
                raise
            time.sleep(30 * (attempt + 1))  # rate limited: back off


# ---- minimal protobuf reader: collect every repeated string field by path ----
def _varint(b: bytes, i: int) -> tuple[int, int]:
    shift = res = 0
    while True:
        c = b[i]
        i += 1
        res |= (c & 0x7F) << shift
        if not c & 0x80:
            return res, i
        shift += 7


def _walk(b: bytes, path: tuple, out: dict, depth: int = 0):
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        field, wt = key >> 3, key & 7
        if wt == 0:
            _, i = _varint(b, i)
        elif wt == 1:
            i += 8
        elif wt == 5:
            i += 4
        elif wt == 2:
            n, i = _varint(b, i)
            chunk = b[i:i + n]
            i += n
            p = path + (field,)
            try:
                s = chunk.decode("utf-8")
                if s.isprintable():
                    out.setdefault(p, []).append(s)
            except UnicodeDecodeError:
                pass
            if depth < 6:
                try:
                    _walk(chunk, p, out, depth + 1)
                except (IndexError, ValueError):
                    pass
        else:
            raise ValueError("bad wire type")


def ladder(version: str, snapshot: str, cls: str | None = None) -> list[tuple[str, str]]:
    q = {"overview": snapshot, **({"class": cls} if cls else {})}
    blob = get(f"{API}/builds/{version}/search?" + urllib.parse.urlencode(q), raw=True)
    fields: dict = {}
    _walk(blob, (), fields)
    # columns are stored one after another in one repeated field: [names..., accounts..., ...]
    values = max(fields.values(), key=len)
    is_acc = [bool(re.fullmatch(r".+-\d{4}", s)) for s in values]
    start = is_acc.index(True)
    end = start
    while end < len(values) and is_acc[end]:
        end += 1
    n = end - start
    accounts, names = values[start:end], values[start - n:start]
    return list(zip(accounts, names))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default=None, help="poe.ninja build league url, e.g. runesofaldur")
    ap.add_argument("--per-class", type=int, default=1)
    ap.add_argument("--max", type=int, default=40)
    a = ap.parse_args()
    state = get(f"{API}/data/index-state")
    cands = [s for s in state["snapshotVersions"] if (a.league and s["url"] == a.league)
             or (not a.league and "hc" not in s["url"] and "ssf" not in s["url"] and s["url"] != "standard")]
    chars, snap = [], None
    for snap in cands:  # a brand new league can have an empty ladder: take the next one
        try:
            chars = ladder(snap["version"], snap["snapshotName"])
        except (StopIteration, Exception):
            chars = []
        print(f"league {snap['name']} ({snap['version']}): {len(chars)} characters", flush=True)
        if chars:
            break
    OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT))
    from soe.kb import KB

    ascendancies = [a_ for asc in KB().classes().values() for a_ in asc]
    have = {json.loads(f.read_text(encoding="utf-8"))["class"] for f in OUT.glob("*.json")}
    saved = 0
    for asc in ascendancies:
        if saved >= a.max:
            break
        if asc in have:
            print(f"  have {asc}", flush=True)
            continue
        time.sleep(DELAY)
        try:
            top = ladder(snap["version"], snap["snapshotName"], asc)[: a.per_class]
        except Exception as e:
            print(f"  {asc}: no ladder ({type(e).__name__})", flush=True)
            continue
        for acc, name in top:
            time.sleep(DELAY)
            q = urllib.parse.urlencode({"account": acc, "name": name, "overview": snap["snapshotName"], "timeMachine": ""})
            try:
                c = get(f"{API}/builds/{snap['version']}/character?{q}")
            except Exception as e:
                print(f"  skip {acc}/{name}: {e}", flush=True)
                continue
            if not c.get("pathOfBuildingExport"):
                continue
            cls = c.get("class") or asc
            skills = [{"name": d.get("name"), "dps": d.get("dps"), "dotDps": d.get("dotDps")}
                      for s in c.get("skills", []) for d in (s.get("dps") or [])]
            rec = {"account": acc, "name": name, "class": cls, "level": c.get("level"), "league": c.get("league"),
                   "code": c["pathOfBuildingExport"], "ninja_defensive": c.get("defensiveStats"),
                   "ninja_skills": skills}
            safe = re.sub(r"[^\w-]+", "_", f"{cls}-{name}")[:80]
            (OUT / f"{safe}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            saved += 1
            print(f"  {cls:<22} {name}", flush=True)
    print(f"saved {saved} characters to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
