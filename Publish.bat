@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 (
    python publish.py %*
) else (
    py -3 publish.py %*
)
if errorlevel 1 (
    pause
    exit /b 1
)
