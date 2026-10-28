@echo off
setlocal EnableExtensions
title Campus Canteen Assistant
cd /d "%~dp0"

set "DAWNDINE_URL=http://127.0.0.1:7860"
set "PYTHONUTF8=1"

where uv >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] uv was not found in PATH.
    echo Install uv first: https://docs.astral.sh/uv/
    echo After installation, close this window and double-click this file again.
    echo.
    pause
    exit /b 1
)

rem If the server is already running, only open the page.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = Get-NetTCPConnection -LocalPort 7860 -State Listen -ErrorAction SilentlyContinue; if ($c) { exit 0 } else { exit 1 }"
if %errorlevel%==0 (
    echo.
    echo Campus Canteen Assistant is already running at %DAWNDINE_URL%
    if /I not "%DAWNDINE_NO_BROWSER%"=="1" (
        start "" "%DAWNDINE_URL%"
    ) else (
        echo Browser opening skipped because DAWNDINE_NO_BROWSER=1
    )
    echo.
    ping -n 3 127.0.0.1 >nul
    exit /b 0
)

if not exist ".env" (
    echo.
    echo [WARN] .env was not found.
    echo The web page can still start and the watermark workbench works,
    echo but chat and knowledge retrieval need DASHSCOPE_API_KEY.
    echo Copy .env.example to .env, fill the key, then restart.
    echo.
)

echo.
echo Starting Campus Canteen Assistant...
echo URL: %DAWNDINE_URL%
echo Keep this window open while using the app. Press Ctrl+C to stop.
echo.

uv run main.py
set "EXITCODE=%errorlevel%"

if not "%EXITCODE%"=="0" (
    echo.
    echo Campus Canteen Assistant exited with code %EXITCODE%.
    echo Check:
    echo   1. uv sync has been run;
    echo   2. .env contains DASHSCOPE_API_KEY;
    echo   3. port 7860 is not used by another program;
    echo   4. the error message above.
    echo.
    pause
)

exit /b %EXITCODE%

