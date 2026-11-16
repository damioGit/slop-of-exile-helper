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
def ask(question: str, skill: str | None = None, goal: str | None = None, budget_divine: float | None = None) -> dict:
    """Answer a player's free-text question about the loaded build with a measured to-do list (~20-60 s).
    Understands Polish and English, e.g. "nie oneshotuję moba, jak bić mocniej Cometem za 5 div",
    "I keep dying to bosses", "out of mana". goal (optional): dps, hit (one-shot = average hit), survive,
    mana, speed. Each step has gain, cost and, when possible, apply steps for apply_changes."""
    from soe.advisor.assistant import ask as run

    return run(session, question, skill, goal, budget_divine)


@tool
def find_upgrade(slot: str, wanted_mod: str | None = None, budget_divine: float | None = None,
                 damage: float = 1, survive: float = 1) -> dict:
    """Search the official trade site (current league) for a real item to replace the one in `slot`: keeps the
    current item's strongest mods (at ~80% of its rolls) and adds `wanted_mod` (game text, e.g.
    '+3 to Level of all Lightning Spell Skills'). Every listing is priced and measured in PoB in this build.
    Returns the best items with stats, price, gain and a link to the same search."""
    from soe.prices.trade import find_upgrade as run

    return run(session, slot, wanted_mod, budget_divine, _goals(damage, survive))


@tool
def import_character(account_or_link: str, character: str | None = None) -> dict:
    """Load a public character from poe.ninja (Path of Exile 2): either a poe.ninja character link, or the
    account name as shown in game (Name#1234) plus the character name. Finds the league automatically.
    Only characters poe.ninja has indexed (public profile, high enough level) can be imported."""
    return session.import_character(account_or_link, character)


@tool
def resync_character() -> dict:
    """Re-import the character loaded with import_character (picks up gear, gems and passives changed in game
    since, once poe.ninja has re-fetched it). Drops changes made with apply_changes."""
    return session.resync()


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


@tool
def checkup(damage: int = 2, survive: int = 2, mana: int = 1, ease: int = 1, speed: int = 1, deep: bool = True) -> dict:
    """Ranked list of what holds the build back: uncapped resistances, weakest max hit, attributes,
    Spirit, mana sustain, supports that do not apply, low gem levels, unspent points, passives in the
    inactive weapon set, passives and gear mods that change nothing (measured in PoB). Goal weights
    0-3 reorder the list for what the player cares about. Start here for "what should I improve?"."""
    from soe.advisor.checkup import run_checkup

    return run_checkup(session, {"damage": damage, "survive": survive, "mana": mana, "ease": ease, "speed": speed}, deep)


def _goals(damage, survive, speed=1.0):
    from soe.optimize.objective import Objective

    return Objective.from_goals({"damage": damage, "survive": survive, "speed": speed})


@tool
def stat_weights(damage: float = 1, survive: float = 1) -> dict:
    """What each common gear stat is worth to this build (life, ES, resistances, attributes, crit, speed,
    added damage, +skill levels, penetration...): DPS %, EHP % and objective score per stat line,
    measured by adding the line to equipped jewellery. Use it to tell the player what to look for on gear.
    damage/survive weight the score (e.g. survive=2 for a tanky build)."""
    from soe.optimize.stat_weights import stat_weights as sw

    return sw(session.pob, session.base, _goals(damage, survive))


@tool
def optimize_supports(group: int | None = None, damage: float = 1, survive: float = 1,
                      budget_divine: float | None = None) -> dict:
    """Try every compatible support gem in every support slot of a skill group (default: main skill)
    with full PoB recalculations in parallel (~20-30 s). Returns the value of each current support,
    the best swaps per slot and the best set of swaps checked together with apply_steps.
    budget_divine skips lineage supports priced above it on poe.ninja (ask the player's budget).
    Supports whose removal raises the score are listed: ask why the player uses them before replacing."""
    from soe.optimize.supports import optimize_supports as opt

    return opt(session, group, _goals(damage, survive), budget_divine=budget_divine)


@tool
def optimize_tree(damage: float = 1, survive: float = 1, max_moves: int = 6, max_path: int = 5,
                  include_small: bool = False) -> dict:
    """Greedy passive tree optimizer: spends free points and moves points from weak passives to strong
    ones (refund + allocate), verified in PoB after each move (~10-30 s). Keeps passives PoB cannot
    calculate. Returns the moves, total DPS/EHP change, apply_steps and the final build code.
    The loaded build is not changed."""
    from soe.optimize.tree import optimize_tree as opt

    return opt(session, _goals(damage, survive), max_moves=max_moves, max_path=max_path, include_small=include_small)


