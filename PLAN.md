# SLOP OF EXILE HELPER — plan działania

> Optymalizator buildów do Path of Exile 2 z podpowiedziami, sugestiami, crafting helperem
> i silnikiem combo. Liczy na prawdziwym kalkulatorze Path of Building (PoE2),
> a myśli Claude'em.
>
> **Deadline:** PoE2 1.0 — **11 grudnia 2026** (od dziś, 16.11, mamy 25 dni).

---

## 1. Idea w jednym zdaniu

Nie piszemy własnego kalkulatora obrażeń (to by zajęło rok i byłoby błędne).
**Bierzemy silnik PoB2 jako bibliotekę** (Lua odpalane headless), owijamy go w API,
które pozwala *zmieniać build i liczyć wynik tysiące razy*, a na to kładziemy:
bazę wiedzy, optymalizatory, silnik interakcji i Claude'a jako mózg rozmowy z graczem.

## 1b. Scenariusze (przykłady, nie zamknięta lista)

Helper ma odpowiadać na **dowolne** pytanie o build, np.:
- „Podoba mi się unikat X, zagram pod to?” (rozpisane niżej jako wzór),
- „Jak zwiększyć DPS / przeżywalność za mniej niż N divine?”,
- „Jaki skill + supporty dają najlepszy clear przy tym gearze?”,
- „Co craftować na ten slot i jak?”,
- „Jakie combo wykorzystuje mechanikę Y?”,
- „Zrób mi league startera pod styl Z”.

Każdy działa tym samym schematem: **wczytaj → zrozum (KB + combo) → przelicz na PoB → zoptymalizuj → wyjaśnij**.

### Przykład rozpisany: build pod unikat

> **Gracz:** „Podoba mi się unikat X, a to moja postać” *(kod PoB / import postaci)*.

Co robi helper, krok po kroku:

1. **Wczytuje postać** do silnika PoB i liczy stan wyjściowy: DPS, EHP, resy, atrybuty, sloty.
2. **Czyta unikat z KB**: jego mody, tagi, mechaniki, np. „konwertuje X na Y” albo „triggeruje Z”.
3. **Analizuje dopasowanie** przez silnik combo: które obecne skille i supporty z nim działają, a co się gryzie albo traci wartość.
4. **Liczy na prawdziwym PoB**: wkłada unikat w slot i pokazuje różnicę (DPS, EHP, co się zepsuło: resy, atrybuty, requirementy).
5. **Naprawia build**: optymalizator szuka zmian, które wykorzystują unikat, czyli przepięcie supportów, inny main skill, przestawienie node'ów na drzewku, zmiana ascendancy.
6. **Uzupełnia dziury**: stat weights mówią, czego brakuje na gearze („potrzebujesz +40% fire res i ~60 str”), a crafting podpowiada, jak to zrobić najtaniej.
7. **Werdykt i plan** od Claude'a, ludzkim językiem:
   - „Tak, możesz pod to zagrać. Będzie optymalnie, jeśli zrobisz A, B, C” (z liczbami przed i po),
   - albo „Nie warto, bo…, ale ten unikat świetnie działa z buildem W”,
   - lista: gemy, supporty, node'y, crafty w kolejności priorytetu i kosztu.

Każdy moduł poniżej istnieje po to, żeby ten scenariusz działał.

## 1c. Decyzje (16.11.2026)

| Temat | Decyzja |
|---|---|
| Mózg | **Serwer MCP w Claude Code.** Claude woła narzędzia helpera, bez osobnych kosztów API. |
| UI na premierę | **Lokalna web appka**: wklejasz kod buildu, widzisz staty, drzewko, porównania i plan zmian. Rozmowa idzie przez Claude Code, a appka i MCP korzystają z tego samego backendu, więc to, co policzy Claude, od razu widać w appce. |
| Priorytety na 11.12 | 1) optymalizacja Twojej postaci, 2) crafting helper, 3) Q&A o mechanikach i combosach. Ranking starterów schodzi na później. |
| Ceny | Tak, z poe.ninja i trade, od fazy 4. Sugestie typu „najtaniej” w divine/exalt. |

