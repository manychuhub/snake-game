@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .env (
  echo Missing .env. Copy .env.example to .env and configure keys.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  where py >nul 2>&1
  if errorlevel 1 (python -m venv .venv) else (py -3 -m venv .venv)
  if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto fail
.venv\Scripts\python.exe -c "import config; assert config.KEY and config.TOKEN, 'Missing API key or auth token'"
if errorlevel 1 goto fail
.venv\Scripts\python.exe -c "import config,uvicorn; print('API docs: '+config.BASE_URL+'/docs'); uvicorn.run('api_server:app',host=config.HOST,port=config.PORT)"
if errorlevel 1 goto fail
exit /b 0
:fail
echo Startup failed. Copy the error message, not your keys.
pause
exit /b 1
