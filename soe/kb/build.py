"""Build data/kb.sqlite from the game data PoB has loaded.

python -m soe.kb.build      (or: soe kb build)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "kb.sqlite"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE gems (
    id TEXT PRIMARY KEY, name TEXT, kind TEXT, gem_type TEXT, tags TEXT, tag_string TEXT,
    req_str INT, req_dex INT, req_int INT, tier INT, max_level INT,
    skill_id TEXT, description TEXT, stats_text TEXT,
    skill_types TEXT, minion_types TEXT, require_types TEXT, add_types TEXT, exclude_types TEXT,
    family TEXT, cast_time REAL, cannot_be_supported INT
);
CREATE INDEX gems_name ON gems(name COLLATE NOCASE);
CREATE TABLE skills (
    id TEXT PRIMARY KEY, name TEXT, description TEXT, support INT, stats_text TEXT,
    skill_types TEXT, minion_types TEXT, require_types TEXT, exclude_types TEXT
);
CREATE INDEX skills_name ON skills(name COLLATE NOCASE);
CREATE TABLE mods (
    id TEXT, domain TEXT, type TEXT, affix TEXT, text TEXT, level INT, grp TEXT,
    tags TEXT, weight_keys TEXT, weight_vals TEXT, spawns_on TEXT,
    PRIMARY KEY (domain, id)
);
CREATE INDEX mods_grp ON mods(grp);
CREATE TABLE bases (
    name TEXT PRIMARY KEY, type TEXT, sub_type TEXT, tags TEXT, implicit TEXT, req TEXT, props TEXT, hidden INT
);
CREATE TABLE uniques (
    name TEXT, base TEXT, slot_type TEXT, league TEXT, req_level INT, implicits TEXT, mods TEXT, raw TEXT,
    PRIMARY KEY (name, base)
);
CREATE INDEX uniques_name ON uniques(name COLLATE NOCASE);
CREATE TABLE nodes (
    id INT PRIMARY KEY, name TEXT, type TEXT, ascendancy TEXT, stats TEXT, linked TEXT, x REAL, y REAL
);
CREATE INDEX nodes_name ON nodes(name COLLATE NOCASE);
CREATE TABLE classes (class TEXT, ascendancy TEXT);
CREATE VIRTUAL TABLE search USING fts5(kind UNINDEXED, ref UNINDEXED, name, body, tokenize = 'unicode61 remove_diacritics 2');
"""

_BRACES = re.compile(r"\{[^}]*\}")
_VARIANT = re.compile(r"\{variant:([\d,]+)\}")


def parse_unique(raw: str) -> dict:
    """PoB unique text block -> name, base, league, requirement, implicits and mods of the current variant."""
    lines = [ln.strip() for ln in raw.strip().splitlines() if ln.strip()]
    name, base = lines[0], lines[1]
    variants, league, req_level, implicits_n, body = [], None, None, 0, []
    for ln in lines[2:]:
        if ln.startswith("Variant:"):
            variants.append(ln[8:].strip())
        elif ln.startswith("League:"):
            league = ln[7:].strip()
        elif ln.startswith("Requires Level"):
            m = re.search(r"\d+", ln)
            req_level = int(m.group()) if m else None
        elif ln.startswith("Implicits:"):
            implicits_n = int(ln.split(":")[1])
        elif re.match(r"^(Source|Selected Variant|Has Alt Variant|Limited to|Radius|Item Level|Quality|Sockets|LevelReq|Requires):", ln):
            continue
        else:
            body.append(ln)
    current = len(variants)  # PoB lists the current variant last
    kept_implicit, kept_mods = [], []
    for i, ln in enumerate(body):
        m = _VARIANT.search(ln)
        if m and current and str(current) not in m.group(1).split(","):
            continue
        text = _BRACES.sub("", ln).strip()
        (kept_implicit if i < implicits_n else kept_mods).append(text)
    return {"name": name, "base": base, "league": league, "req_level": req_level,
            "implicits": kept_implicit, "mods": kept_mods}


