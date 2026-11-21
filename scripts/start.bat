@echo off
rem Uruchamia appke Slop of Exile Helper i otwiera ja w przegladarce.
rem Zamkniecie tego okna wylacza appke.
title Slop of Exile Helper
cd /d "%~dp0.."
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo Brak srodowiska .venv. Zrob setup z README.md:
    echo   py -m venv .venv
    echo   .venv\Scripts\python -m pip install -e ".[dev]"
    echo   .venv\Scripts\python scripts\fetch_pob.py
    echo   .venv\Scripts\soe kb build
    pause
    exit /b 1
)
if not exist "vendor\PathOfBuilding-PoE2\src\HeadlessWrapper.lua" (
    echo Pobieram Path of Building...
    ".venv\Scripts\python.exe" scripts\fetch_pob.py || (pause & exit /b 1)
)
if not exist "data\kb.current" if not exist "data\kb.sqlite" (
    echo Buduje baze wiedzy...
    ".venv\Scripts\python.exe" -m soe.kb.build || (pause & exit /b 1)
)

rem nowa wersja appki z GitHuba (opcja w panelu Dane): po aktualizacji ten plik startuje od nowa, w tej samej linii
".venv\Scripts\python.exe" scripts\self_update.py & if errorlevel 5 (set SOE_UPDATED=1& call "%~f0" %* & exit /b)

rem 3 = "Aktualizuj appke" w aplikacji: po aktualizacji appka startuje od nowa (bez otwierania nowej karty)
set SOE_RESTART_CODE=3
set OPEN=--open
:run
".venv\Scripts\python.exe" -m soe.web.app %OPEN%
if errorlevel 3 if not errorlevel 4 (
    set OPEN=
    echo Uruchamiam nowa wersje...
    goto run
)
if errorlevel 1 pause
