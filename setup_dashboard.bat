@echo off
REM MarketImmune Dashboard - Quick Setup Script for Windows
REM This script automates the setup process for Windows users

setlocal enabledelayedexpansion

echo.
echo ============================================================
echo  MarketImmune Dashboard - Quick Setup
echo ============================================================
echo.

REM Check Python installation
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://www.python.org/
    pause
    exit /b 1
)

echo [1/5] Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)

echo [2/5] Activating virtual environment...
call venv\Scripts\activate.bat

echo [3/5] Installing dependencies...
pip install --upgrade pip >nul 2>&1
pip install -r dashboard\requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)

echo [4/5] Initializing database...
python manage.py migrate
if errorlevel 1 (
    echo ERROR: Database migration failed
    pause
    exit /b 1
)

echo [5/7] Loading benchmark data...
python manage.py load_metrics
if errorlevel 1 (
    echo ERROR: Failed to load metrics
    pause
    exit /b 1
)

echo [6/7] Training ML risk head + writing benchmark report...
python scripts\train_risk_head.py

echo [7/7] Pre-warming simulator session with ML head...
python manage.py prepare_simulator --force

echo.
echo ============================================================
echo  Setup Complete!
echo ============================================================
echo.
echo The dashboard is ready to run. Start it with:
echo.
echo   python manage.py runserver
echo.
echo Then open your browser to: http://localhost:8000
echo.
echo Press any key to continue...
pause >nul
