@echo off
rem Weekly step 4: bring the live BRT up to date with the approved code on GitHub (main).
rem Order matters: check nobody's mid-review BEFORE pulling, so the running server never serves
rem new static files with old code for longer than the test run.
setlocal
cd /d "%~dp0"
set "PORT=%BRT_PORT%"
if "%PORT%"=="" set "PORT=8080"

set "LIVE="
for /f "delims=" %%n in ('curl.exe -s -f -m 3 http://127.0.0.1:%PORT%/admin/live-count 2^>nul') do set "LIVE=%%n"
if "%LIVE%"=="" goto :pull
if "%LIVE%"=="0" goto :pull
echo.
echo   %LIVE% agent(s) are on BRT right now. Who: http://127.0.0.1:%PORT%/admin/
choice /c YN /m "  Deploy anyway? They will be cut off"
if errorlevel 2 goto :abort

:pull
echo Pulling main...
git pull --ff-only origin main
if errorlevel 1 goto :fail_pull
".venv\Scripts\pip.exe" install -q -r requirements.txt
if errorlevel 1 goto :fail_deps
echo Running tests...
".venv\Scripts\pytest.exe" -q
if errorlevel 1 goto :fail_tests

call "%~dp0stop-brt.bat" /force
call "%~dp0start-brt.bat"
echo Deployed.
exit /b 0

:fail_pull
echo Pull failed: local changes or a diverged branch. Nothing was changed. BRT still running.
exit /b 1
:fail_deps
echo Installing requirements failed. BRT still running on the old code.
exit /b 1
:fail_tests
echo TESTS FAILED. BRT was NOT restarted and is still running the old code.
echo Fix on a branch, or roll back with: git reset --hard ORIG_HEAD
exit /b 1
:abort
echo Deploy cancelled. Nothing changed.
exit /b 1
