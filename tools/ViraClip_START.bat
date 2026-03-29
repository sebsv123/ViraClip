@echo off
TITLE ViraClip START
CD /D "%~dp0"
powershell.exe -ExecutionPolicy Bypass -File "Launch_ViraClip.ps1"
if %errorlevel% neq 0 (
    echo.
    echo ❌ ERROR CRITICO: No se puede ejecutar Launch_ViraClip.ps1
    pause
)
