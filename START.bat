@echo off
REM ============================================================
REM ANS State Classification - One-Click Startup Script
REM ============================================================
REM This script activates the virtual environment and starts
REM the Streamlit dashboard at localhost:8511
REM ============================================================

echo.
echo ========================================
echo  ANS State Monitor - Starting...
echo ========================================
echo.

REM Activate virtual environment
echo [1/2] Activating virtual environment...
call .venv\Scripts\activate.bat

REM Start Streamlit app
echo [2/2] Starting Streamlit dashboard...
echo.
echo ✓ App starting on http://localhost:8511
echo ✓ Press Ctrl+C to stop
echo.

python -m streamlit run app.py --server.port 8511 --logger.level=info

pause
