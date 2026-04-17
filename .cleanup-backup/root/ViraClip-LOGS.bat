@echo off
title ViraClip - Logs en Vivo
color 0B

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

echo.
echo  [ViraClip] Logs en vivo de los workers de procesamiento
echo  Ctrl+C para salir
echo  ────────────────────────────────────────────────────────
echo.

:: Si se pasa "all" como argumento, muestra todos los servicios
if "%1"=="all" (
    docker compose logs -f
) else if "%1"=="backend" (
    docker compose logs -f backend
) else if "%1"=="frontend" (
    docker compose logs -f frontend
) else (
    :: Por defecto: solo workers (donde ocurre el procesamiento de video)
    docker compose logs -f worker worker-2 worker-3
)
