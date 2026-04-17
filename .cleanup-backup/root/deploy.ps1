# ============================================================================
# ViraClip - One-Click Deploy Script para Windows (PowerShell)
# ============================================================================
# Este script ejecuta todos los pasos necesarios para desplegar ViraClip
# con mejor manejo de errores y output colorido
# ============================================================================

$ErrorActionPreference = "Continue"

function Write-Step {
    param([string]$Message)
    Write-Host "`n[$Message]" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "✗ $Message" -ForegroundColor Red
}

function Write-Warning-Custom {
    param([string]$Message)
    Write-Host "⚠ $Message" -ForegroundColor Yellow
}

Write-Host "`n========================================"  -ForegroundColor Magenta
Write-Host "   ViraClip - One-Click Deploy" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

# Cambiar al directorio del proyecto
Set-Location $PSScriptRoot

# 1. Detener containers
Write-Step "1/6 Deteniendo containers existentes..."
docker-compose down 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Success "Containers detenidos"
} else {
    Write-Warning-Custom "No habia containers corriendo (normal en primer deploy)"
}

# 2. Build
Write-Step "2/6 Construyendo imagenes con cambios nuevos..."
Write-Host "Esto puede tomar 2-5 minutos..." -ForegroundColor Gray
docker-compose build --no-cache backend worker frontend
if ($LASTEXITCODE -ne 0) {
    Write-Error-Custom "Falló build"
    Read-Host "Presiona Enter para salir"
    exit 1
}
Write-Success "Build completado"

# 3. Iniciar servicios
Write-Step "3/6 Iniciando servicios..."
docker-compose up -d
if ($LASTEXITCODE -ne 0) {
    Write-Error-Custom "Falló docker-compose up"
    Read-Host "Presiona Enter para salir"
    exit 1
}
Write-Success "Servicios iniciados"

# 4. Esperar DB
Write-Step "4/6 Esperando a que base de datos esté lista..."
Start-Sleep -Seconds 10
Write-Success "Base de datos lista"

# 5. Migraciones
Write-Step "5/6 Ejecutando migraciones de base de datos..."
try {
    # Intentar copiar migration file al container
    docker cp backend/migrations/003_add_error_tracking.sql viraclip-postgres-1:/tmp/migration.sql 2>$null
    docker-compose exec -T postgres psql -U viraclip -d viraclip -f /tmp/migration.sql 2>$null
    
    if ($LASTEXITCODE -ne 0) {
        Write-Warning-Custom "Migración archivo falló, aplicando manualmente..."
        docker-compose exec -T postgres psql -U viraclip -d viraclip -c 'ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_code VARCHAR(10);' 2>$null | Out-Null
        docker-compose exec -T postgres psql -U viraclip -d viraclip -c 'ALTER TABLE tasks ADD COLUMN IF NOT EXISTS error_message TEXT;' 2>$null | Out-Null
        docker-compose exec -T postgres psql -U viraclip -d viraclip -c 'CREATE INDEX IF NOT EXISTS idx_tasks_error_code ON tasks(error_code) WHERE error_code IS NOT NULL;' 2>$null | Out-Null
    }
    Write-Success "Migraciones aplicadas"
} catch {
    Write-Warning-Custom "Migración puede haber fallado o ya estar aplicada"
}

# 6. Verificar servicios
Write-Step "6/6 Verificando servicios..."
Write-Host "`n--- Estado de containers ---" -ForegroundColor Yellow
docker-compose ps

Write-Host "`n--- Health checks ---" -ForegroundColor Yellow
$backendHealth = Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 5 -ErrorAction SilentlyContinue
if ($backendHealth) {
    Write-Success "Backend health: OK"
} else {
    Write-Warning-Custom "Backend aún no responde (puede tardar unos segundos más)"
}

Write-Host "`n--- Logs recientes del backend (últimas 15 líneas) ---" -ForegroundColor Yellow
docker-compose logs --tail=15 backend

Write-Host "`n--- Logs recientes del worker (últimas 15 líneas) ---" -ForegroundColor Yellow
docker-compose logs --tail=15 worker

# Resumen final
Write-Host "`n========================================"  -ForegroundColor Magenta
Write-Host "   Deploy Completado!" -ForegroundColor Magenta
Write-Host "========================================`n" -ForegroundColor Magenta

Write-Host "🌐 Frontend:      " -NoNewline -ForegroundColor Cyan
Write-Host "http://localhost:3000" -ForegroundColor White

Write-Host "🔧 Backend:       " -NoNewline -ForegroundColor Cyan
Write-Host "http://localhost:8000" -ForegroundColor White

Write-Host "📊 Admin Metrics: " -NoNewline -ForegroundColor Cyan
Write-Host "http://localhost:8000/admin/metrics" -ForegroundColor White

Write-Host "📚 API Docs:      " -NoNewline -ForegroundColor Cyan
Write-Host "http://localhost:8000/docs" -ForegroundColor White

Write-Host "`nPara ver logs en tiempo real:" -ForegroundColor Gray
Write-Host "  docker-compose logs -f" -ForegroundColor White

Write-Host "`nPara detener servicios:" -ForegroundColor Gray
Write-Host "  docker-compose down" -ForegroundColor White

Write-Host "`nPresiona cualquier tecla para salir..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
