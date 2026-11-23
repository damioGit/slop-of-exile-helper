# Slop of Exile Helper

PoE2 build optimizer on top of the Path of Building (PoE2) engine. Plan: [PLAN.md](PLAN.md). Setup and API: [README.md](README.md).
The user writes in casual Polish; answer in Polish.

## Answering build questions (MCP server `soe`)

When the user pastes a build code or asks about their build, use the `soe` tools. Never quote DPS, EHP or stat changes from memory; every number must come from a tool call.

1. `load_build` with the code, then `build_overview`. Note the main skill, the active weapon set, the passive point budget, enemy resistances and the config, especially `enemyIsBoss`.
   For "what should I improve?" start with `checkup` (set goal weights from what the player says). On a full tree, use `rank_respec` to find points to move.
   For "what should I change?" use `improvement_plan` (~1 min), or the parts on their own: `optimize_supports` (~25 s), `optimize_tree` (~10–30 s), `stat_weights` (what to look for on gear). Tell the player it takes a moment.
   Gear: "which item do I replace first?" → `gear_audit` (each slot vs a realistic rare for the character's level). "What is this item worth / should I exalt, chaos, annul or fracture it?" → `item_analysis` (value of every mod, currency odds and prices). "How do I craft a better X?" → `craft_plan` (base, essence, exalts, odds, cost of one try). "How do I craft a base with mods X, Y, Z (cheapest / surest)?" → `craft_pool` then `craft_routes` (routes compared by chance per try and expected cost).
   Items: "I like unique X" → `try_unique`; "best unique for this slot" → `rank_uniques`; "what to craft / how to improve this item" → `mod_upgrades` (per mod, with essences) and `ideal_item` (the ceiling); odds of hitting mods → `craft_odds`. Crafting odds use the real spawn weights, mod families, essences and desecrated mods from poe2db (`soe poe2db sync`, saved in data/poe2db); a base without a poe2db page falls back to equal weights, say so then.
   Synergies: `suggest_combos` shows what the build creates and feeds on, payoffs, enablers, and **config conditions that nothing in the build creates**. Mention those first, because they mean the DPS shown is optimistic.
   Real items: `find_upgrade(slot, wanted_mod, budget_divine)` searches the official trade site, keeps the current item's key mods, and prices and measures every listing in PoB. Use it before suggesting gear the player has to buy, and say plainly when nothing in budget beats the current item.
   Gear mod suggestions are ranked by a typical (middle tier) roll. The best roll is shown apart with its odds. Never present a top-tier mod as a budget option.
   Prices: `price_check` (poe.ninja, current league, never guessed). Uniques, lineage supports, essences, Uncut Skill Gem and Exalted-based craft odds carry prices in their results. Quote them with the league and say that unlisted means unknown, not free.
   Ask for the player's budget and pass `budget_divine` to `optimize_supports` / `improvement_plan`. If `current_supports_that_lower_the_score` is not empty, ask why the player uses those supports before suggesting a swap.
   For a free-text player question ("I can't one-shot X, how do I hit harder with Y?") call `ask` first: it picks the skill and goal (one-shot = average hit, not DPS) and returns a measured to-do list.
   When PoB cannot calculate something (`not_calculated`, `unsupported`, a support that does not apply, a unique effect) or the KB has no answer, look it up before answering: WebSearch/WebFetch on poe2wiki.net (mechanics, uniques, skill tags) or poe2db.tw (exact mod values, skill types, support rules). Then explain how it works in THIS build, in plain words. Never answer only "PoB doesn't model it".
   Optimizer gains are PoB numbers under the current config. Before recommending, check what each gain depends on, for example Ferocity needs frenzy charges, Stand and Deliver needs enemies within 2 m, and lineage supports (unique names) are rare. Show the bundle result (`all_together`) as the honest total, because single gains do not add up.
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
   - mod spawn weights come from poe2db, not PoB; desecration odds assume revealed options draw normal and desecrated mods alike (poe2db does not say how often)
   - skills with conditional uptime are calculated as PoB's config says; check `build_config` before calling something "free DPS"

## Development

- Tests: `.venv/Scripts/python -m pytest` (needs `vendor/` from `scripts/fetch_pob.py` and nothing else)
- The knowledge base is built by `soe kb build` into `data/kb.sqlite` (gitignored)
- Only `soe/engine/lua/soe_api.lua` and `kb_export.lua` touch PoB internals. When updating PoB (`POB_VERSION`), fix those first
- Lua table fields named `items`/`keys`/`values` must be read as `tbl["items"]` from Python (lupa)
- Write files with the Write tool, not bash heredocs: the Bash tool here mangles long heredocs
- The running web app holds the player's own build (saved in `data/user/last_session.json`, restored on start). Never load a build into it from the terminal: test on another port (`SOE_LAST_BUILD` pointing at a scratch file)
- AI mode of the web assistant: `soe/web/ai.py` runs Claude Code headless (`claude -p`, the player's own login) with the soe MCP tools
- Web app: `soe/web/app.py` (FastAPI over the same `Session`) + `soe/web/static/index.html` (one file, no build step). Run `soe web`; API docs at /api/docs
- Languages: the repo, docs and UI are English; the UI has a PL/EN switch (default: the browser's language). Player-facing text is a pair: `t("English", "Polish")` from `soe.i18n` in Python (language per request from the `X-SOE-Lang` header, English for MCP and tests), `T("English", "Polish")` in the page, `data-pl` attributes on static HTML. Never write a one-language string the player sees; `scripts/find_polish.py` lists Polish text outside pairs. Do not name a local variable `t` where `t()` is used.
- Real-character check: `scripts/fetch_corpus.py` then `scripts/run_corpus.py` (data/corpus, never commit other players' characters). Run it after engine changes.
- Auto-update: `soe/pipeline/autoupdate.py` checks at app start and on page visits (every 6 h): new PoB release (update + engine check + KB + poe2db, then the app swaps sessions), stale poe2db pages, prices, app commits behind origin (pulled only on the player's click; `scripts/start.bat` restarts on exit code 3). `SOE_AUTOUPDATE=0` turns it off. Force update (panel button "Force a full update", or `soe refresh --full`): rebuilds the KB, refetches all poe2db pages, crafting rules and prices, re-downloads a damaged PoB, pulls the app and restarts it.
- Web page: one syntax error blanks the whole app; `tests/test_page_js.py` runs `node --check` on its script
- Launch day: `soe update [tag]` (fetch → engine check on tests/builds → new KB → patch report in data/), `soe compare old new`
- MCP tools answer in English (MCP clients translate)
