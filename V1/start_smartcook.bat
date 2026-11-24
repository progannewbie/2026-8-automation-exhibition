@echo off
rem SmartCook exhibition UI launcher: start src\web_ui.py, open the browser once it is up.
rem Arguments are passed through to web_ui.py, e.g. start_smartcook.bat --simulate
rem Keep this file ASCII-only: cmd reads .bat files in the system code page (cp950).
setlocal
title SmartCook UI

set "ROOT=%~dp0"
set "PORT=5000"
set "URL=http://localhost:%PORT%"

rem Prefer the project .venv (packages live there), fall back to system python
set "PY=%ROOT%.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

rem Already running: just open the browser instead of starting a second server
curl -s -o nul --max-time 2 "%URL%/" && (
    echo SmartCook UI is already running: %URL%
    start "" "%URL%"
    timeout /t 3 >nul
    exit /b 0
)

rem Wait in the background for the server (connecting to the arms can take a while,
rem up to ~90 s), then open the browser
start "" /b powershell -NoProfile -WindowStyle Hidden -Command ^
    "for ($i = 0; $i -lt 90; $i++) { try { Invoke-WebRequest -UseBasicParsing '%URL%/' -TimeoutSec 1 | Out-Null; break } catch { if ($_.Exception.Response) { break } }; Start-Sleep -Seconds 1 }; Start-Process '%URL%'"

cd /d "%ROOT%src"
"%PY%" web_ui.py --port %PORT% %*

echo.
echo SmartCook UI has stopped.
pause
