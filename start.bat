@echo off
echo ==================================
echo   Cloud RAM - Starting Servers
echo ==================================
echo.
echo [1/2] Starting Cloud Backend on port 8000...
start "Cloud Backend (port 8000)" cmd /k "cd /d %~dp0server && python -m uvicorn main:app --port 8000 --reload"

timeout /t 2 /nobreak >nul

echo [2/2] Starting Monitor Agent on port 8001...
start "Monitor Agent (port 8001)" cmd /k "cd /d %~dp0 && python client/monitor.py"

timeout /t 4 /nobreak >nul

echo.
echo ✓ Servers starting up!
echo.
echo   Dashboard:  http://localhost:8001
echo   Cloud API:  http://localhost:8000/docs
echo.
echo Opening dashboard...
start http://localhost:8001

echo.
pause
