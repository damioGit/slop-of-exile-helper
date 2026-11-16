"""Read-only queries over data/kb.sqlite."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from soe.kb.build import current_db_path

_JSON_COLS = {
    "tags", "stats_text", "skill_types", "minion_types", "require_types", "add_types", "exclude_types",
    "family", "weight_keys", "weight_vals", "spawns_on", "req", "props", "implicits", "mods", "stats", "linked",
}


def type_expr_match(expr: list[str], types: set[str]) -> bool:
    """PoB's skill type expression (postfix with AND/OR/NOT); True if any stack value ends up true."""
    stack: list[bool] = []
    for tok in expr:
        if tok == "OR":
            other = stack.pop()
            stack[-1] = stack[-1] or other
        elif tok == "AND":
            other = stack.pop()
            stack[-1] = stack[-1] and other
        elif tok == "NOT":
            stack[-1] = not stack[-1]
        else:
            stack.append(tok in types)
    return any(stack)


def can_support(support: dict, active: dict) -> bool:
    """Same rule as PoB's calcLib.canGrantedEffectSupportActiveSkill, on KB rows."""
    if active.get("cannot_be_supported"):
        return False
    types = set(active.get("skill_types") or [])
    minion = set(active.get("minion_types") or [])
    exclude = support.get("exclude_types") or []
    if exclude and type_expr_match(exclude, types):
        return False
    require = support.get("require_types") or []
    return not require or type_expr_match(require, types | minion)


def _fts_query(text: str) -> str:
    words = re.findall(r"[\w']+", text.lower())
    return " AND ".join(f'"{w}"*' for w in words)


