@echo off
setlocal
chcp 65001 >nul
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\start.ps1" -Stop %*
set "pg_exit=%errorlevel%"
if not "%pg_exit%"=="0" pause
exit /b %pg_exit%
