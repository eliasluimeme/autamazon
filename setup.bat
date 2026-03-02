@echo off
setlocal
title Amazon Project Setup

echo ==================================================
echo 🚀 STARTING WINDOWS PROJECT SETUP
echo ==================================================

REM 1. Detect Python
set PYTHON_CMD=python
where %PYTHON_CMD% >nul 2>nul
if %errorlevel% neq 0 (
    set PYTHON_CMD=py
    where %PYTHON_CMD% >nul 2>nul
    if %errorlevel% neq 0 (
        echo ❌ ERROR: Python not found. Please install Python 3.8+
        pause
        exit /b 1
    )
)

REM 2. Run the logic
%PYTHON_CMD% setup.py --no-shell
if %errorlevel% neq 0 (
    echo ❌ ERROR: Setup logic failed.
    pause
    exit /b %errorlevel%
)

REM 3. Activate the virtual environment
if exist .venv\Scripts\activate.bat (
    echo --- Activating virtual environment ---
    
    REM We need to use a trick to keep the venv active in the current CMD after the bat ends
    REM but usually 'call' inside a bat works if the user ran the bat from CDM.
    REM If they double clicked, it ends.
    
    echo ✅ SUCCESS: .venv is now active.
    echo Using:
    .venv\Scripts\python.exe --version
    
    if not exist .env (
        echo ⚠️  REMINDER: Please update your .env file with API keys!
    )
    
    echo ==================================================
    echo ✅ SETUP COMPLETE
    echo ==================================================
    
    REM This will leave the user in the activated state if run from CMD
    call .venv\Scripts\activate
) else (
    echo ❌ ERROR: Virtual environment not found.
    pause
)

REM If we started from double-click, the pause keeps it open.
REM If from CMD, it just continues.
echo.
echo Press any key to start working, or close this window.
pause >nul
