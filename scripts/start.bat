@echo off
rem Starts Slop of Exile Helper and opens it in the browser.
rem Closing this window stops the app.
title Slop of Exile Helper
cd /d "%~dp0.."
chcp 65001 >nul

if not exist ".venv\Scripts\python.exe" (
    echo No .venv environment. Run install.bat, or set it up as in README.md:
    echo   py -m venv .venv
    echo   .venv\Scripts\python -m pip install -e ".[dev]"
    echo   .venv\Scripts\python scripts\fetch_pob.py
    echo   .venv\Scripts\soe kb build
    pause
    exit /b 1
)
if not exist "vendor\PathOfBuilding-PoE2\src\HeadlessWrapper.lua" (
    echo Downloading Path of Building...
    ".venv\Scripts\python.exe" scripts\fetch_pob.py || (pause & exit /b 1)
)
if not exist "data\kb.current" if not exist "data\kb.sqlite" (
    echo Building the knowledge base...
    ".venv\Scripts\python.exe" -m soe.kb.build || (pause & exit /b 1)
)

rem a new app version from GitHub (switch in the Data panel): after an update this file starts again, on the same line
".venv\Scripts\python.exe" scripts\self_update.py & if errorlevel 5 (set SOE_UPDATED=1& call "%~f0" %* & exit /b)

rem exit code 3 = "Update the app" in the app: after the update the app starts again (without a new browser tab)
set SOE_RESTART_CODE=3
set OPEN=--open
:run
".venv\Scripts\python.exe" -m soe.web.app %OPEN%
if errorlevel 3 if not errorlevel 4 (
    set OPEN=
    echo Starting the new version...
    goto run
)
if errorlevel 1 pause
