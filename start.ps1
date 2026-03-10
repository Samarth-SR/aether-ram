# Cloud RAM — Quick Launch Script
# Run this from c:\Users\user\ram
# Usage: .\start.ps1

Write-Host "==================================" -ForegroundColor Cyan
Write-Host "  Cloud RAM - Starting Servers    " -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

# Terminal 1: Cloud Backend on port 8000
Write-Host "`n[1/2] Starting Cloud Backend (port 8000)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
  "cd '$PSScriptRoot\server'; Write-Host 'Cloud Backend starting...' -ForegroundColor Cyan; python -m uvicorn main:app --port 8000 --reload" `
  -WindowStyle Normal

Start-Sleep -Seconds 2

# Terminal 2: Monitor Agent + Dashboard on port 8001
Write-Host "[2/2] Starting Monitor Agent (port 8001)..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
  "cd '$PSScriptRoot'; Write-Host 'Monitor Agent starting...' -ForegroundColor Green; python client/monitor.py" `
  -WindowStyle Normal

Start-Sleep -Seconds 3

Write-Host "`n[OK] Both servers starting up!" -ForegroundColor Green
Write-Host ""
Write-Host "  Dashboard:  http://localhost:8001" -ForegroundColor Cyan
Write-Host "  Cloud API:  http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""
Write-Host "Opening dashboard in browser..." -ForegroundColor Yellow

# Open dashboard in default browser
Start-Process "http://localhost:8001"

Write-Host "`nPress any key to exit this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
