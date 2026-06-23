@echo off
set OUT=%USERPROFILE%\Desktop\tailscale_check.txt
echo ===== Tailscale Diagnostic ===== > "%OUT%"
echo. >> "%OUT%"

if exist "C:\Program Files\Tailscale\tailscale-ipn.exe" (
    echo FOUND: C:\Program Files\Tailscale\tailscale-ipn.exe >> "%OUT%"
) else (
    echo NOT FOUND: C:\Program Files\Tailscale\tailscale-ipn.exe >> "%OUT%"
)

if exist "C:\Program Files (x86)\Tailscale\tailscale-ipn.exe" (
    echo FOUND: C:\Program Files (x86)\Tailscale\tailscale-ipn.exe >> "%OUT%"
) else (
    echo NOT FOUND: C:\Program Files (x86)\Tailscale\tailscale-ipn.exe >> "%OUT%"
)

if exist "%LOCALAPPDATA%\Programs\Tailscale\tailscale-ipn.exe" (
    echo FOUND: %LOCALAPPDATA%\Programs\Tailscale\tailscale-ipn.exe >> "%OUT%"
) else (
    echo NOT FOUND AppData: %LOCALAPPDATA%\Programs\Tailscale\tailscale-ipn.exe >> "%OUT%"
)

echo. >> "%OUT%"
echo -- where tailscale -- >> "%OUT%"
where tailscale >> "%OUT%" 2>&1
where tailscale-ipn >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo -- dir search -- >> "%OUT%"
dir /s /b "C:\tailscale-ipn.exe" >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo -- registry tailscale: URI -- >> "%OUT%"
reg query "HKCR\tailscale" /ve >> "%OUT%" 2>&1

echo. >> "%OUT%"
echo -- installed apps search -- >> "%OUT%"
dir /s /b "C:\Program Files\Tailscale\" >> "%OUT%" 2>&1
dir /s /b "C:\Program Files (x86)\Tailscale\" >> "%OUT%" 2>&1

echo Done. Opening result...
start notepad "%OUT%"
