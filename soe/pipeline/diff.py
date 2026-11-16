"""What changed between two knowledge bases (= two PoB data versions): gems, uniques, passives, mods, bases."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _rows(path: Path, sql: str) -> list[dict]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql)]
    finally:
        con.close()


def _j(v):
    return json.loads(v) if isinstance(v, str) and v[:1] in "[{" else v


def _by_name(rows, key="name"):
    out = {}
    for r in rows:
        out.setdefault(r[key], r)
    return out


def _lines_diff(a: list[str], b: list[str]) -> dict:
    sa, sb = set(a or []), set(b or [])
    return {"removed": sorted(sa - sb), "added": sorted(sb - sa)}


def diff_kb(old: Path, new: Path) -> dict:
    meta_old = {r["key"]: r["value"] for r in _rows(old, "SELECT * FROM meta")}
    meta_new = {r["key"]: r["value"] for r in _rows(new, "SELECT * FROM meta")}
    res: dict = {"old": meta_old, "new": meta_new}

    # gems (by name; tiers of the same support share a name only per tier, so name is fine)
    g_old = _by_name(_rows(old, "SELECT name, kind, stats_text, tag_string, skill_types FROM gems"))
    g_new = _by_name(_rows(new, "SELECT name, kind, stats_text, tag_string, skill_types FROM gems"))
    changed = {}
    for n in sorted(set(g_old) & set(g_new)):
        d = _lines_diff(_j(g_old[n]["stats_text"]), _j(g_new[n]["stats_text"]))
        if d["added"] or d["removed"]:
            changed[n] = d
    res["gems"] = {"added": sorted(set(g_new) - set(g_old)), "removed": sorted(set(g_old) - set(g_new)), "changed": changed}

    # uniques
    u_old = _by_name(_rows(old, "SELECT name, base, implicits, mods FROM uniques"))
    u_new = _by_name(_rows(new, "SELECT name, base, implicits, mods FROM uniques"))
    changed = {}
    for n in sorted(set(u_old) & set(u_new)):
        d = _lines_diff(_j(u_old[n]["implicits"]) + _j(u_old[n]["mods"]), _j(u_new[n]["implicits"]) + _j(u_new[n]["mods"]))
        if d["added"] or d["removed"]:
            changed[n] = d
    res["uniques"] = {"added": sorted(set(u_new) - set(u_old)), "removed": sorted(set(u_old) - set(u_new)),
                      "changed": changed}

    # notables and keystones (by name, ids can move between tree versions)
    q = "SELECT name, type, stats FROM nodes WHERE type IN ('Notable','Keystone') AND ascendancy IS NULL"
    n_old, n_new = _by_name(_rows(old, q)), _by_name(_rows(new, q))
    changed = {}
    for n in sorted(set(n_old) & set(n_new)):
        d = _lines_diff(_j(n_old[n]["stats"]), _j(n_new[n]["stats"]))
        if d["added"] or d["removed"]:
            changed[n] = d
    res["passives"] = {"added": sorted(set(n_new) - set(n_old)), "removed": sorted(set(n_old) - set(n_new)),
                       "changed": changed}

    # ascendancy nodes
    q = "SELECT ascendancy || ': ' || name AS name, stats FROM nodes WHERE ascendancy IS NOT NULL AND type != 'AscendClassStart'"
    a_old, a_new = _by_name(_rows(old, q)), _by_name(_rows(new, q))
    changed = {n: _lines_diff(_j(a_old[n]["stats"]), _j(a_new[n]["stats"])) for n in sorted(set(a_old) & set(a_new))}
    res["ascendancies"] = {"added": sorted(set(a_new) - set(a_old)), "removed": sorted(set(a_old) - set(a_new)),
                           "changed": {k: v for k, v in changed.items() if v["added"] or v["removed"]}}

    # item mods: families and top tiers on the main domain
    q = "SELECT grp, type, MAX(level) AS top_level, COUNT(*) AS tiers FROM mods WHERE domain = 'Item' GROUP BY grp, type"
    m_old = {(r["grp"], r["type"]): r for r in _rows(old, q)}
    m_new = {(r["grp"], r["type"]): r for r in _rows(new, q)}
    res["mod_families"] = {
        "added": sorted(f"{t} {g}" for g, t in set(m_new) - set(m_old)),
        "removed": sorted(f"{t} {g}" for g, t in set(m_old) - set(m_new)),
        "tiers_changed": sorted(f"{t} {g}: {m_old[(g, t)]['tiers']} -> {m_new[(g, t)]['tiers']} tiers"
                                for g, t in set(m_old) & set(m_new) if m_old[(g, t)]["tiers"] != m_new[(g, t)]["tiers"]),
    }
    b_old = {r["name"] for r in _rows(old, "SELECT name FROM bases WHERE hidden = 0")}
    b_new = {r["name"] for r in _rows(new, "SELECT name FROM bases WHERE hidden = 0")}
    res["bases"] = {"added": sorted(b_new - b_old), "removed": sorted(b_old - b_new)}
    res["counts"] = {k: {"added": len(v.get("added", [])), "removed": len(v.get("removed", [])),
                         "changed": len(v.get("changed", v.get("tiers_changed", [])))}
                     for k, v in res.items() if isinstance(v, dict) and "added" in v}
    return res


def _md_changes(title: str, block: dict, limit: int = 60) -> list[str]:
    out = [f"## {title}", ""]
    if block.get("added"):
        out.append(f"**Nowe ({len(block['added'])}):** " + ", ".join(block["added"][:limit])
                   + (" …" if len(block["added"]) > limit else ""))
    if block.get("removed"):
        out.append(f"\n**Usunięte ({len(block['removed'])}):** " + ", ".join(block["removed"][:limit]))
    ch = block.get("changed") or {}
    if ch:
        out.append(f"\n**Zmienione ({len(ch)}):**\n")
        for name, d in list(ch.items())[:limit]:
            out.append(f"- **{name}**")
            for ln in d["removed"]:
                out.append(f"  - ~~{ln}~~")
            for ln in d["added"]:
                out.append(f"  - {ln}")
        if len(ch) > limit:
            out.append(f"- … i {len(ch) - limit} więcej (pełna lista w JSON)")
    if not (block.get("added") or block.get("removed") or ch or block.get("tiers_changed")):
        out.append("Bez zmian.")
    if block.get("tiers_changed"):
        out.append(f"\n**Zmiana liczby tierów ({len(block['tiers_changed'])}):** " + "; ".join(block["tiers_changed"][:limit]))
    out.append("")
    return out


def report_md(d: dict) -> str:
    lines = [f"# Zmiany w danych: PoB {d['old'].get('pob_version')} → {d['new'].get('pob_version')}", "",
             f"Drzewko {d['old'].get('tree_version')} → {d['new'].get('tree_version')}. "
             f"Bazy wiedzy z {d['old'].get('built_at')} i {d['new'].get('built_at')}.", "",
             "| Co | Nowe | Usunięte | Zmienione |", "|---|---|---|---|"]
    for k, c in d["counts"].items():
        lines.append(f"| {k} | {c['added']} | {c['removed']} | {c['changed']} |")
    lines.append("")
    for key, title in (("gems", "Gemy"), ("uniques", "Unikaty"), ("passives", "Notable i keystone"),
                       ("ascendancies", "Ascendancy"), ("mod_families", "Mody na itemach"), ("bases", "Bazy itemów")):
        lines += _md_changes(title, d[key])
    return "\n".join(lines)
