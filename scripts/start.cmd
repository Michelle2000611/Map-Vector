@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
set "PYTHONUTF8=1"
"%~dp0../.venv/Scripts/python.exe" -X utf8 -m mapvector
