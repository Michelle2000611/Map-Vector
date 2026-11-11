@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-frontend.ps1"
exit /b %errorlevel%
