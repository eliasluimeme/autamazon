@echo off
setlocal EnableDelayedExpansion
title Amazon Project Setup
chcp 65001 >nul 2>nul

REM -------------------------------------------------------
REM Auto-elevate to Administrator (required for C++ Build
REM Tools installation via winget / vs_buildtools.exe)
REM -------------------------------------------------------
net session >nul 2>&1
if !errorlevel! neq 0 (
    echo [INFO] Requesting administrator privileges...
    powershell -NoProfile -Command ^
        "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
    exit /b
)

echo ==================================================
echo  STARTING WINDOWS PROJECT SETUP  (as Administrator)
echo ==================================================

REM -------------------------------------------------------
REM 1. Make sure we run from the directory of this script
REM -------------------------------------------------------
cd /d "%~dp0"

REM -------------------------------------------------------
REM 2. Detect Python (prefer py launcher, then python)
REM -------------------------------------------------------
set "PYTHON_CMD="

where py >nul 2>nul
if !errorlevel! equ 0 (
    REM Confirm it can actually launch Python 3
    py -3 --version >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=py -3"
        goto :python_found
    )
)

where python >nul 2>nul
if !errorlevel! equ 0 (
    python --version >nul 2>nul
    if !errorlevel! equ 0 (
        set "PYTHON_CMD=python"
        goto :python_found
    )
)

where python3 >nul 2>nul
if !errorlevel! equ 0 (
    set "PYTHON_CMD=python3"
    goto :python_found
)

echo.
echo ERROR: Python 3 not found.
echo Please install Python 3.8+ from https://www.python.org/downloads/
echo Make sure to tick "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:python_found
echo [OK] Found Python: %PYTHON_CMD%
%PYTHON_CMD% --version

REM -------------------------------------------------------
REM 3. Run the cross-platform setup logic
REM -------------------------------------------------------
echo.
echo [INFO] Running setup.py ...
%PYTHON_CMD% setup.py --no-shell
if !errorlevel! neq 0 (
    echo.
    echo ERROR: setup.py failed. See output above for details.
    echo.
    pause
    exit /b !errorlevel!
)

REM -------------------------------------------------------
REM 4. Verify the virtual environment was created
REM -------------------------------------------------------
if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo ERROR: Virtual environment was not created at .venv\Scripts\
    echo.
    pause
    exit /b 1
)

REM -------------------------------------------------------
REM 5. Quick smoke-test: verify loguru is importable
REM -------------------------------------------------------
echo.
echo [INFO] Smoke-testing key packages ...
".venv\Scripts\python.exe" -c "import loguru; import playwright; import agentql; print('[OK] loguru, playwright, agentql all importable')"
if !errorlevel! neq 0 (
    echo.
    echo WARNING: One or more packages failed the smoke test.
    echo Try running:  .venv\Scripts\pip install loguru playwright agentql
    echo.
)

REM -------------------------------------------------------
REM 6. Remind user about .env
REM -------------------------------------------------------
if not exist ".env" (
    echo.
    echo REMINDER: .env file not found. Please create it with your API keys.
)

echo.
echo ==================================================
echo  SETUP COMPLETE
echo ==================================================
echo.
echo To activate the virtual environment in this window, run:
echo     .venv\Scripts\activate
echo.
echo Or, to start working immediately, run:
echo     .venv\Scripts\python.exe run.py
echo.

REM Activate for the rest of this CMD session (only works if run via cmd.exe)
call ".venv\Scripts\activate.bat"

echo Virtual environment is now active.
echo Python: 
python --version
echo.
echo Press any key to close this window, or keep it open to start working.
pause >nul
