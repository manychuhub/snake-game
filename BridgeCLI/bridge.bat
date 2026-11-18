@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
 echo Run start.bat first.
 exit /b 1
)
set PYTHONUTF8=1
.venv\Scripts\python.exe bridge_cli.py %*
