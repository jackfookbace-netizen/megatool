@echo off
cd /d "%~dp0"
title MEGATOOL Server - Port 8000
echo ======================================================
echo    MEGATOOL - Shopee Auto Export Server
echo    Running on: http://127.0.0.1:8000
echo ======================================================
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
