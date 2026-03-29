@echo off
title ViraClip - Instalando acceso directo en el escritorio
color 0A

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "DESKTOP=%USERPROFILE%\Desktop"
set "SHORTCUT_NAME=ViraClip"

echo.
echo  [ViraClip] Creando acceso directo en el escritorio...
echo  Carpeta del proyecto: %PROJECT_DIR%
echo  Escritorio: %DESKTOP%
echo.

:: Crear el acceso directo usando PowerShell
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell; " ^
  "$sc = $ws.CreateShortcut('%DESKTOP%\%SHORTCUT_NAME%.lnk'); " ^
  "$sc.TargetPath = '%PROJECT_DIR%\ViraClip-START.bat'; " ^
  "$sc.WorkingDirectory = '%PROJECT_DIR%'; " ^
  "$sc.Description = 'ViraClip - AI Video Clipping Tool'; " ^
  "$sc.WindowStyle = 1; " ^
  "$sc.Save()"

if %ERRORLEVEL% EQU 0 (
    echo  [OK] Acceso directo creado en el escritorio: ViraClip
    echo.
    echo  Ahora puedes:
    echo   - Doble clic en "ViraClip" del escritorio para arrancar todo
    echo   - O ejecutar ViraClip-START.bat directamente desde esta carpeta
    echo.
    echo  Scripts adicionales en esta carpeta:
    echo   - ViraClip-STOP.bat   : Para detener todos los servicios
    echo   - ViraClip-LOGS.bat   : Solo ver logs (si ya esta corriendo)
    echo   - ViraClip-LOGS.bat all     : Logs de todos los servicios
    echo   - ViraClip-LOGS.bat backend : Solo logs del backend
) else (
    echo  [ERROR] No se pudo crear el acceso directo.
    echo  Crea uno manualmente apuntando a: %PROJECT_DIR%\ViraClip-START.bat
)

echo.
pause
