@echo off
rem Stop every background BRT server started from this folder.
rem Usage: stop-brt.bat          (warns if agents are live)
rem        stop-brt.bat /force   (skips the check)
setlocal
cd /d "%~dp0"
set "PORT=%BRT_PORT%"
if "%PORT%"=="" set "PORT=8080"

rem Ask BRT who's on it before pulling the plug.
if /i "%~1"=="/force" goto :kill
set "LIVE="
for /f "delims=" %%n in ('curl.exe -s -f -m 3 http://127.0.0.1:%PORT%/admin/live-count 2^>nul') do set "LIVE=%%n"
if "%LIVE%"=="" goto :kill
if "%LIVE%"=="0" goto :kill
echo.
echo   %LIVE% agent(s) are on BRT right now. See http://127.0.0.1:%PORT%/admin/ for who's mid-review.
choice /c YN /m "  Stop BRT anyway"
if errorlevel 2 (
  echo BRT left running.
  exit /b 1
)

:kill
rem Match on the exact .venv\Scripts\pythonw.exe path, not a PID file. That catches every copy
rem (even if started twice) and can't hit an unrelated process that reused an old PID.
rem /T takes down the launcher's child interpreter too.
powershell -NoProfile -Command "$exe = Join-Path (Get-Location) '.venv\Scripts\pythonw.exe'; $p = @(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | Where-Object { $_.ExecutablePath -eq $exe }); if ($p.Count -eq 0) { 'BRT is not running.' } else { $p | ForEach-Object { taskkill /PID $_.ProcessId /T /F | Out-Null }; \"Stopped $($p.Count) BRT process(es).\" }"
if exist "%LOCALAPPDATA%\BRT\brt.pid" del "%LOCALAPPDATA%\BRT\brt.pid"
