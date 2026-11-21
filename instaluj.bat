@echo off
rem Slop of Exile Helper: instalacja jednym kliknieciem (Windows 10/11).
rem Instaluje (jesli trzeba) Pythona i Gita przez winget, potem: srodowisko .venv, Path of Building,
rem baza wiedzy, dane z poe2db i skrot na pulpicie. Mozna uruchomic ponownie: robi tylko to, czego brakuje.
rem SOE_NO_SHORTCUT=1 pomija skrot, SOE_NO_PROMPT=1 nie pyta o uruchomienie na koncu.
setlocal EnableExtensions EnableDelayedExpansion
title Slop of Exile Helper - instalacja
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo  ==============================================
echo    Slop of Exile Helper - instalacja
echo  ==============================================
echo.

rem ---------------------------------------------------------------- 1. Python 3.12+
call :find_python
if not defined PY (
    echo [1/6] Nie ma Pythona 3.12 lub nowszego. Instaluje Pythona 3.13 przez winget...
    where winget >nul 2>&1 || goto no_winget
    winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
    call :find_python
)
if not defined PY (
    echo.
    echo Nie udalo sie znalezc Pythona po instalacji. Zamknij to okno, uruchom instaluj.bat jeszcze raz.
    echo Jesli dalej nie dziala: zainstaluj Pythona 3.13 z https://www.python.org/downloads/ ^(zaznacz "Add to PATH"^).
    goto fail
)
echo [1/6] Python: !PY!

rem ---------------------------------------------------------------- 2. Git (do pobrania Path of Building)
where git >nul 2>&1
if errorlevel 1 if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
where git >nul 2>&1
if errorlevel 1 (
    echo [2/6] Nie ma Gita ^(potrzebny do pobrania Path of Building^). Instaluje przez winget...
    where winget >nul 2>&1 || goto no_winget
    winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    if exist "%ProgramFiles%\Git\cmd\git.exe" set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
    if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "PATH=%LOCALAPPDATA%\Programs\Git\cmd;%PATH%"
)
where git >nul 2>&1 || (
    echo Nie udalo sie zainstalowac Gita. Zainstaluj go z https://git-scm.com/download/win i uruchom instaluj.bat ponownie.
    goto fail
)
echo [2/6] Git: OK

rem ---------------------------------------------------------------- 3. srodowisko i biblioteki
if not exist ".venv\Scripts\python.exe" (
    echo [3/6] Tworze srodowisko .venv...
    !PY! -m venv .venv || goto fail
)
echo [3/6] Instaluje biblioteki ^(chwile to trwa^)...
".venv\Scripts\python.exe" -m pip install -q --upgrade pip
".venv\Scripts\python.exe" -m pip install -q -e . || goto fail

rem ---------------------------------------------------------------- 4. Path of Building
if not exist "vendor\PathOfBuilding-PoE2\src\HeadlessWrapper.lua" (
    echo [4/6] Pobieram Path of Building ^(ok. 400 MB, kilka minut^)...
    ".venv\Scripts\python.exe" scripts\fetch_pob.py || goto fail
) else (
    echo [4/6] Path of Building: juz jest
)

rem ---------------------------------------------------------------- 5. dane gry
echo [5/6] Buduje baze wiedzy z danych gry...
".venv\Scripts\python.exe" -m soe.cli kb build >nul || goto fail
echo [5/6] Pobieram wagi modow, esencje i mody desecrated z poe2db ^(ok. 30 s^)...
".venv\Scripts\python.exe" -m soe.cli poe2db sync >nul
if errorlevel 1 echo        poe2db sie nie udalo: appka sprobuje sama przy starcie.

rem ---------------------------------------------------------------- 6. skrot
if "%SOE_NO_SHORTCUT%"=="1" (
    echo [6/6] Skrot pominiety.
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Slop of Exile Helper.lnk')); $s.TargetPath='%CD%\scripts\start.bat'; $s.WorkingDirectory='%CD%'; $s.IconLocation='%CD%\assets\soe.ico'; $s.Description='Slop of Exile Helper'; $s.Save()"
    echo [6/6] Skrot "Slop of Exile Helper" jest na pulpicie.
)

echo.
echo  Gotowe. Appke uruchamiasz skrotem na pulpicie albo plikiem uruchom.bat.
echo  Dane ^(nowe Path of Building, poe2db, ceny^) i sama appka aktualizuja sie przy starcie.
echo  Tryb AI w asystencie jest opcjonalny: wymaga Claude Code zalogowanego na tym komputerze.
echo.
set "RUN="
if not "%SOE_NO_PROMPT%"=="1" set /p RUN="Uruchomic appke teraz? [T/n] "
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
echo Brak winget ^(menedzer pakietow Windows^). Zainstaluj recznie:
echo   Python 3.13: https://www.python.org/downloads/  ^(zaznacz "Add to PATH"^)
echo   Git:         https://git-scm.com/download/win
echo i uruchom instaluj.bat ponownie.
goto fail

:fail
echo.
echo Instalacja przerwana. Zrob zrzut ekranu tego okna i wyslij go temu, kto dal Ci appke.
if not "%SOE_NO_PROMPT%"=="1" pause
exit /b 1
