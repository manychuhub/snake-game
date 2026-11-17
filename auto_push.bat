@echo off
cd /d "c:\Users\통신운용\Desktop\Agent"

echo ========================================================
echo   [DC-OPS AI] Auto Push to GitHub ^& Render Cloud
echo ========================================================
echo.

echo [1/3] Staging all changed files...
"C:\Program Files\Git\cmd\git.exe" add .

echo.
echo [2/3] Committing files...
"C:\Program Files\Git\cmd\git.exe" commit -m "update: automated sync to cloud"

echo.
echo [3/3] Uploading (Pushing) to GitHub...
echo (If a GitHub sign-in window appears, please authorize in browser)
"C:\Program Files\Git\cmd\git.exe" push -u origin main

echo.
if %ERRORLEVEL% EQU 0 (
    echo ========================================================
    echo   SUCCESS! Uploaded to GitHub.
    echo   Render.com Cloud will auto-deploy within 1-2 minutes.
    echo ========================================================
) else (
    echo [ERROR] Push failed. Please check GitHub login status.
)

echo.
pause
