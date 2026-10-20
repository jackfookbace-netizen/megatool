@echo off
cd /d "%~dp0"
title Push to GitHub
echo ======================================================
echo    Pushing Megatool Web to GitHub...
echo ======================================================
git remote set-url origin https://github.com/jackfookbace-netizen/megatool.git
git branch -M main
git push -u origin main
echo.
echo ======================================================
echo    Done!
echo ======================================================
pause
