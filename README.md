# Slop of Exile Helper

Lokalna appka do Path of Exile 2, która mówi, co poprawić w buildzie i jak to wycraftować. Wszystko liczy prawdziwym silnikiem **Path of Building (PoE2)** na Twojej postaci, a nie z pamięci czy z poradników. Dane modów i craftingu bierze z **poe2db**, a ceny z **poe.ninja**.

Działa w przeglądarce, na Twoim komputerze. Twój build zostaje u Ciebie.

> **Claude nie jest potrzebny.** Cała appka działa bez AI: liczenie, Kuźnia, Gear, drzewko, trade i aktualizacje. Claude to opcjonalny dodatek dla tych, którzy mają Claude Code (patrz [niżej](#opcjonalnie-claude)).

## Instalacja (Windows 10/11)

1. Pobierz `slop-of-exile-helper-vX.Y.Z.zip` z **[Releases](https://github.com/damioGit/slop-of-exile-helper/releases/latest)** i rozpakuj go w stałe miejsce. Potrzeba ok. 1 GB.
2. Kliknij dwa razy **`instaluj.bat`**. Jeśli nie masz Pythona albo Gita, instalator doinstaluje je sam (winget). Pobranie Path of Building trwa kilka minut.
3. Uruchamiasz skrótem **Slop of Exile Helper** na pulpicie (albo `uruchom.bat`). Appka otworzy się w przeglądarce, a zamknięcie czarnego okna ją wyłącza.
4. Wklej kod buildu z Path of Building albo zaimportuj postać z poe.ninja (`Nazwa#1234` + nazwa postaci).

Jak coś nie wyjdzie, uruchom `instaluj.bat` jeszcze raz: robi tylko to, czego brakuje.

## Co potrafi

- **Asystent:** szybki przegląd buildu w kilka sekund:
  - resy do capu, brakujące atrybuty, spirit, czy mana się trzyma;
  - typ obrażeń, który najsłabiej znosisz (największy przeżywalny hit);
  - co wymienić najpierw i najlepsze pasywki w zasięgu.

  Do tego pytania pisane po swojemu („nie oneshotuję bossa, jak bić mocniej?”). Odpowiedź to lista zmian z zyskiem i kosztem, każda z przyciskiem „Zastosuj”.
- **Gear:** ekwipunek wygląda jak w grze. Dla każdego itemu widzisz:
  - ile jest wart każdy mod i czy opłaca się Exalt, Chaos, Annul albo Fracture (z szansami i cenami);
  - który slot wymienić najpierw w porównaniu z realnym rare na Twój level;
  - przepis na lepszy item;
  - wyszukiwanie zamienników na oficjalnym trade, przeliczonych w PoB na Twoim buildzie.
- **Kuźnia:** wybierasz bazę i mody albo klikasz „ułóż cel pod mój build”. Appka porównuje drogi craftu:
  - esencje i Perfect Essence;
  - omeny Exaltation, Annulment i Crystallisation;
  - desecration (kości);
  - Greater/Perfect Exalty;
  - tanie bazy do 5/6 z dokończeniem.

  Dostajesz szansę na próbę, koszt do skutku i koszt, gdy wystarczy 4/6 albo 5/6. Widzisz też, ile DPS i EHP da ten item Twojej postaci. Mody, które na danej bazie praktycznie nie wypadają, są oznaczone od razu.
- **Skille:** gemy z opisami z gry, DPS każdego skilla, supporty, które nie działają (z powodem), i optymalizator supportów.
- **Drzewko:** drzewo pasywne jak w PoB, najlepsze nowe pasywki, co zwolnić i optymalizator drzewka.
- **Plan i Synergie:** wszystkie zmiany policzone razem; mechaniki, które build tworzy i z których korzysta; warunki z configu bez źródła w buildzie (czyli DPS jest zawyżony).

## Aktualizacje same się robią

Przy starcie i co kilka godzin appka sprawdza:
- **nowe Path of Building:** instaluje je dopiero po teście na buildach wzorcowych, więc na premierę nowej ligi albo 1.0 nic nie trzeba robić;
- **dane z poe2db:** wagi modów, esencje, mody desecrated;
- **zasady craftingu:** jeśli GGG zmieni działanie orba albo omena, appka to zgłosi;
- **ceny z poe.ninja i aktualną ligę;**
- **nową wersję samej appki** z tego repo (można to wyłączyć).

Stan danych widać w panelu **„Dane i aktualizacje”**. Jest tam też przycisk „Wymuś pełną aktualizację”, który pobiera wszystko od nowa.

## Opcjonalnie: Claude

Appka **nie wymaga** Claude'a. Jeśli masz [Claude Code](https://claude.com/claude-code), możesz go podpiąć na dwa sposoby:
- **Checkbox „AI” w Asystencie:** pytanie trafia do Claude Code zalogowanego na Twoim koncie. Claude używa tych samych narzędzi co appka i może szukać na wiki, więc rozumie dowolne pytania. Bez Claude Code checkbox po prostu nie zadziała, a reszta appki działa normalnie.
- **Serwer MCP `soe`** (zarejestrowany w `.mcp.json`): w Claude Code w tym folderze rozmawiasz o buildzie, a Claude liczy wszystko w PoB przez ~40 narzędzi (`load_build`, `checkup`, `optimize_supports`, `craft_routes`, `find_upgrade`...). Zasady odpowiadania są w [CLAUDE.md](CLAUDE.md).

## Ważne do wiedzenia

- **Szanse craftu to symulacja na wagach modów z poe2db.** Przy desecration poe2db nie mówi, jak często opcje to zwykłe mody bazy. To założenie jest opisane przy wynikach.
- **Import postaci działa dla publicznych postaci, które zna poe.ninja.** Przy zbyt wielu zapytaniach poe.ninja chwilowo blokuje dostęp i wtedy ceny lecą z cache.
- **Brak ceny na poe.ninja znaczy „nieznana”.** Nic nie jest zgadywane.
- **Projekt fanowski, niezwiązany z Grinding Gear Games.**

---

## Dla programistów

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python scripts/fetch_pob.py      # PoB w wersji z POB_VERSION -> vendor/
.venv/Scripts/soe kb build                     # baza wiedzy z danych PoB
.venv/Scripts/soe poe2db sync                  # wagi modów, esencje, mody desecrated
.venv/Scripts/python -m pytest
```

Najważniejsze komendy:

```bash
.venv/Scripts/soe web                          # appka: http://127.0.0.1:8765
.venv/Scripts/soe eval <kod buildu PoB>        # DPS, EHP, resy, atrybuty
.venv/Scripts/soe refresh [--full]             # sprawdź / wymuś aktualizację danych
.venv/Scripts/soe update [tag]                 # nowe PoB: pobierz -> test silnika -> baza -> raport zmian
.venv/Scripts/soe kb search life leech         # baza wiedzy: gemy, mody, bazy, unikaty, notable
.venv/Scripts/python scripts/make_package.py   # zip dla graczy -> dist/
```

Budowa projektu:
- **`soe/engine/`:** PoB2 headless w Pythonie (LuaJIT przez `lupa`).
  - `pob.py` ma what-if bez zmiany buildu (~130/s na rdzeń);
  - `pool.py` to pula procesów;
  - `lua/soe_api.lua` to jedyny plik, który dotyka wnętrzności PoB.
- **`soe/kb/`:** baza wiedzy z danych PoB oraz `poe2db.py` (wagi, esencje, desecrated) i `craft_rules.py` (czujnik zasad craftingu).
- **`soe/items/`:** Kuźnia (`crafter.py`), gear (`gear.py`, `craftplan.py`, `forge_build.py`), unikaty, mody.
- **`soe/optimize/`:** cel (ważony DPS/EHP z karami), wagi statów, supporty, drzewko, plan.
- **`soe/advisor/`:** sesja, check-up, szybki przegląd i serwer MCP.
- **`soe/web/`:** FastAPI i jeden plik `index.html` (bez builda, polski UI).
- **`soe/prices/`:** poe.ninja, trade, import postaci.
- **`soe/pipeline/`:** aktualizacje (`autoupdate.py`, `update.py`) i raport zmian między wersjami.
- **Testy:** `pytest`, ok. 4 min. Pilnują między innymi, żeby w repo nie było tokenów, haseł ani prywatnych ścieżek.

Pułapki: pola tabel Lua o nazwach `items`, `keys` i `values` czytaj przez `tbl["items"]` (w lupa `.items` to metoda Pythona). LuaJIT na Windows rzuca SEH `0xe24c4a02` przy złapanych błędach Lua: to nie crash. Jedna instancja `PoB` na proces.

## Źródła i podziękowania

- [Path of Building Community (PoE2)](https://github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2): silnik obliczeń, pobierany przy instalacji.
- [poe2db.tw](https://poe2db.tw): wagi modów, esencje, mody desecrated, opisy orbów, ikony.
- [poe.ninja](https://poe.ninja): ceny i publiczne postacie.
- Format check-upu wzorowany na [Exile Build Advisor](https://github.com/reytla/exile-build-adviser) (reytla, MIT). Szczegóły są w [NOTICE](NOTICE).
