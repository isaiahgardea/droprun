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
set "PY=python"

echo  [1/3] Installing dependencies...
%PY% -m pip install pywebview pyinstaller --quiet
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Failed to install dependencies.
    echo  Try running this as Administrator.
    pause
    exit /b 1
)

echo  [2/3] Building executable (this takes 2-4 minutes)...
cd /d "%~dp0"

:: Kill any running instance so the exe file isn't locked by Windows
taskkill /F /IM Droprun.exe >nul 2>&1

:: Give Windows a moment to release the file lock before we delete it
timeout /t 1 /nobreak >nul 2>&1

:: Delete the old exe FIRST so a failed build can never masquerade as success
if exist "dist\Droprun.exe" del /F /Q "dist\Droprun.exe"

%PY% -m PyInstaller ^
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
set "BUILD_RC=%errorlevel%"

echo.
if not "%BUILD_RC%"=="0" (
    echo  [3/3] BUILD FAILED -- PyInstaller exited with code %BUILD_RC%.
    echo  Scroll up for the actual error. The old exe was deleted, so
    echo  nothing stale remains to accidentally run.
    echo.
    pause
    exit /b 1
)
if exist "dist\Droprun.exe" (
    echo  [3/3] Done! A FRESH Droprun.exe was built successfully.
    echo.
    echo  ============================================
    echo   Droprun.exe is ready in the dist\ folder
    echo   Share it with your friends!
    echo  ============================================
    echo.
    start "" "%~dp0dist"
) else (
    echo  [3/3] BUILD FAILED -- PyInstaller returned 0 but produced no exe.
    echo  Scroll up for details.
    echo.
    pause
    exit /b 1
)

pause
