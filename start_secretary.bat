@echo off
title Telegram AI Secretary
cd /d "%~dp0"

REM ─── Set your credentials here ───
REM Or set them as system environment variables
if "%TELEGRAM_BOT_TOKEN%"=="" set TELEGRAM_BOT_TOKEN=8653492472:AAG_54x92Lmb1dWHVX9AO6Pqp3lNCwYoOyM
if "%TELEGRAM_CHAT_ID%"=="" set TELEGRAM_CHAT_ID=7560692069

echo ==========================================
echo   Telegram AI Secretary
echo ==========================================
echo Bot Token: ...%TELEGRAM_BOT_TOKEN:~-6%
echo Chat ID: %TELEGRAM_CHAT_ID%
echo ==========================================
echo.

python telegram_secretary.py

echo.
echo Secretary stopped. Press any key to exit.
pause >nul