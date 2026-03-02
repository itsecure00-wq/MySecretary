@echo off
title Telegram AI Secretary
cd /d "%~dp0"

REM ─── Load credentials from .env file ───
for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
    if "%%a"=="TELEGRAM_BOT_TOKEN" set TELEGRAM_BOT_TOKEN=%%b
    if "%%a"=="TELEGRAM_CHAT_ID" set TELEGRAM_CHAT_ID=%%b
    if "%%a"=="GCFB_GROUP_CHAT_ID" set GCFB_GROUP_CHAT_ID=%%b
    if "%%a"=="LDS_USER" set LDS_USER=%%b
    if "%%a"=="LDS_PASS" set LDS_PASS=%%b
    if "%%a"=="BOOKING_USER" set BOOKING_USER=%%b
    if "%%a"=="BOOKING_PASS" set BOOKING_PASS=%%b
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
echo [%date% %time%] Starting bot... >> crash_log.txt

REM Run Python with stderr captured to temp file
"C:\Users\Admin23\AppData\Local\Python\pythoncore-3.14-64\python.exe" telegram_secretary.py 2> _stderr_temp.txt
set EXIT_CODE=%ERRORLEVEL%

REM Log crash info to crash_log.txt (structured format)
echo ===CRASH_START=== >> crash_log.txt
echo timestamp=%date% %time% >> crash_log.txt
echo exit_code=%EXIT_CODE% >> crash_log.txt
echo --- stderr --- >> crash_log.txt
type _stderr_temp.txt >> crash_log.txt
echo. >> crash_log.txt
echo ===CRASH_END=== >> crash_log.txt

echo.
echo [%time%] Secretary crashed (exit code: %EXIT_CODE%). Restarting in 5 seconds...
echo Press Ctrl+C to stop permanently.
ping -n 6 127.0.0.1 >nul
goto loop
