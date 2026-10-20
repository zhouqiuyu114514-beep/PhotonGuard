@echo off
chcp 65001 >nul
call "%~dp0app\停止工作台.bat" %*
exit /b %errorlevel%