Konsekwencja: dochodzi warstwa **`api/`** (lokalny serwer HTTP, FastAPI), z której korzystają i serwer MCP, i web appka. Faza 6 to UI zamiast rankingu starterów, a pipeline premierowy zostaje, bo i tak trzeba szybko wciągnąć dane 1.0.

## 2. Architektura

```
                ┌──────────────────────────────────────────────┐
  gracz  ───►   │  ADVISOR (Claude)  — pytania, sugestie,       │
  (pytania)     │  wyjaśnienia, "dlaczego"                      │
                └───────────────▲──────────────────────────────┘
                                │ narzędzia (MCP)
   ┌───────────────┬────────────┼─────────────┬─────────────────┐
   │ KNOWLEDGE BASE│ OPTIMIZER  │ COMBO ENGINE│ CRAFTING        │
   │ gemy, skille, │ drzewko,   │ tagi, inter-│ mod pool, tiery,│
   │ supporty, mody│ gemy, gear,│ akcje, kon- │ wagi, ścieżki   │
   │ unikaty, bazy │ stat weights│ wersje, trig│ craftu, koszt   │
   └──────▲────────┴─────▲──────┴──────▲──────┴────────▲────────┘
          │              │             │               │
   ┌──────┴──────────────┴─────────────┴───────────────┴───────┐
   │  ENGINE — most do PoB2 (Python + lupa/LuaJIT, headless)    │
   │  load(build code) → mutate(node/gem/item/config) → calc()  │
   └──────────────────────────▲─────────────────────────────────┘
                              │ git submodule, przypięta wersja
                   PathOfBuilding-PoE2 (src/)
```

### Moduły

| Moduł | Co robi | Tech |
|---|---|---|
| `engine/` | Odpala PoB2 headless, ładuje build (kod pobb / XML / JSON postaci z API GGG), robi zmiany i zwraca **wszystkie** staty jako JSON. Snapshot/rollback, żeby testować tysiące wariantów. | Python + `lupa` (wbudowany LuaJIT) |
| `kb/` | Eksport danych PoB (`src/Data`, `TreeData`) do SQLite + wyszukiwanie pełnotekstowe. Gemy, supporty, tagi, mody z tierami, bazy, unikaty, drzewko, ascendancy. | Python, SQLite FTS5 |
| `combo/` | Graf interakcji: tagi skilli ↔ supporty, konwersje obrażeń, triggery, ailmenty, „co skaluje co”. Wykrywa synergie i zakazane kombinacje. | Python, reguły + dane z KB |
| `optimizer/` | Drzewko (beam search po ścieżkach, wartość na punkt), gemy i supporty (permutacje z prune), **stat weights** dla gearu („ile DPS daje +1% X”), balans DPS vs EHP vs koszt. | Python, wielowątkowo (wiele instancji PoB) |
| `crafting/` | Pule modów dla bazy/ilvl, tiery, wagi, plan craftu krok po kroku z szansami i kosztem w currency. | Python + dane z exportu gry |
| `advisor/` | **Serwer MCP** z narzędziami (`search_kb`, `eval_build`, `try_change`, `optimize_tree`, `suggest_supports`, `stat_weights`, `plan_craft`, `explain`…). Claude rozmawia z graczem i woła narzędzia. | Python MCP SDK |
| `pipeline/` | **Dzień premiery:** pobiera nowy release PoB, re-eksportuje dane, robi diff (nerfy/buffy/nowe gemy/unikaty), odpala ranking league starterów. | Python + `gh` |
| `ui/` | Później. Lokalna appka webowa (wklejasz kod buildu, czat, wykresy). | TBD |

## 3. Fazy i harmonogram

