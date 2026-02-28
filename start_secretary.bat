@echo off
title Telegram AI Secretary
cd /d "%~dp0"

REM ─── Load credentials from .env file ───
for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if "%%a"=="TELEGRAM_BOT_TOKEN" set TELEGRAM_BOT_TOKEN=%%b
    if "%%a"=="TELEGRAM_CHAT_ID" set TELEGRAM_CHAT_ID=%%b
)

REM ─── Prevent "nested session" error if launched from Claude Code ───
set CLAUDECODE=

echo ==========================================
echo   Telegram AI Secretary
echo ==========================================
echo Bot Token: ...%TELEGRAM_BOT_TOKEN:~-6%
echo Chat ID: %TELEGRAM_CHAT_ID%
echo ==========================================
echo.

:loop
python telegram_secretary.py
echo.
echo [%time%] Secretary crashed or stopped. Restarting in 5 seconds...
echo Press Ctrl+C to stop permanently.
timeout /t 5 /nobreak >nul
goto loop
