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
| **0. Bootstrap** | 16–18.11 | Repo, submoduł PoB2, `lupa` ładuje PoB headless, wklejam kod buildu → dostaję DPS/EHP w JSON. |
| **1. Engine API** | 19–23.11 | `mutate()` dla node'ów drzewka, gemów, itemów, configu; snapshot/rollback; pula instancji; test wydajności (cel: >20 evali/s). |
| **2. Knowledge Base** | 21–25.11 | SQLite ze wszystkimi gemami/supportami/modami/unikatami/drzewkiem, wyszukiwarka, CLI `soe kb search "fire spell"`. |
| **3. MCP + Advisor v1** | 24–28.11 | Claude w Claude Code widzi narzędzia, odpowiada na „jak zwiększyć DPS tego buildu” na prawdziwych liczbach. |
| **4. Optymalizatory** | 26.11–4.12 | Stat weights, optymalizacja drzewka i supportów, raport „top 10 zmian za najmniej”. |
| **5. Combo + Crafting** | 1–9.12 | Graf interakcji i sugestie combosów; planer craftu (o ile dane wag modów będą dostępne). |
| **6. Launch pipeline** | 5–10.12 | Próba generalna na diffie 0.22 → 0.23; skrypt „nowy release → raport” w < 30 min. |
| **D-day** | 11.12+ | PoB wypuszcza dane 1.0 → odpalamy pipeline → ranking starterów i aktualizujemy wszystko. |

## 4. Ryzyka (szczerze)

1. **PoB 1.0 może wyjść z opóźnieniem** względem gry (zwykle godziny–2 dni). Pipeline musi być gotowy, żeby zadziałał w minuty po releasie.
2. **Headless PoB na Windows** — potrzebuje LuaJIT + kilku modułów C (np. `lua-utf8`, zlib do kodów buildu). Zamiast tego dekodujemy kody w Pythonie, a moduły stubujemy. Fallback: build LuaJIT ze źródeł albo WSL.
3. **Wydajność** — pełny przelicz PoB to ~50–300 ms. Optymalizator musi być sprytny (heurystyka + PoB do weryfikacji), plus wiele procesów równolegle.
4. **Wagi modów do craftingu** — PoB ma mody i tiery, ale nie zawsze spawn weights. Może trzeba będzie dociągnąć dane z exportu plików gry (narzędzia typu RePoE/poe2db). Do sprawdzenia w fazie 2.
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
