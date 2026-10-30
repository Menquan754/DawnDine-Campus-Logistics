@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0..\.."

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example
) else (
    echo .env already exists. Opening it now.
)

start "" notepad ".env"
echo.
echo Replace the placeholder with your DashScope API key, save the file,
echo then double-click "启动DawnDine.bat" to start the web app.
echo Key page: https://bailian.console.aliyun.com/
echo.
pause