def _j(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def build(db_path: Path = DB_PATH, game_data: dict | None = None, pob_version: str | None = None) -> dict:
    t0 = time.perf_counter()
    if game_data is None:
        from soe.engine.pob import PoB

        pob = PoB()
        pob.new_build()
        game_data = pob.export_game_data()
    if pob_version is None:
        pob_version = (ROOT / "POB_VERSION").read_text().strip()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    search = []

    for g in game_data["gems"]:
        s = g.get("skill") or {}
        kind = "support" if s.get("support") else "active"
        con.execute(
            "INSERT OR REPLACE INTO gems VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (g["id"], g["name"], kind, g.get("gem_type"), _j(g.get("tags", [])), g.get("tag_string"),
             g.get("req_str"), g.get("req_dex"), g.get("req_int"), g.get("tier"), g.get("max_level"),
             g.get("skill_id"), s.get("description"), _j(s.get("stats_text", [])),
             _j(s.get("skill_types", [])), _j(s.get("minion_types", [])), _j(s.get("require_types", [])),
             _j(s.get("add_types", [])), _j(s.get("exclude_types", [])), _j(s.get("family", [])),
             s.get("cast_time"), int(bool(s.get("cannot_be_supported")))),
        )
        body = " ".join([kind, g.get("gem_type") or "", g.get("tag_string") or "", " ".join(g.get("tags", [])),
                         s.get("description") or "", " ".join(s.get("stats_text", [])), " ".join(s.get("skill_types", []))])
        search.append(("gem", g["id"], g["name"], body))

    for s in game_data["skills"]:
        con.execute(
            "INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?,?,?,?,?)",
            (s["id"], s["name"], s.get("description"), int(bool(s.get("support"))), _j(s.get("stats_text", [])),
             _j(s.get("skill_types", [])), _j(s.get("minion_types", [])), _j(s.get("require_types", [])),
             _j(s.get("exclude_types", []))),
        )
        search.append(("skill", s["id"], s["name"], " ".join([s.get("description") or "", " ".join(s.get("stats_text", []))])))

    for m in game_data["mods"]:
        keys, vals = m.get("weight_keys", []), m.get("weight_vals", [])
        spawns = [k for k, v in zip(keys, vals) if v and k != "default"]
        text = " / ".join(m.get("text", []))
        con.execute(
            "INSERT OR REPLACE INTO mods VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (m["id"], m["domain"], m.get("type"), m.get("affix"), text, m.get("level"), m.get("group"),
             _j(m.get("tags", [])), _j(keys), _j(vals), _j(spawns)),
        )
        search.append(("mod", f"{m['domain']}:{m['id']}", m.get("affix") or m["id"],
                       " ".join([text, m.get("type") or "", m["domain"], " ".join(m.get("tags", [])), " ".join(spawns)])))

    for b in game_data["bases"]:
        con.execute(
            "INSERT OR REPLACE INTO bases VALUES (?,?,?,?,?,?,?,?)",
            (b["name"], b.get("type"), b.get("sub_type"), _j(b.get("tags", [])), b.get("implicit"),
             _j(b.get("req", {})), _j(b.get("props", {})), int(bool(b.get("hidden")))),
        )
        if not b.get("hidden"):
            search.append(("base", b["name"], b["name"], " ".join([b.get("type") or "", b.get("sub_type") or "", b.get("implicit") or ""])))

    for u in game_data["uniques"]:
        p = parse_unique(u["raw"])
        con.execute(
            "INSERT OR REPLACE INTO uniques VALUES (?,?,?,?,?,?,?,?)",
            (p["name"], p["base"], u["slot_type"], p["league"], p["req_level"], _j(p["implicits"]), _j(p["mods"]), u["raw"]),
        )
        search.append(("unique", f"{p['name']}|{p['base']}", p["name"],
                       " ".join([p["base"], u["slot_type"], " ".join(p["implicits"]), " ".join(p["mods"])])))

    for n in game_data["nodes"]:
        con.execute(
            "INSERT OR REPLACE INTO nodes VALUES (?,?,?,?,?,?,?,?)",
            (n["id"], n["name"], n.get("type"), n.get("ascendancy"), _j(n.get("stats", [])), _j(n.get("linked", [])),
             n.get("x"), n.get("y")),
        )
        if n.get("type") in ("Notable", "Keystone") or n.get("ascendancy"):
            search.append(("node", str(n["id"]), n["name"],
                           " ".join([n.get("type") or "", n.get("ascendancy") or "", " ".join(n.get("stats", []))])))

    for c in game_data["classes"]:
        for a in c["ascendancies"] or [None]:
            con.execute("INSERT INTO classes VALUES (?,?)", (c["name"], a))
            if a:
                search.append(("ascendancy", a, a, c["name"]))

    con.executemany("INSERT INTO search VALUES (?,?,?,?)", search)
    meta = {"schema": SCHEMA_VERSION, "pob_version": pob_version, "tree_version": game_data.get("tree_version"),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    counts = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
              for t in ("gems", "skills", "mods", "bases", "uniques", "nodes")}
    con.commit()
    con.close()
    tmp.replace(db_path)
    return {**meta, **counts, "seconds": round(time.perf_counter() - t0, 1), "path": str(db_path)}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
