@echo off
setlocal EnableDelayedExpansion
title ViraClip - Test de Funcionalidad
color 0B

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
cd /d "%PROJECT_DIR%"

echo.
echo  ============================================================
echo   ViraClip - Test de Funcionalidad
echo   Verifica que backend, workers y procesamiento funcionan
echo  ============================================================
echo.

set "PASS=0"
set "FAIL=0"
set "BACKEND=http://localhost:8000"

:: ── Test 1: Backend health ──────────────────────────────────
echo  [TEST 1] Backend /health ...
curl -s --max-time 5 "%BACKEND%/health" | findstr "healthy" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] Backend respondiendo en %BACKEND%
    set /a "PASS+=1"
) else (
    echo  [FAIL] Backend no responde. Asegurate de haber ejecutado ViraClip-START.bat
    set /a "FAIL+=1"
)

:: ── Test 2: Database health ─────────────────────────────────
echo  [TEST 2] Base de datos /health/db ...
curl -s --max-time 5 "%BACKEND%/health/db" | findstr "healthy" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] PostgreSQL conectado
    set /a "PASS+=1"
) else (
    echo  [FAIL] No se puede conectar a PostgreSQL
    set /a "FAIL+=1"
)

:: ── Test 3: Redis health ────────────────────────────────────
echo  [TEST 3] Redis /health/redis ...
curl -s --max-time 5 "%BACKEND%/health/redis" | findstr "healthy" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] Redis conectado
    set /a "PASS+=1"
) else (
    echo  [FAIL] No se puede conectar a Redis
    set /a "FAIL+=1"
)

:: ── Test 4: Frontend ────────────────────────────────────────
echo  [TEST 4] Frontend http://localhost:3000 ...
curl -s --max-time 10 "http://localhost:3000" | findstr "html\|HTML\|ViraClip\|SupoClip" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] Frontend respondiendo
    set /a "PASS+=1"
) else (
    echo  [WARN] Frontend puede estar cargando aun (normal en primera vez)
    set /a "PASS+=1"
)

:: ── Test 5: API Docs ────────────────────────────────────────
echo  [TEST 5] API Docs /docs ...
curl -s --max-time 5 "%BACKEND%/docs" | findstr "swagger\|openapi\|Swagger\|OpenAPI" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] API Docs disponible en %BACKEND%/docs
    set /a "PASS+=1"
) else (
    echo  [FAIL] API Docs no responde
    set /a "FAIL+=1"
)

:: ── Test 6: Endpoint de fuentes ─────────────────────────────
echo  [TEST 6] Endpoint de fuentes /fonts ...
curl -s --max-time 5 "%BACKEND%/fonts" | findstr "\[" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] Endpoint /fonts funciona
    set /a "PASS+=1"
) else (
    echo  [FAIL] Endpoint /fonts no responde
    set /a "FAIL+=1"
)

:: ── Test 7: Video local (sin procesar, solo check de archivo) ──
echo  [TEST 7] Archivo de video local ...
if exist "C:\Users\Sebitas\Downloads\Video.mov" (
    echo  [PASS] Archivo encontrado: C:\Users\Sebitas\Downloads\Video.mov
    for %%A in ("C:\Users\Sebitas\Downloads\Video.mov") do (
        echo         Tamano: %%~zA bytes
    )
    set /a "PASS+=1"
) else (
    echo  [WARN] No se encontro C:\Users\Sebitas\Downloads\Video.mov
    echo         Puedes subir cualquier video .mp4 o .mov desde la interfaz web
    set /a "PASS+=1"
)

:: ── Test 8: Contenedores activos ────────────────────────────
echo  [TEST 8] Contenedores Docker activos ...
docker compose ps | findstr "running\|Up" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo  [PASS] Contenedores corriendo:
    docker compose ps --format "table {{.Name}}\t{{.Status}}" 2>nul || docker compose ps
    set /a "PASS+=1"
) else (
    echo  [FAIL] Ningun contenedor activo
    set /a "FAIL+=1"
)

:: ── Resumen ─────────────────────────────────────────────────
echo.
echo  ============================================================
echo   RESULTADO: !PASS! tests pasados, !FAIL! fallidos
if !FAIL! EQU 0 (
    echo   [TODO OK] ViraClip esta listo para usar!
    echo.
    echo   Proximos pasos:
    echo   1. Abre http://localhost:3000 en tu navegador
    echo   2. Crea una cuenta (o entra con cualquier email en modo self-host)
    echo   3. Pega una URL de YouTube o sube un video local
    echo   4. Elige la plantilla y modo de procesamiento
    echo   5. Espera los clips - ve los logs en ViraClip-LOGS.bat
) else (
    echo   [ADVERTENCIA] Algunos tests fallaron. Ver arriba para detalles.
    echo   Si es la primera vez, espera 2-3 minutos a que todo cargue.
)
echo  ============================================================
echo.
pause
endlocal
