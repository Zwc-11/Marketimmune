#!/bin/bash
# MarketImmune Dashboard - Quick Setup Script for macOS/Linux
# This script automates the setup process for Unix-like systems

set -e  # Exit on error

echo ""
echo "============================================================"
echo "  MarketImmune Dashboard - Quick Setup"
echo "============================================================"
echo ""

# Check Python installation
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 is not installed"
    echo "Please install Python 3.8+ using:"
    echo "  macOS: brew install python3"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-venv"
    echo "  Other: https://www.python.org/"
    exit 1
fi

echo "[1/5] Creating virtual environment..."
python3 -m venv venv

echo "[2/5] Activating virtual environment..."
source venv/bin/activate

echo "[3/5] Installing dependencies..."
pip install --upgrade pip > /dev/null 2>&1 || true
pip install -r dashboard/requirements.txt

echo "[4/5] Initializing database..."
python manage.py migrate

echo "[5/5] Loading benchmark data..."
python manage.py load_metrics

echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "The dashboard is ready to run. Start it with:"
echo ""
echo "  source venv/bin/activate"
echo "  python manage.py runserver"
echo ""
echo "Then open your browser to: http://localhost:8000"
echo ""
