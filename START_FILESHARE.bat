@echo off
title FileShare
echo.
echo  Starting FileShare...
echo  Press Ctrl+C in this window to stop.
echo.

:: Check if Python is available
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found!
    echo  Download it from https://python.org/downloads
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

:: Run the app from the same folder as this batch file
cd /d "%~dp0"
python fileshare.py %*

pause