class KB:
    def __init__(self, path: Path | None = None):
        path = path or current_db_path()
        if not Path(path).exists():
            raise FileNotFoundError(f"{path} missing; run: soe kb build")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    def _rows(self, sql: str, args=()) -> list[dict]:
        out = []
        for r in self.con.execute(sql, args):
            d = dict(r)
            for k in _JSON_COLS & d.keys():
                if isinstance(d[k], str):
                    d[k] = json.loads(d[k])
            out.append(d)
        return out

    def meta(self) -> dict:
        return {r["key"]: r["value"] for r in self.con.execute("SELECT * FROM meta")}

    # ---- search -------------------------------------------------------------------
    def search(self, text: str, kind: str | None = None, limit: int = 20) -> list[dict]:
        """Full-text search over gems, skills, mods, bases, uniques, notables/keystones and ascendancies.
        Words are AND-ed and prefix-matched; names weigh more than descriptions."""
        q = _fts_query(text)
        if not q:
            return []
        sql = ("SELECT kind, ref, name, snippet(search, 3, '[', ']', '…', 12) AS snippet, "
               "bm25(search, 10.0, 1.0) AS score FROM search WHERE search MATCH ?")
        args: list = [q]
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        sql += " ORDER BY score LIMIT ?"
        args.append(limit)
        return self._rows(sql, args)

    # ---- lookups ---------------------------------------------------------------------
    def gem(self, name: str) -> dict | None:
        rows = self._rows("SELECT * FROM gems WHERE name = ? COLLATE NOCASE ORDER BY tier DESC", (name,))
        if not rows:
            hit = self.search(name, kind="gem", limit=1)
            rows = self._rows("SELECT * FROM gems WHERE id = ?", (hit[0]["ref"],)) if hit else []
        return rows[0] if rows else None

    def gems(self, kind: str | None = None, tag: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM gems WHERE 1=1", []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if tag:
            sql += " AND EXISTS (SELECT 1 FROM json_each(gems.tags) WHERE value = ?)"
            args.append(tag)
        return self._rows(sql + " ORDER BY name", args)

    def supports_for(self, gem_name: str) -> list[dict]:
        """Support gems PoB would allow on this active gem."""
        active = self.gem(gem_name)
        if not active or active["kind"] != "active":
            return []
        seen, res = set(), []
        for s in self.gems(kind="support"):
            if s["name"] not in seen and can_support(s, active):
                seen.add(s["name"])
                res.append(s)
        return res

    def unique(self, name: str) -> list[dict]:
        rows = self._rows("SELECT * FROM uniques WHERE name = ? COLLATE NOCASE", (name,))
        if not rows:
            hit = self.search(name, kind="unique", limit=1)
            if hit:
                n, b = hit[0]["ref"].split("|", 1)
                rows = self._rows("SELECT * FROM uniques WHERE name = ? AND base = ?", (n, b))
        return rows

    def base(self, name: str) -> dict | None:
        rows = self._rows("SELECT * FROM bases WHERE name = ? COLLATE NOCASE", (name,))
        return rows[0] if rows else None

    def node(self, name_or_id) -> list[dict]:
        if isinstance(name_or_id, int) or str(name_or_id).isdigit():
            return self._rows("SELECT * FROM nodes WHERE id = ?", (int(name_or_id),))
        return self._rows("SELECT * FROM nodes WHERE name = ? COLLATE NOCASE", (name_or_id,))

    def mods(self, text: str | None = None, *, domain: str = "Item", slot: str | None = None,
             affix_type: str | None = None, group: str | None = None, max_level: int | None = None) -> list[dict]:
        """Item modifiers. slot = a weight key like 'ring', 'body_armour', 'str_armour', 'spear'
        (mods that can roll there); text = substring of the mod line."""
        sql, args = "SELECT * FROM mods WHERE domain = ?", [domain]
        if text:
            sql += " AND text LIKE ?"
            args.append(f"%{text}%")
        if slot:
            sql += " AND EXISTS (SELECT 1 FROM json_each(mods.spawns_on) WHERE value = ?)"
            args.append(slot)
        if affix_type:
            sql += " AND type = ?"
            args.append(affix_type)
        if group:
            sql += " AND grp = ?"
            args.append(group)
        if max_level is not None:
            sql += " AND level <= ?"
            args.append(max_level)
        return self._rows(sql + " ORDER BY grp, level", args)

    def mod_tiers(self, group: str, domain: str = "Item", slot: str | None = None,
                  affix_type: str | None = None) -> list[dict]:
        """All tiers of one mod family, best first (highest level), numbered T1 = best.
        slot / affix_type narrow it down (the same group can be a prefix on one slot and differ on another)."""
        rows = self.mods(domain=domain, slot=slot, affix_type=affix_type, group=group)
        rows.sort(key=lambda r: r["level"] or 0, reverse=True)
        for i, r in enumerate(rows, 1):
            r["tier"] = i
        return rows

    def mod_pool(self, base_name: str, ilvl: int = 100, domain: str = "Item") -> list[dict]:
        """Mods that can roll on a base at an item level, using the game's rule: the first weight key in
        the mod's list that the base has decides (weight 0 = cannot roll). Real weights are not in PoB, so
        every possible mod has weight 1 here."""
        base = self.base(base_name)
        if not base:
            raise ValueError(f"unknown base {base_name!r}")
        tags = set(base["tags"])
        out = []
        for m in self._rows("SELECT * FROM mods WHERE domain = ? AND level <= ? AND type IN ('Prefix','Suffix')",
                            (domain, ilvl)):
            w = next((v for k, v in zip(m["weight_keys"], m["weight_vals"]) if k in tags), 0)
            if w > 0:
                out.append(m)
        return out

    def essences_for(self, mod_id: str) -> list[dict]:
        return self._rows("SELECT name, family AS essence_type, tier_level, item_type FROM essences WHERE mod_id = ?",
                          (mod_id,))

    def uniques_for_base_type(self, base_type: str) -> list[dict]:
        return self._rows("SELECT u.* FROM uniques u JOIN bases b ON b.name = u.base WHERE b.type = ?", (base_type,))

    def classes(self) -> dict[str, list[str]]:
        res: dict[str, list[str]] = {}
        for r in self.con.execute("SELECT class, ascendancy FROM classes ORDER BY class, ascendancy"):
            res.setdefault(r["class"], [])
            if r["ascendancy"]:
                res[r["class"]].append(r["ascendancy"])
        return res
