@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
py -3 -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 (
    python -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
    if errorlevel 1 (
        echo Python 3.11 or later is required.
        pause
        exit /b 1
    )
    python launch.py %*
) else (
    py -3 launch.py %*
)
if errorlevel 1 (
    pause
    exit /b 1
)
