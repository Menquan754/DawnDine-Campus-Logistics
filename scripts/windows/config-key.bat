@echo off
setlocal EnableExtensions
title DawnDine - Configure API Key
cd /d "%~dp0..\.."

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
) else (
    echo .env already exists. Opening it now.
)

if not exist ".env" (
    echo [ERROR] Cannot create .env. Check write permission for this folder.
    pause
    exit /b 1
)

start "" notepad ".env"
echo.
echo Replace the placeholder DASHSCOPE_API_KEY value with your real key, save the file,
echo close Notepad, then double-click the DawnDine launcher to start the web app.
echo Key page: https://bailian.console.aliyun.com/
echo.
pause
