@echo off
setlocal EnableExtensions
title DawnDine
cd /d "%~dp0..\.."

if not defined DAWNDINE_PORT set "DAWNDINE_PORT=7860"
set "DAWNDINE_URL=http://127.0.0.1:%DAWNDINE_PORT%"
set "PYTHONUTF8=1"

where uv >nul 2>nul
if errorlevel 1 goto :no_uv

if not exist ".venv" (
    echo [INFO] .venv not found. Running first-time setup now...
    set "DAWNDINE_SILENT_SETUP=1"
    call "%~dp0setup.bat"
    if not exist ".venv" goto :need_setup
)
if not exist ".env" (
    echo [WARN] .env not found. The page still opens; each visitor can enter
    echo        their own DashScope Key in the Settings dialog.
    echo.
)

if /I "%DAWNDINE_KEEP_RUNNING%"=="1" goto :keep_running

rem Stop an old DawnDine server so the latest code is loaded.
rem Exit codes: 1 = port free, 2 = old DawnDine stopped, 3 = port used by others.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port = %DAWNDINE_PORT%; $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if (-not $c) { exit 1 }; $procId = $c.OwningProcess; $proc = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $procId); if ($proc.CommandLine -match 'dawndine') { Stop-Process -Id $procId -Force; for ($i = 0; $i -lt 24; $i++) { if (-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Milliseconds 250 }; exit 2 }; exit 3"
set "DAWNDINE_PORT_STATE=%errorlevel%"

if "%DAWNDINE_PORT_STATE%"=="3" goto :port_busy
if "%DAWNDINE_PORT_STATE%"=="2" (
    echo.
    echo [INFO] Stopped the old DawnDine process so the latest code can load.
    echo.
)
goto :start_server

:keep_running
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-NetTCPConnection -LocalPort %DAWNDINE_PORT% -State Listen -ErrorAction SilentlyContinue; if ($c) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
    echo.
    echo DawnDine is already running at %DAWNDINE_URL%
    if /I not "%DAWNDINE_NO_BROWSER%"=="1" start "" "%DAWNDINE_URL%"
    echo.
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)
goto :start_server

:port_busy
echo.
echo [ERROR] Port %DAWNDINE_PORT% is used by another program.
echo Close it, or set DAWNDINE_PORT to another port, then run again.
echo.
pause
exit /b 1

:start_server
echo.
echo Starting DawnDine...
echo URL: %DAWNDINE_URL%
echo Keep this window open while using the app. Press Ctrl+C to stop.
echo.

uv run dawndine
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo DawnDine exited with code %EXITCODE%.
    echo Check:
    echo   1. run scripts\windows\setup.bat once;
    echo   2. .env contains DASHSCOPE_API_KEY;
    echo   3. port %DAWNDINE_PORT% is free;
    echo   4. the error message above.
    echo.
    pause
)

exit /b %EXITCODE%

:need_setup
echo.
echo [ERROR] .venv not found. Run scripts\windows\setup.bat first.
echo.
pause
exit /b 1

:no_uv
echo.
echo [ERROR] uv was not found in PATH.
echo Run scripts\windows\setup.bat to install everything automatically.
echo.
pause
exit /b 1
