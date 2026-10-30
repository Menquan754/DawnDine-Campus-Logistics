@echo off
chcp 65001 >nul
setlocal EnableExtensions
title DawnDine First Setup
cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "UV_LINK_MODE=copy"

echo ============================================================
echo  DawnDine - first-time setup
echo  Project: %CD%
echo ============================================================
echo.

where uv >nul 2>nul
if errorlevel 1 goto :install_uv
goto :sync

:install_uv
echo [INFO] uv was not found. Trying to install it automatically...
where python >nul 2>nul
if errorlevel 1 goto :no_python
python -m pip install --user -U uv
if errorlevel 1 goto :uv_fail
set "PATH=%USERPROFILE%\.local\bin;%APPDATA%\Python\Scripts;%LOCALAPPDATA%\Programs\Python\Scripts;%PATH%"
where uv >nul 2>nul
if errorlevel 1 goto :uv_fail
echo [OK] uv installed.
echo.

:sync
echo [1/3] Installing dependencies into .venv (uv sync)...
echo       The first run downloads Python and packages, please wait.
uv sync
if errorlevel 1 goto :sync_fail
echo [OK] Dependencies ready.
echo.

echo [2/3] Creating .env and runtime folders...
if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo [OK] .env created from .env.example
) else (
    echo [SKIP] .env already exists.
)
uv run python -c "from dawndine.config import ensure_runtime_dirs; ensure_runtime_dirs(); print('[OK] data, data/knowledge, data/templates, data/chroma, uploads, watermarked, exports')"
if errorlevel 1 goto :verify_fail
echo.

echo [3/3] Checking the dawndine entry point...
uv run dawndine --help >nul 2>nul
if errorlevel 1 goto :verify_fail
echo [OK] Entry point works: uv run dawndine
echo.
echo ============================================================
echo  Setup finished.
echo  Next steps:
echo    1. Double-click scripts\windows\配置APIKey.bat and fill DASHSCOPE_API_KEY
echo    2. Double-click scripts\windows\启动DawnDine.bat
echo ============================================================
echo.
pause
exit /b 0

:no_python
echo.
echo [ERROR] Neither uv nor python was found in PATH.
echo Install Python 3.11+ from https://www.python.org/downloads/ first,
echo then run this file again.
echo.
pause
exit /b 1

:uv_fail
echo.
echo [ERROR] Automatic uv installation failed.
echo Install uv manually: https://docs.astral.sh/uv/getting-started/installation/
echo Then close this window and run this file again.
echo.
pause
exit /b 1

:sync_fail
echo.
echo [ERROR] uv sync failed. Check the network or proxy settings and retry.
echo.
pause
exit /b 1

:verify_fail
echo.
echo [ERROR] Package verification failed. Try: uv sync --reinstall
echo.
pause
exit /b 1