| Faza | Termin | Cel — „gotowe” gdy… |
|---|---|---|
| **0. Bootstrap** ✅ | 16.11 | Repo, submoduł PoB2, `lupa` ładuje PoB headless, wklejam kod buildu → dostaję DPS/EHP w JSON. |
| **1. Engine API** ✅ | 16.11 | `mutate()` dla node'ów drzewka, gemów, itemów, configu; snapshot/rollback; pula instancji; test wydajności (cel: >20 evali/s). |
| **2. Knowledge Base** ✅ | 16.11 | SQLite ze wszystkimi gemami/supportami/modami/unikatami/drzewkiem, wyszukiwarka, CLI `soe kb search "fire spell"`. |
| **3. MCP + Advisor v1** | 24–28.11 | Claude w Claude Code widzi narzędzia, odpowiada na „jak zwiększyć DPS tego buildu” na prawdziwych liczbach. |
| **4. Optymalizatory** | 26.11–4.12 | Stat weights, optymalizacja drzewka i supportów, raport „top 10 zmian za najmniej”. |
| **5. Combo + Crafting** | 1–9.12 | Graf interakcji i sugestie combosów; planer craftu (o ile dane wag modów będą dostępne). |
| **6. Web appka + launch pipeline** | 3–10.12 | Lokalna appka (build, staty, drzewko, plan zmian). Skrypt „nowy release PoB → dane gotowe” w < 30 min, próba na 0.22 → 0.23. |
| **D-day** | 11.12+ | PoB wypuszcza dane 1.0 → odpalamy pipeline → ranking starterów i aktualizujemy wszystko. |

## 4. Ryzyka (szczerze)

1. **PoB 1.0 może wyjść z opóźnieniem** względem gry (zwykle godziny–2 dni). Pipeline musi być gotowy, żeby zadziałał w minuty po releasie.
2. **Headless PoB na Windows** — potrzebuje LuaJIT + kilku modułów C (np. `lua-utf8`, zlib do kodów buildu). Zamiast tego dekodujemy kody w Pythonie, a moduły stubujemy. Fallback: build LuaJIT ze źródeł albo WSL.
3. **Wydajność** — pełny przelicz PoB to ~50–300 ms. Optymalizator musi być sprytny (heurystyka + PoB do weryfikacji), plus wiele procesów równolegle.
4. **Wagi modów do craftingu** — sprawdzone 16.11: PoB ma dla każdego moda tylko 0/1 („może wypaść na tym slocie” albo nie), bez prawdziwych wag. Wg r/pathofexiledev pliki PoE2 w ogóle nie mają wag, bo GGG trzyma je na serwerze. Plan na fazę 5: liczymy, co może wypaść na danej bazie i ilvl (pula modów, tiery, grupy, prefix/suffix) przy równych wagach, a wagi od społeczności (wiki PoE2 ma tabelę spawn weights) dokładamy jako opcjonalną poprawkę. Szanse pokazujemy jako przybliżone.
5. **„Wszystko”** — robimy to warstwami. Każda faza daje coś, czego da się używać od razu, zamiast jednego wielkiego wybuchu 10 grudnia.
6. **ToS** — tylko dane z PoB, publiczne API i pliki gry offline. Zero automatyzacji klienta gry.

## 5. Struktura repo (docelowa)

```
slop-of-exile-helper/
├─ vendor/PathOfBuilding-PoE2/   # submodule, przypięty tag
├─ soe/
│  ├─ engine/      # most do PoB
│  ├─ kb/          # baza wiedzy
│  ├─ combo/       # interakcje
│  ├─ optimizer/
│  ├─ crafting/
│  ├─ advisor/     # serwer MCP
│  └─ pipeline/    # launch day
├─ data/           # wygenerowane (gitignore), SQLite, cache
├─ tests/          # buildy referencyjne + oczekiwane liczby
└─ PLAN.md
```

## 6. Najbliższe kroki (faza 0)

1. Dodać PoB2 jako submoduł (sparse checkout `src/` + `runtime/lua`, repo ma ~1.8 GB).
2. `pip install lupa` → sprawdzić, czy to wersja z LuaJIT 2.1.
3. Odpalić `HeadlessWrapper.lua` przez lupa, stuby dla brakujących modułów.
4. Dekoder kodów pobb.in (base64url + zlib → XML) w Pythonie.
5. Test: 3 referencyjne buildy → porównanie DPS z GUI PoB (tolerancja 0.1%).
