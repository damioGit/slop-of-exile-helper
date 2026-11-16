# Slop of Exile Helper

Optymalizator buildów do Path of Exile 2, oparty na silniku Path of Building (PoE2) i Claude'zie.
Plan i harmonogram: [PLAN.md](PLAN.md).

**Status:** faza 0 gotowa. PoB2 działa headless w Pythonie (LuaJIT przez `lupa`), ładuje buildy z kodu lub XML, zmienia je przez API i liczy staty.

## Setup (Windows)

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python scripts/fetch_pob.py      # PoB w wersji z POB_VERSION -> vendor/
.venv/Scripts/python -m pytest
```

## Użycie

```bash
.venv/Scripts/soe eval <kod buildu PoB>         # podsumowanie: DPS, EHP, resy, atrybuty
.venv/Scripts/soe eval build.txt --full         # wszystkie staty, które liczy PoB
```

## Jak to działa

- `soe/engine/pob.py`: klasa `PoB` z metodami: ładowanie (`load_code`, `load_xml`), eksport (`export_code`), zmiany (`set_class`, `set_level`, `paste_gems`, `add_item`, `alloc_node`, `dealloc_node`, `reachable`) i wyniki (`summary`, `output`).
- `soe/engine/lua/soe_api.lua`: jedyne miejsce, które dotyka wnętrzności PoB. Przy aktualizacji PoB naprawiamy tylko ten plik.
- `soe/engine/lua/bootstrap.lua`: odpala `HeadlessWrapper.lua` z PoB, podpina zlib z Pythona i pure-Lua shim za `lua-utf8`.
- Nową wersję PoB (np. 1.0 w dniu premiery) ściągasz przez `python scripts/fetch_pob.py <tag>` i zmianę `POB_VERSION`.

## Znane pułapki

- Pola tabel Lua o nazwach `items`, `keys`, `values` czytaj przez `tbl["items"]`, bo w lupa `.items` to metoda Pythona.
- LuaJIT na Windows rzuca wyjątek SEH `0xe24c4a02` przy każdym złapanym błędzie Lua. To nie crash; faulthandler w pytest jest wyłączony z tego powodu.
- Jedna instancja `PoB` na proces/wątek. Do równoległych obliczeń używaj wielu procesów.
