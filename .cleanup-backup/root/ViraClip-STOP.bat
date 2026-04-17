@echo off
title ViraClip - Deteniendo servicios...
color 0C

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

echo.
echo  [ViraClip] Deteniendo todos los servicios...
echo.

docker compose down

echo.
echo  [OK] ViraClip detenido correctamente.
echo  Los datos (videos, clips, BD) se conservan para el proximo inicio.
echo.
pause
