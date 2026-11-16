# Slop of Exile Helper

Optymalizator buildów do Path of Exile 2, oparty na silniku Path of Building (PoE2) i Claude'zie.
Plan i harmonogram: [PLAN.md](PLAN.md).

**Status:** fazy 0–6 gotowe. PoB2 działa headless w Pythonie (LuaJIT przez `lupa`). Do buildu masz doradcę w Claude Code (MCP), lokalną appkę webową i pipeline na dzień premiery.

## Setup (Windows)

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python scripts/fetch_pob.py      # PoB w wersji z POB_VERSION -> vendor/
.venv/Scripts/soe kb build                     # baza wiedzy
.venv/Scripts/python -m pytest
```

## Użycie

```bash
.venv/Scripts/soe web                           # appka: http://127.0.0.1:8765
.venv/Scripts/soe eval <kod buildu PoB>         # podsumowanie: DPS, EHP, resy, atrybuty
.venv/Scripts/soe eval build.txt --full         # wszystkie staty, które liczy PoB
```

## Appka webowa

`soe web` uruchamia lokalną stronę na tym samym silniku co doradca MCP. Wklejasz kod buildu i masz zakładki:
- **Check-up**: co hamuje build, kolejność według suwaków celów
- **Przegląd**: kafle statów, mierniki resów do capu, max hit per typ, punkty, config
- **Skille**: DPS każdego skilla, gemy (supporty, które nie działają, są przekreślone), optymalizator supportów z „Zastosuj”
- **Gear**: widok slotu (tekst itemu, lepsze mody z esencjami, idealny item, unikaty na slot, porównanie wklejonego itemu), wagi statów, „unikat, który mi się podoba”
- **Drzewko**: najlepsze nowe pasywki, co zwolnić, optymalizator drzewka z „Zastosuj”
- **Combo**: co build tworzy / z czego korzysta, payoffy, enablery, ostrzeżenia z configu
- **Plan**: wszystkie zmiany posortowane, razem zmierzone, „Zastosuj gemy i drzewko”
- **Szukaj**: baza wiedzy

„Kod PoB” kopiuje aktualny build (ze zmianami) do schowka, a „Reset” wraca do wczytanego. Jest jasny i ciemny motyw, a układ działa na telefonie.

## Dzień premiery (PoB z danymi 1.0)

```bash
.venv/Scripts/soe update             # najnowszy release PoB: pobierz -> test silnika -> nowa baza -> raport zmian
.venv/Scripts/soe update v1.0.0      # konkretny tag
.venv/Scripts/soe compare v0.22.0 v0.23.1   # sam raport różnic między wersjami
```

`update` testuje silnik na buildach z `tests/builds/`. Jeśli test padnie, wraca do poprzedniej wersji. Raport zmian (gemy, unikaty, notable, ascendancy, mody, bazy) trafia do `data/patch-<stara>-<nowa>.md`. Przykład z próby: [docs/patch-example-v0.22.0-v0.23.1.md](docs/patch-example-v0.22.0-v0.23.1.md) (~1 min).
Po aktualizacji zrestartuj serwer MCP i appkę, a potem odpal testy. Liczby z `tests/test_reference_builds.py` (poe.ninja) trzeba będzie podmienić na buildach z 1.0.

## Doradca w Claude Code (MCP)

Serwer `soe` jest zarejestrowany w `.mcp.json`. Claude Code w tym folderze pyta przy starcie, czy go włączyć.
Wymaga zbudowanej bazy (`soe kb build`). Narzędzia: `load_build`, `build_overview`, `checkup`, `get_item`, `build_config`,
`whatif_passives`, `whatif_item`, `try_changes`, `apply_changes`, `rank_passives`, `rank_respec`,
`stat_weights`, `optimize_supports`, `optimize_tree`, `improvement_plan`, `try_unique`, `rank_uniques`,
`mod_upgrades`, `ideal_item`, `craft_odds`, `suggest_combos`, `export_build`, `reset_build`,
`kb_search`, `kb_gem`, `kb_supports_for`, `kb_unique`, `kb_mods`, `kb_node`. Zasady odpowiadania są w [CLAUDE.md](CLAUDE.md).

`checkup` to lista tego, co hamuje build: resy, najsłabszy max hit, atrybuty, spirit, mana, supporty, które nie działają,
poziomy gemów, punkty, pasywki z drugiego zestawu broni oraz pasywki i mody, które nic nie dają (zmierzone w PoB).
Wynik ułożony jest wg wag celów gracza. Format jest wzorowany na [Exile Build Advisor](https://github.com/reytla/exile-build-adviser)
(reytla, MIT), szczegóły w [NOTICE](NOTICE).

Ręczne uruchomienie: `.venv/Scripts/python -m soe.advisor.server` (stdio).

### Optymalizatory (`soe/optimize/`)

- `objective.py`: cel = waga_dmg · ln(DPS) + waga_surv · ln(EHP), z karami za spadek resów, niespełnione atrybuty i przekroczony spirit
- `stat_weights.py`: ile wart jest każdy z ~45 statów gearowych (dodany do biżuterii, what-if, < 0.5 s)
- `supports.py`: wszystkie pasujące supporty w każdym slocie, pełne przeliczenia PoB na puli procesów, 2 etapy (~25 s); reguły: support raz na skill, jedna rodzina gemów
- `tree.py`: zachłanne ruchy na drzewku (zwolnij słabe → weź mocne), każdy ruch sprawdzony w PoB; pasywek, których PoB nie liczy, nie rusza
- `plan.py`: `improvement_plan` łączy wszystko (supporty, drzewko, najlepsza zmiana moda na każdym slocie), mierzy całość razem i dokłada priorytety statów na gear

### Itemy i combo (`soe/items/`, `soe/combo/`)

- `uniques.py`: `try_unique` (wstaw unikat, zobacz zmiany, linie, których PoB nie liczy, co psuje) i `rank_uniques` (wszystkie unikaty danego typu vs obecny item, ~0.5 s)
- `craft.py`: pula modów bazy dla ilvl (zasada pierwszego pasującego tagu wagi), rozpoznawanie tieru moda (z zakresem, też ponad tiery po katalizatorach), `mod_upgrades` (co wymienić, na co, esencja), `ideal_item` (sufit 3+3), `craft_odds` (równe wagi = szacunek)
- `mechanics.py`: słownik ~25 mechanik (ailmenty, charge'e, whirlwind, infusion, ground, herald...), profil buildu (tworzy / korzysta), payoffy i enablery mierzone w PoB, sprawdzenie warunków włączonych w configu bez źródła w buildzie (~10 s z pulą)
- baza wiedzy: tabela esencji; każda budowa to nowy plik `data/kb-*.sqlite` + wskaźnik `data/kb.current` (na Windows otwartej bazy nie da się podmienić)

## Baza wiedzy

```bash
.venv/Scripts/soe kb build                       # data/kb.sqlite z danych PoB (~2 s)
.venv/Scripts/soe kb search life leech           # szuka we wszystkim: gemy, skille, mody, bazy, unikaty, notable, ascendancy
.venv/Scripts/soe kb gem Twister                 # typy skilla, tagi, staty na max poziomie jako tekst
.venv/Scripts/soe kb supports Twister            # supporty, które PoB pozwala podpiąć
.venv/Scripts/soe kb unique Headhunter           # aktualny wariant: implicity i mody
.venv/Scripts/soe kb mods "maximum Life" --slot ring --type Prefix
```

W Pythonie: `from soe.kb import KB` i dalej `KB().search(...)`, `gem`, `supports_for`, `unique`, `base`, `node`, `mods(slot=...)`, `mod_tiers(group, slot=...)`, `classes()`.
Wagi modów w danych PoB to tylko 0/1 (patrz PLAN.md, ryzyko 4).

## Jak to działa

- `soe/engine/pob.py`: klasa `PoB`, jedna instancja PoB:
  - **ładowanie i eksport:** `load_code`, `load_xml`, `export_code`, `export_xml`
  - **wyniki:** `summary()` (najważniejsze staty, brakujące = 0), `output()` (wszystko), `all_skill_dps()` (DPS, DoT i miniony każdego skilla)
  - **what-if bez zmiany buildu (~130/s na rdzeń):** `whatif(add_nodes=[...], with_path=True)`, `whatif(remove_nodes=[...])`, `whatif(slot="Ring 2", item_raw=...)`, `whatif(slot="Ring 2")` (pusty slot)
  - **zmiany:** drzewko (`alloc_node`, `dealloc_node`, `reachable`, `node_info`, `node_path`), gemy (`groups`, `set_gem(group, gem, name=/level=/quality=/enabled=)`, `remove_gem`, `set_main_skill`, `paste_gems`), itemy (`items`, `equip`, `unequip`), config (`config_options`, `set_config`), postać (`set_class`, `set_level`)
  - **cofanie:** `with pob.trial(): ...` (albo `snapshot()` i `restore()`)
  - „Weapon 1/2” samo trafia w aktywny zestaw broni (swap), `exact_slot=True` wyłącza to mapowanie
- `soe/engine/pool.py`: `PoBPool` to wiele procesów z tym samym buildem. Zadania to słowniki (`{"call": "whatif", "kwargs": {...}}` albo `{"trial": [[metoda, kwargs], ...]}`). Na 16 rdzeniach daje ~800 what-if/s (`scripts/bench.py`).
- `soe/engine/lua/soe_api.lua`: jedyne miejsce, które dotyka wnętrzności PoB. Przy aktualizacji PoB naprawiamy tylko ten plik.
- `soe/engine/lua/bootstrap.lua`: odpala `HeadlessWrapper.lua` z PoB, podpina zlib z Pythona i pure-Lua shim za `lua-utf8`.
- Nową wersję PoB (np. 1.0 w dniu premiery) ściągasz przez `python scripts/fetch_pob.py <tag>` i zmianę `POB_VERSION`.

## Znane pułapki

- Pola tabel Lua o nazwach `items`, `keys`, `values` czytaj przez `tbl["items"]`, bo w lupa `.items` to metoda Pythona.
- LuaJIT na Windows rzuca wyjątek SEH `0xe24c4a02` przy każdym złapanym błędzie Lua. To nie crash; faulthandler w pytest jest wyłączony z tego powodu.
- Jedna instancja `PoB` na proces/wątek. Do równoległych obliczeń używaj wielu procesów.
