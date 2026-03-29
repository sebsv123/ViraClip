@echo off
TITLE ViraClip LOG MONITOR
CD /D "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "Monitor_ViraClip.ps1"
if %errorlevel% neq 0 (
    echo.
    echo ❌ ERROR CRITICO: No se puede ejecutar Monitor_ViraClip.ps1
    pause
)
