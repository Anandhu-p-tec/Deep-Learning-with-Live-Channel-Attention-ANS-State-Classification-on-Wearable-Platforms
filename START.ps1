# ============================================================
# ANS State Classification - PowerShell Startup Script
# ============================================================
# Usage: 
#   1. Right-click this file → "Run with PowerShell"
#   2. If execution policy error occurs, run this first:
#      Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# ============================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  ANS State Monitor - Starting..." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Activate virtual environment
Write-Host "[1/2] Activating virtual environment..." -ForegroundColor Yellow
& ".\.venv\Scripts\Activate.ps1"

# Start Streamlit app
Write-Host "[2/2] Starting Streamlit dashboard..." -ForegroundColor Yellow
Write-Host ""
Write-Host "✓ App starting on http://localhost:8511" -ForegroundColor Green
Write-Host "✓ Press Ctrl+C to stop" -ForegroundColor Green
Write-Host ""

python -m streamlit run app.py --server.port 8511 --logger.level=info

Write-Host "Press any key to close..." -ForegroundColor Red
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
