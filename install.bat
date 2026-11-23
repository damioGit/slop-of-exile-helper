@echo off
rem Slop of Exile Helper: one-click install (Windows 10/11).
rem Installs Python and Git with winget when missing, then: the .venv environment, Path of Building,
rem the knowledge base, poe2db data and a desktop shortcut. Safe to run again: it only does what is missing.
rem SOE_NO_SHORTCUT=1 skips the shortcut, SOE_NO_PROMPT=1 does not ask to start the app at the end.
setlocal EnableExtensions EnableDelayedExpansion
title Slop of Exile Helper - install
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo  ==============================================
echo    Slop of Exile Helper - install
echo  ==============================================
echo.

rem ---------------------------------------------------------------- 1. Python 3.12+
call :find_python
if not defined PY (
    echo [1/6] No Python 3.12 or newer. Installing Python 3.13 with winget...
    where winget >nul 2>&1 || goto no_winget
    winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
    call :find_python
)
if not defined PY (
    echo.
    echo Python was not found after installing it. Close this window and run install.bat again.
    echo If it still fails: install Python 3.13 from https://www.python.org/downloads/ ^(tick "Add to PATH"^).
    goto fail
)
echo [1/6] Python: !PY!

rem ---------------------------------------------------------------- 2. Git (to download Path of Building)
where git >nul 2>&1
if errorlevel 1 if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
where git >nul 2>&1
if errorlevel 1 (
    echo [2/6] No Git ^(needed to download Path of Building^). Installing it with winget...
    where winget >nul 2>&1 || goto no_winget
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
    if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;%PATH%"
)
where git >nul 2>&1 || (
    echo Git could not be installed. Install it from https://git-scm.com/download/win and run install.bat again.
    goto fail
)
echo [2/6] Git: OK

rem ---------------------------------------------------------------- 3. environment and libraries
if not exist ".venv\Scripts\python.exe" (
    echo [3/6] Creating the .venv environment...
    !PY! -m venv .venv || goto fail
)
echo [3/6] Installing libraries ^(takes a moment^)...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -e . || goto fail

rem ---------------------------------------------------------------- 4. Path of Building
if not exist "vendor\PathOfBuilding-PoE2\src\HeadlessWrapper.lua" (
    echo [4/6] Downloading Path of Building ^(about 400 MB, a few minutes^)...
    ".venv\Scripts\python.exe" scripts\fetch_pob.py || goto fail
) else (
    echo [4/6] Path of Building: already there
)

rem ---------------------------------------------------------------- 5. game data
echo [5/6] Building the knowledge base from the game data...
".venv\Scripts\python.exe" -m soe.cli kb build >nul || goto fail
echo [5/6] Downloading mod weights, essences and desecrated mods from poe2db ^(about 30 s^)...
".venv\Scripts\python.exe" -m soe.cli poe2db sync >nul
if errorlevel 1 echo        poe2db failed: the app will try again on start.

rem ---------------------------------------------------------------- 6. shortcut
if "%SOE_NO_SHORTCUT%"=="1" (
    echo [6/6] Shortcut skipped.
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Slop of Exile Helper.lnk')); $s.TargetPath='%CD%\scripts\start.bat'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\assets\soe.ico'; $s.Description='Slop of Exile Helper'; $s.Save()"
    echo [6/6] The "Slop of Exile Helper" shortcut is on the desktop.
)

echo.
echo  Done. Start the app with the desktop shortcut or run.bat.
echo  Data ^(new Path of Building, poe2db, prices^) and the app itself update on start.
echo  AI mode in the assistant is optional: it needs Claude Code logged in on this computer.
echo.
set "RUN="
if not "%SOE_NO_PROMPT%"=="1" set /p RUN="Start the app now? [Y/n] "
if "%SOE_NO_PROMPT%"=="1" set "RUN=n"
rem Last line on purpose: linking to GitHub can replace this file with a newer one, so nothing may come after it.
".venv\Scripts\python.exe" scripts\self_update.py --attach & (if /i not "!RUN!"=="n" start "" "%CD%\scripts\start.bat") & exit /b 0

rem ---------------------------------------------------------------- helpers
:find_python
set "PY="
for %%V in (3.14 3.13 3.12) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    for %%V in (314 313 312) do (
        if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe""
    )
)
exit /b 0

:no_winget
echo winget ^(the Windows package manager^) is missing. Install by hand:
echo   Python 3.13: https://www.python.org/downloads/  ^(tick "Add to PATH"^)
echo   Git:         https://git-scm.com/download/win
echo then run install.bat again.
goto fail

:fail
echo.
echo Install stopped. Take a screenshot of this window and send it to whoever gave you the app.
if not "%SOE_NO_PROMPT%"=="1" pause
exit /b 1