@tool
def improvement_plan(damage: float = 1, survive: float = 1, top: int = 10, budget_divine: float | None = None) -> dict:
    """The answer to "what should I change?": best support swaps, main skill gem level, passive moves,
    ranked by gain, plus everything together measured as one bundle, plus which stats to look for on
    gear. Takes ~1 minute. damage/survive weight the goal."""
    from soe.optimize.plan import improvement_plan as plan

    return plan(session, {"damage": damage, "survive": survive}, top=top, budget_divine=budget_divine)


@tool
def try_unique(name: str, slot: str | None = None, damage: float = 1, survive: float = 1) -> dict:
    """"I like unique X": puts the unique in the build (best fitting slot unless given) and reports the
    stat changes, what it replaces, lines PoB cannot calculate and what it breaks (resistances, attributes)."""
    from soe.items.uniques import try_unique as tu

    return tu(session, name, slot, _goals(damage, survive))


@tool
def rank_uniques(slot: str, damage: float = 1, survive: float = 1, limit: int = 15) -> dict:
    """Every unique of the item type in `slot` (e.g. 'Ring 1', 'Body Armour', 'Weapon 1'), ranked against
    the item worn now, measured in PoB."""
    from soe.items.uniques import rank_uniques as ru

    return ru(session, slot, _goals(damage, survive), limit)


@tool
def mod_upgrades(slot: str, damage: float = 1, survive: float = 1, limit: int = 10) -> dict:
    """Crafting: for each mod on the item in `slot`, the best replacement of the same affix type (prefix or
    suffix) that can roll on its base at its item level, with the gain and an essence that guarantees it.
    Lines from outside the normal pool (fractured, desecrated, runes, catalyst-boosted values) are listed."""
    from soe.items.craft import mod_upgrades as mu

    return mu(session, slot, _goals(damage, survive), limit)


@tool
def ideal_item(slot: str, damage: float = 1, survive: float = 1, item_level: int | None = None) -> dict:
    """The best 3 prefixes + 3 suffixes for this build on the base in `slot` (top tier, top rolls), and how
    much better it is than the current item. A ceiling to aim at and a list of what to look for."""
    from soe.items.craft import ideal_item as ii

    return ii(session, slot, _goals(damage, survive), item_level)


@tool
def craft_odds(base: str, item_level: int, want_groups: list[str]) -> dict:
    """Chance that one random added prefix/suffix lands in the wanted mod families (names as in
    ideal_item / mod_upgrades 'group'). Equal weights: PoB has no real spawn weights, so it is an estimate."""
    from soe.items.craft import craft_odds as co

    return co(session, base, item_level, want_groups)


@tool
def suggest_combos(damage: float = 1, survive: float = 1, max_cost: int = 6) -> dict:
    """Combo engine (~10 s): which mechanics the build creates (shock, blind, frenzy charges, whirlwinds,
    heralds...) and which it feeds on; payoffs that use what it creates and enablers for what it lacks
    (supports and passives measured in PoB, uniques as leads); and config conditions switched on in PoB
    that nothing in the build creates (optimistic numbers)."""
    from soe.combo.mechanics import suggest_combos as sc

    return sc(session, _goals(damage, survive), max_cost)


@tool
def price_check(names: list[str]) -> dict:
    """Current poe.ninja prices (Path of Exile 2, current league) for currency, essences, uniques, lineage
    supports, uncut gems, runes, fragments... by exact item name. Unknown or unlisted = null (never guessed).
    Also returns the league and the Divine/Exalted/Chaos rates."""
    from soe.prices import default_prices

    p = default_prices()
    return {"status": p.status(), "prices": {n: p.price(n) for n in names}}


@tool
def rank_respec(metric: str = "dps", limit: int = 15) -> dict:
    """Allocated passives ordered by the smallest loss per refunded point (node + nodes that only connect
    through it), for finding points to move when none are free. Also lists nodes allocated to the
    inactive weapon set (they count for nothing in the current calculation) and the point budget.
    `not_calculated` lists stat lines PoB cannot model; a 0 loss there does not mean useless in game."""
    return session.rank_respec(metric, limit)


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
def kb_supports_for(gem: str, search: str | None = None, limit: int = 40) -> dict:
    """Support gems that can support this active gem (same rule as PoB). search filters by name/text
    (e.g. 'crit', 'cold', 'more damage'). Returns the total count and at most `limit` supports."""
    rows = session.kb.supports_for(gem)
    if search:
        s = search.lower()
        rows = [r for r in rows if s in r["name"].lower() or s in " ".join(r["stats_text"]).lower()]
    return {"total": len(rows), "shown": min(len(rows), limit),
            "supports": [{"name": r["name"], "tier": r["tier"], "text": r["stats_text"]} for r in rows[:limit]]}


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
