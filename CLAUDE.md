# Slop of Exile Helper

PoE2 build optimizer on top of the Path of Building (PoE2) engine. Plan: [PLAN.md](PLAN.md). Setup and API: [README.md](README.md).
The user writes in casual Polish; answer in Polish.

## Answering build questions (MCP server `soe`)

When the user pastes a build code or asks about their build, use the `soe` tools. Never quote DPS, EHP or stat changes from memory; every number must come from a tool call.

1. `load_build` with the code, then `build_overview`. Note the main skill, the active weapon set, the passive point budget, enemy resistances and the config, especially `enemyIsBoss`.
   For "what should I improve?" start with `checkup` (set goal weights from what the player says). On a full tree, use `rank_respec` to find points to move.
   Read the `notes` in tool results: they explain empty changes (inactive weapon set, mechanics PoB does not calculate, conditions switched off).
2. Look things up with `kb_*`: gem text, supports for a skill, unique mods, which mods can roll on a slot. Patch-specific details (numbers, what a unique does) come from the KB, not from memory.
3. Measure before recommending:
   - passives: `rank_passives` (gain per point), then `whatif_passives` for specific nodes
   - gear: `get_item` gives the current item text; edit it or paste a trade item into `whatif_item`
   - gems, config, level, combinations: `try_changes` (rolled back automatically)
   - only `apply_changes` when the user wants the change kept; give them the new `build_code`
4. In the answer:
   - give before → after with the % change
   - say what each number depends on, for example "against enemies within 2 m", "while affected by Herald of Ice", "vs Pinnacle boss config"
   - flag the trade-offs: DPS vs EHP, resistances dropping below cap, attribute requirements, spirit
   - order suggestions by impact per cost (passive points, currency, gem swaps)
5. Known limits:
   - PoB has no real mod spawn weights (only can/can't roll), so crafting odds are estimates
   - skills with conditional uptime are calculated as PoB's config says; check `build_config` before calling something "free DPS"

## Development

- Tests: `.venv/Scripts/python -m pytest` (needs `vendor/` from `scripts/fetch_pob.py` and nothing else)
- The knowledge base is built by `soe kb build` into `data/kb.sqlite` (gitignored)
- Only `soe/engine/lua/soe_api.lua` and `kb_export.lua` touch PoB internals. When updating PoB (`POB_VERSION`), fix those first
- Lua table fields named `items`/`keys`/`values` must be read as `tbl["items"]` from Python (lupa)
- Write files with the Write tool, not bash heredocs: the Bash tool here mangles long heredocs
