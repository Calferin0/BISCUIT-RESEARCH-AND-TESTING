@echo off
rem Start BRT in the background (no console window). Log: %LOCALAPPDATA%\BRT\brt.log
rem To start at login: put a shortcut to this file in shell:startup
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto :nosetup
set "PORT=%BRT_PORT%"
if "%PORT%"=="" set "PORT=8080"

rem Already up? Then don't start a second copy. (run.py also refuses to share the port.)
curl.exe -s -f -m 2 -o nul http://127.0.0.1:%PORT%/admin/live-count
if not errorlevel 1 (
  echo BRT is already running. Admin page: http://127.0.0.1:%PORT%/admin/
  exit /b 0
)

start "" ".venv\Scripts\pythonw.exe" run.py
echo BRT starting in the background.
echo Admin page (this PC only): http://127.0.0.1:%PORT%/admin/
echo If it doesn't come up, check %LOCALAPPDATA%\BRT\brt.log
exit /b 0

:nosetup
echo No .venv found. One-time setup:
echo   py -3.14 -m venv .venv
echo   .venv\Scripts\pip install -r requirements.txt
exit /b 1
