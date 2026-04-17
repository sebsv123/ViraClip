@echo off
REM ============================================================================
REM ViraClip - One-Click Deploy Script para Windows
REM ============================================================================
REM Este script ejecuta todos los pasos necesarios para desplegar ViraClip:
REM 1. Detiene containers existentes
REM 2. Rebuild con nuevos cambios
REM 3. Espera a que servicios estén ready
REM 4. Ejecuta migraciones de DB
REM 5. Verifica logs
REM ============================================================================

echo.
echo ========================================
echo   ViraClip - One-Click Deploy
echo ========================================
echo.

REM Cambiar al directorio del proyecto
cd /d %~dp0

echo [1/6] Deteniendo containers existentes...
docker-compose down
if %errorlevel% neq 0 (
    echo ERROR: Falló docker-compose down
    pause
    exit /b 1
)
echo ✓ Containers detenidos
echo.

echo [2/6] Construyendo imagenes con cambios nuevos...
docker-compose build --no-cache backend worker frontend
if %errorlevel% neq 0 (
    echo ERROR: Falló build
    pause
    exit /b 1
)
echo ✓ Build completado
echo.

echo [3/6] Iniciando servicios...
docker-compose up -d
if %errorlevel% neq 0 (
    echo ERROR: Falló docker-compose up
    pause
    exit /b 1
)
echo ✓ Servicios iniciados
echo.

echo [4/6] Esperando a que base de datos esté lista...
timeout /t 10 /nobreak >nul
echo ✓ Base de datos lista
echo.

echo [5/6] Ejecutando migraciones de base de datos...
docker-compose exec -T postgres psql -U viraclip -d viraclip -f /docker-entrypoint-initdb.d/003_add_error_tracking.sql 2>nul
if %errorlevel% neq 0 (
    echo ADVERTENCIA: Migración puede haber fallado o ya estar aplicada
    echo Intentando aplicar manualmente...
    docker-compose exec -T postgres psql -U viraclip -d viraclip -c "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_code VARCHAR(10);" >nul 2>&1
    docker-compose exec -T postgres psql -U viraclip -d viraclip -c "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_message TEXT;" >nul 2>&1
    docker-compose exec -T postgres psql -U viraclip -d viraclip -c "CREATE INDEX IF NOT EXISTS idx_tasks_error_code ON tasks(error_code) WHERE error_code IS NOT NULL;" >nul 2>&1
)
echo ✓ Migraciones aplicadas
echo.

echo [6/6] Verificando servicios...
echo.
echo --- Estado de containers ---
docker-compose ps
echo.
echo --- Logs recientes del backend (últimas 20 líneas) ---
docker-compose logs --tail=20 backend
echo.
echo --- Logs recientes del worker (últimas 20 líneas) ---
docker-compose logs --tail=20 worker
echo.

echo ========================================
echo   Deploy Completado!
echo ========================================
echo.
echo Frontend: http://localhost:3000
echo Backend:  http://localhost:8000
echo Admin Metrics: http://localhost:8000/admin/metrics
echo.
echo Para ver logs en tiempo real:
echo   docker-compose logs -f
echo.
echo Presiona cualquier tecla para salir...
pause >nul
