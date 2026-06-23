@echo off
title Building Droprun.exe
echo.
echo  ===========================================
echo    Building Droprun.exe -- please wait...
echo  ===========================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found.
    echo  Download from https://python.org/downloads
    echo  Make sure to check "Add Python to PATH" during install.
    echo.
    pause
    exit /b 1
)

echo  [1/3] Installing dependencies...
pip install pywebview pyinstaller --quiet
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Failed to install dependencies.
    echo  Try running this as Administrator.
    pause
    exit /b 1
)

echo  [2/3] Building executable (this takes 2-4 minutes)...
cd /d "%~dp0"

python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name Droprun ^
  --icon "Assets\Droprun.ico" ^
  --add-data "droprun_ui.html;." ^
  --add-data "Assets;Assets" ^
  --add-data "Droprun_Help_Guide.docx;." ^
  --collect-all webview ^
  --noconfirm ^
  fileshare_desktop.py

echo.
if exist "dist\Droprun.exe" (
    echo  [3/3] Done!
    echo.
    echo  ============================================
    echo   Droprun.exe is ready in the dist\ folder
    echo   Share it with your friends!
    echo  ============================================
    echo.
    start "" "%~dp0dist"
) else (
    echo  [3/3] Build may have failed -- check output above for errors.
)

pause
