"""MCP server: Slop of Exile Helper tools for Claude.

Run: python -m soe.advisor.server   (stdio; registered in .mcp.json)
"""
from __future__ import annotations

import functools
import json
import os
import sys
import traceback

from mcp.server.mcpserver import MCPServer

from soe.advisor.session import METRICS, OPS, Session

INSTRUCTIONS = """\
Path of Exile 2 build helper backed by the real Path of Building calculation engine and a game-data knowledge base.
Workflow: load_build -> build_overview -> answer with numbers from what-if tools, never from memory.
All what-if / try tools leave the build untouched; only apply_changes changes it.
Stat diffs are {stat: [before, after, delta, pct]}. DPS is per PoB's current config (check build_config).
"""

mcp = MCPServer("slop-of-exile-helper", instructions=INSTRUCTIONS)
session = Session(os.environ.get("SOE_KB") or None)  # SOE_KB: alternative kb.sqlite (tests)


def tool(fn):
    """Register a tool that runs under the session lock and returns errors as text instead of crashing."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with session.lock:
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                traceback.print_exc(file=sys.stderr)
                return {"error": f"{type(e).__name__}: {e}"}
    return mcp.tool()(wrapper)


# ---- build ---------------------------------------------------------------------------
@tool
def load_build(build: str, name: str = "build") -> dict:
    """Load a build: a Path of Building export code, PoB XML, or a path to a file with either.
    Returns the summary (class, ascendancy, level, main skill, DPS, defences, resistances, attributes)."""
    return session.load(build, name)


@tool
def build_overview(with_all_skill_dps: bool = True) -> dict:
    """Everything about the loaded build: summary, skill groups with gems (group numbers are used by
    try_changes), DPS of every skill, equipped items in use, active weapon set and key config values."""
    return session.overview(with_all_skill_dps)


@tool
def get_item(slot: str) -> dict | None:
    """Full text of the item in a slot (e.g. 'Helmet', 'Ring 1', 'Weapon 1' = active weapon set),
    in PoB/game copy format, so it can be edited and passed to whatif_item."""
    return session.item(slot)


@tool
def build_config(search: str | None = None, only_set: bool = True) -> list[dict]:
    """PoB configuration options (enemy type, conditions, charges, buffs...). By default only those set.
    search filters by label or variable name. Change them with try_changes op set_config."""
    return session.config(search, only_set)


@tool
def export_build() -> str:
    """Current build as a PoB import code (includes changes made with apply_changes)."""
    return session.export_code()


@tool
def reset_build() -> dict:
    """Undo every apply_changes: back to the build as loaded."""
    return session.reset()


# ---- what-if ----------------------------------------------------------------------------
@tool
def whatif_passives(add: list[str] | None = None, remove: list[str] | None = None) -> dict:
    """Stat changes from allocating (with the shortest path) and/or removing passive nodes.
    Nodes by name or id. Build is not changed."""
    return session.whatif_passives(add, remove)


@tool
def whatif_item(slot: str, item_text: str | None = None) -> dict:
    """Stat changes from putting an item (game/PoB item text, e.g. from get_item or the trade site)
    in a slot; without item_text the slot is emptied. Build is not changed."""
    return session.whatif_item(slot, item_text)


@tool
def try_changes(steps: list[dict]) -> dict:
    """Apply a list of changes, report stat changes, then roll everything back.
    Each step is {"op": ..., ...}:
      set_gem {group, gem, name?, level?, quality?, enabled?}  (gem index past the end adds a gem)
      remove_gem {group, gem} | set_main_skill {group, skill?} | paste_gems {text}
      equip {slot, raw} | unequip {slot} | set_config {var, value} | set_level {level}
      alloc_node {node} | dealloc_node {node}   (node = name or id)
    Group/gem numbers are 1-based, as in build_overview."""
    return session.try_changes(steps)


@tool
def apply_changes(steps: list[dict]) -> dict:
    """Same steps as try_changes, but kept. Returns the changes and the new build code."""
    return session.apply_changes(steps)


@tool
def rank_passives(metric: str = "dps", max_cost: int = 6, limit: int = 15, include_small: bool = False) -> list[dict]:
    """Rank reachable notables/keystones (and small nodes with include_small) by gain per point
    for a metric: dps, hit_dps, ehp, life, es, mana, evasion, armour, speed, phys_max_hit,
    chaos_max_hit, movement, or any summary stat name. Path cost included. Also shows DPS/EHP side effects."""
    types = ("Notable", "Keystone", "Normal") if include_small else ("Notable", "Keystone")
    return session.rank_passives(metric, types, max_cost, limit)


# ---- knowledge base ---------------------------------------------------------------------
@tool
def kb_search(query: str, kind: str | None = None, limit: int = 15) -> list[dict]:
    """Full-text search over game data: kind = gem, skill, mod, base, unique, node, ascendancy (or all)."""
    return session.kb.search(query, kind, limit)


@tool
def kb_gem(name: str) -> dict | None:
    """Gem details: tags, skill types, requirements, description and stats at max level as game text."""
    return session.kb.gem(name)


@tool
def kb_supports_for(gem: str, search: str | None = None) -> list[dict]:
    """Support gems that can support this active gem (same rule as PoB). search filters by name/text."""
    rows = session.kb.supports_for(gem)
    if search:
        s = search.lower()
        rows = [r for r in rows if s in r["name"].lower() or s in " ".join(r["stats_text"]).lower()]
    return [{"name": r["name"], "tier": r["tier"], "text": r["stats_text"]} for r in rows]


@tool
def kb_unique(name: str) -> list[dict]:
    """Unique item: base, league, level requirement, implicits and mods (current variant)."""
    return [{k: r[k] for k in ("name", "base", "slot_type", "league", "req_level", "implicits", "mods")}
            for r in session.kb.unique(name)]


@tool
def kb_mods(text: str | None = None, slot: str | None = None, affix_type: str | None = None,
            domain: str = "Item", max_level: int | None = None) -> list[dict]:
    """Item modifiers that can roll: slot is a weight key like ring, amulet, belt, helmet, gloves, boots,
    body_armour, str_armour, dex_armour, int_armour, spear, bow, wand, staff, quiver, focus, sceptre...
    affix_type Prefix/Suffix; max_level = item level. Note: PoB has no real spawn weights."""
    rows = session.kb.mods(text, domain=domain, slot=slot, affix_type=affix_type, max_level=max_level)
    return [{k: r[k] for k in ("type", "affix", "text", "level", "grp")} for r in rows[:200]]


@tool
def kb_node(name: str) -> list[dict]:
    """Passive node(s) by name: type, ascendancy, stats."""
    return [{k: r[k] for k in ("id", "name", "type", "ascendancy", "stats")} for r in session.kb.node(name)]


def main():
    # PoB must never write to stdout (it is the MCP channel); our PoB wrapper silences Lua print.
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    mcp.run("stdio")


if __name__ == "__main__":
    main()
