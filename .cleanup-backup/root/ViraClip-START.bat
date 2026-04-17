@echo off
setlocal EnableDelayedExpansion
title ViraClip - Iniciando...
color 0A

:: ============================================================
::  ViraClip - Lanzador Principal
::  Un clic para arrancar todo y ver los logs en vivo
:: ============================================================

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

echo.
echo  ██╗   ██╗██╗██████╗  █████╗  ██████╗██╗     ██╗██████╗
echo  ██║   ██║██║██╔══██╗██╔══██╗██╔════╝██║     ██║██╔══██╗
echo  ██║   ██║██║██████╔╝███████║██║     ██║     ██║██████╔╝
echo  ╚██╗ ██╔╝██║██╔══██╗██╔══██║██║     ██║     ██║██╔═══╝
echo   ╚████╔╝ ██║██║  ██║██║  ██║╚██████╗███████╗██║██║
echo    ╚═══╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝ ╚═════╝╚══════╝╚═╝╚═╝
echo.
echo  AI Video Clipping Tool - Local Edition
echo  ==========================================
echo.

:: ── 1. Verificar .env ──────────────────────────────────────
if not exist "%PROJECT_DIR%\.env" (
    echo  [ERROR] No se encontro el archivo .env
    echo  Crea el .env con tus API keys antes de continuar.
    echo  Mira .env.example como referencia.
    pause
    exit /b 1
)

:: ── 1b. Crear carpeta de exports si no existe ──────────────
if not exist "C:\Users\Sebitas\ViraClip-Exports" (
    mkdir "C:\Users\Sebitas\ViraClip-Exports"
    echo  [OK] Carpeta de exports creada: C:\Users\Sebitas\ViraClip-Exports
)

:: ── 2. Verificar Docker Desktop ────────────────────────────
echo  [1/5] Verificando Docker Desktop...
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo  Docker no esta corriendo. Iniciando Docker Desktop...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo  Esperando que Docker arranque (hasta 60 segundos)...
    set /a "intentos=0"
    :esperar_docker
    timeout /t 5 /nobreak >nul
    docker info >nul 2>&1
    if %ERRORLEVEL% EQU 0 goto docker_ok
    set /a "intentos+=1"
    if !intentos! LSS 12 (
        echo  Esperando... (!intentos!/12)
        goto esperar_docker
    )
    echo  [ERROR] Docker tarda demasiado en iniciar.
    echo  Abre Docker Desktop manualmente y vuelve a ejecutar este script.
    pause
    exit /b 1
)
:docker_ok
echo  [OK] Docker Desktop listo.

:: ── 3. Construir y levantar servicios ─────────────────────
echo.
echo  [2/5] Levantando servicios con Docker Compose...
echo  (Primera vez puede tardar varios minutos en descargar imagenes)
echo.

docker compose up -d --build
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo  [ERROR] Fallo al levantar los servicios.
    echo  Revisa los errores arriba. Causas comunes:
    echo   - Puertos 3000 u 8000 ocupados por otro proceso
    echo   - GPU NVIDIA no disponible (edita docker-compose.yml)
    echo   - Error de compilacion en el codigo
    echo.
    echo  Ver logs completos con: docker compose logs
    pause
    exit /b 1
)

:: ── 4. Esperar que los servicios esten healthy ─────────────
echo.
echo  [3/5] Esperando que los servicios esten listos...
set /a "espera=0"
:check_health
timeout /t 5 /nobreak >nul
docker compose ps | findstr "healthy" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    :: Al menos un servicio healthy, verificar backend especificamente
    curl -s --max-time 3 http://localhost:8000/health >nul 2>&1
    if %ERRORLEVEL% EQU 0 goto servicios_ok
)
set /a "espera+=1"
if !espera! LSS 20 (
    echo  Esperando servicios... ^(!espera!/20^)
    goto check_health
)
echo  Servicios tardando mas de lo normal, continuando de todos modos...

:servicios_ok
echo  [OK] Servicios levantados.

:: ── 5. Abrir navegador ─────────────────────────────────────
echo.
echo  [4/5] Abriendo ViraClip en el navegador...
timeout /t 3 /nobreak >nul
start "" "http://localhost:3000"

:: ── 6. Mostrar estado y abrir logs ─────────────────────────
echo.
echo  [5/5] Estado de los contenedores:
echo  ────────────────────────────────────────────────────────
docker compose ps
echo  ────────────────────────────────────────────────────────
echo.
echo  ============================================================
echo   ViraClip esta corriendo!
echo   Frontend:  http://localhost:3000
echo   Backend:   http://localhost:8000
echo   API Docs:  http://localhost:8000/docs
echo  ============================================================
echo.
echo  Mostrando LOGS EN VIVO de los workers (Ctrl+C para salir)
echo  Los clips exportados se guardan en:
echo  C:\Users\Sebitas\ViraClip-Exports\
echo.
echo  ────────────────────────────────────────────────────────

:: Logs en vivo de los 3 workers (el procesamiento real de video)
docker compose logs -f worker worker-2 worker-3

endlocal
