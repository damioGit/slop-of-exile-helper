# Slop of Exile Helper

A local Path of Exile 2 app that tells you what to improve in your build and how to craft it. Every number comes from the real **Path of Building (PoE2)** engine run on your character, not from memory or guides. Mod and crafting data come from **poe2db**, prices from **poe.ninja**.

It runs in your browser, on your computer. Your build stays with you. The interface is in English, with a PL/EN switch in the top bar.

> **Claude is not required.** The whole app works without AI: calculations, the Forge, Gear, the tree, trade and updates. Claude is an optional extra for people who have Claude Code (see [below](#optional-claude)).

## Install (Windows 10/11)

1. Download `slop-of-exile-helper-vX.Y.Z.zip` from **[Releases](https://github.com/damioGit/slop-of-exile-helper/releases/latest)** and unzip it somewhere it can stay (about 1 GB).
2. Double-click **`install.bat`**. If Python or Git is missing, the installer adds it (winget). Downloading Path of Building takes a few minutes.
3. Start it with the **Slop of Exile Helper** desktop shortcut (or `run.bat`). The app opens in your browser; closing the black window stops it.
4. Paste a Path of Building code or import a character from poe.ninja (`Name#1234` + character name).

If something fails, run `install.bat` again: it only does what is missing.

## What it does

- **Assistant:** a quick check of the build in a few seconds:
  - resistances against the cap, missing attributes, spirit, whether mana holds up;
  - the damage type you take worst (the biggest hit you survive);
  - what to replace first and the best passives in reach.

  You can also ask questions in your own words ("I can't one-shot bosses, how do I hit harder?") and get a list of changes with their gain and cost, each with an "Apply" button.
- **Gear:** your equipment looks like in game. For every item you see:
  - what each mod is worth, and whether an Exalt, Chaos, Annul or Fracture pays off (with odds and prices);
  - which slot to replace first against a realistic rare for your level;
  - a recipe for a better item;
  - replacements from the official trade site, each calculated in PoB on your build.
- **Forge:** pick a base and mods, or click "goal for my build". The app compares craft routes:
  - essences and Perfect Essences;
  - Exaltation, Annulment and Crystallisation omens;
  - desecration (bones);
  - Greater/Perfect Exalted Orbs;
  - cheap bases to 5/6 and finishing the best one.

  You get the chance per try, the cost until done and the cost when 4/6 or 5/6 is enough. You also see how much DPS and EHP the item gives your character. Mods that practically never roll on that base are flagged straight away.
- **Skills:** gems with their in-game descriptions, DPS of every skill, supports that do not apply (with the reason) and a support optimizer.
- **Tree:** the passive tree as in PoB, the best new passives, what to refund and a tree optimizer.
- **Plan and Synergies:** all changes measured together; the mechanics the build creates and feeds on; config conditions nothing in the build creates (meaning the DPS shown is too high).

## Updates happen by themselves

On start and every few hours the app checks:
- **a new Path of Building:** installed only after it passes the check on reference builds, so a new league or 1.0 needs nothing from you;
- **poe2db data:** mod weights, essences, desecrated mods;
- **crafting rules:** if GGG changes what an orb or omen does, the app reports it;
- **poe.ninja prices and the current league;**
- **a new version of the app itself** from this repository (can be turned off).

The state of the data is in the **"Data and updates"** panel. It also has a "Force a full update" button that downloads everything again.

## Optional: Claude

The app does **not** need Claude. If you have [Claude Code](https://claude.com/claude-code), there are two ways to use it:
- **The "AI" checkbox in the Assistant:** the question goes to Claude Code logged in on your account. Claude uses the same tools as the app and can look things up on the wiki, so it understands any question. Without Claude Code the checkbox simply does not work; the rest of the app is unaffected.
- **The `soe` MCP server** (registered in `.mcp.json`): in Claude Code in this folder you talk about your build and Claude calculates everything in PoB with ~40 tools (`load_build`, `checkup`, `optimize_supports`, `craft_routes`, `find_upgrade`...). The rules for its answers are in [CLAUDE.md](CLAUDE.md).

## Good to know

- **Craft odds are a simulation on poe2db mod weights.** For desecration, poe2db does not say how often the options are the base's normal mods; that assumption is written next to the results.
- **Importing a character works for public characters poe.ninja knows.** When there are too many requests, poe.ninja blocks access for a while and prices come from the cache.
- **No price on poe.ninja means "unknown".** Nothing is guessed.
- **A fan project, not affiliated with Grinding Gear Games.**

---

## For developers

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python scripts/fetch_pob.py      # PoB at the POB_VERSION tag -> vendor/
.venv/Scripts/soe kb build                     # knowledge base from PoB's data
.venv/Scripts/soe poe2db sync                  # mod weights, essences, desecrated mods
.venv/Scripts/python -m pytest
```

Main commands:

```bash
.venv/Scripts/soe web                          # the app: http://127.0.0.1:8765
.venv/Scripts/soe eval <PoB build code>        # DPS, EHP, resistances, attributes
.venv/Scripts/soe refresh [--full]             # check / force a data update
.venv/Scripts/soe update [tag]                 # new PoB: fetch -> engine check -> KB -> patch report
.venv/Scripts/soe kb search life leech         # knowledge base: gems, mods, bases, uniques, notables
.venv/Scripts/python scripts/make_package.py   # zip for players -> dist/
```

Layout:
- **`soe/engine/`:** PoE2 PoB headless in Python (LuaJIT via `lupa`).
  - `pob.py` runs what-ifs without changing the build (~130/s per core);
  - `pool.py` is a process pool;
  - `lua/soe_api.lua` is the only file that touches PoB internals.
- **`soe/kb/`:** the knowledge base from PoB's data, plus `poe2db.py` (weights, essences, desecrated mods) and `craft_rules.py` (the crafting rules sensor).
- **`soe/items/`:** the Forge (`crafter.py`), gear (`gear.py`, `craftplan.py`, `forge_build.py`), uniques, mods.
- **`soe/optimize/`:** the objective (weighted DPS/EHP with penalties), stat weights, supports, tree, plan.
- **`soe/advisor/`:** the session, check-up, quick check and the MCP server.
- **`soe/web/`:** FastAPI and one `index.html` (no build step).
- **`soe/prices/`:** poe.ninja, trade, character import.
- **`soe/pipeline/`:** updates (`autoupdate.py`, `update.py`) and the report of changes between versions.
- **`soe/i18n.py`:** player-facing text comes in English and Polish: `t("English", "Polish")` in Python, `T(...)` in the page; the page sends its language in `X-SOE-Lang`. `scripts/find_polish.py` lists Polish text outside such pairs.
- **Tests:** `pytest`, about 4 min. Among other things they check that the repository holds no tokens, passwords or private paths.

Pitfalls: Lua table fields named `items`, `keys` and `values` must be read as `tbl["items"]` (in lupa `.items` is a Python method). LuaJIT on Windows raises SEH `0xe24c4a02` for caught Lua errors: that is not a crash. One `PoB` instance per process.

## Sources and thanks

- [Path of Building Community (PoE2)](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2): the calculation engine, downloaded at install.
- [poe2db.tw](https://poe2db.tw): mod weights, essences, desecrated mods, orb descriptions, icons.
- [poe.ninja](https://poe.ninja): prices and public characters.
- The check-up format is inspired by [Exile Build Advisor](https://github.com/reytla/exile-build-adviser) (reytla, MIT). Details in [NOTICE](NOTICE).
