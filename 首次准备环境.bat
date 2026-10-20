@echo off
chcp 65001 >nul
call "%~dp0app\首次准备环境.bat" %*
exit /b %errorlevel%
