# ViraClip Production Validation Script
# Validates system readiness for production deployment
# Usage: .\scripts\validate-production.ps1

$ErrorActionPreference = "Continue"
$script:FailureCount = 0
$script:WarningCount = 0
$script:SuccessCount = 0

function Write-Check {
    param($Message, $Status)
    switch ($Status) {
        "OK" { 
            Write-Host "✅ $Message" -ForegroundColor Green
            $script:SuccessCount++
        }
        "WARN" { 
            Write-Host "⚠️  $Message" -ForegroundColor Yellow
            $script:WarningCount++
        }
        "FAIL" { 
            Write-Host "❌ $Message" -ForegroundColor Red
            $script:FailureCount++
        }
        "INFO" { 
            Write-Host "ℹ️  $Message" -ForegroundColor Cyan
        }
    }
}

Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   VIRACLIP PRODUCTION VALIDATION" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""

# 1. CHECK: Docker instalado
Write-Host "[1] DOCKER ENVIRONMENT" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

try {
    $dockerVersion = docker --version 2>$null
    if ($dockerVersion) {
        Write-Check "Docker installed: $dockerVersion" "OK"
    } else {
        Write-Check "Docker not found - install Docker Desktop" "FAIL"
    }
} catch {
    Write-Check "Docker not found - install Docker Desktop" "FAIL"
}

try {
    $composeVersion = docker compose version 2>$null
    if ($composeVersion) {
        Write-Check "Docker Compose: $composeVersion" "OK"
    } else {
        Write-Check "Docker Compose not found" "FAIL"
    }
} catch {
    Write-Check "Docker Compose not found" "FAIL"
}

# 2. CHECK: Espacio en disco
Write-Host ""
Write-Host "[2] DISK SPACE" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

$drive = Get-PSDrive C
$freeGB = [math]::Round($drive.Free / 1GB, 2)
$usedGB = [math]::Round($drive.Used / 1GB, 2)
$totalGB = [math]::Round(($drive.Free + $drive.Used) / 1GB, 2)

Write-Check "Total space: $totalGB GB" "INFO"
Write-Check "Used space: $usedGB GB" "INFO"

if ($freeGB -gt 50) {
    Write-Check "Free space: $freeGB GB (Excellent)" "OK"
} elseif ($freeGB -gt 30) {
    Write-Check "Free space: $freeGB GB (Adequate)" "WARN"
} else {
    Write-Check "Free space: $freeGB GB (Insufficient - need 50GB+)" "FAIL"
}

# 3. CHECK: .env file exists
Write-Host ""
Write-Host "[3] ENVIRONMENT CONFIGURATION" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

if (Test-Path ".env") {
    Write-Check ".env file exists" "OK"
    
    # Check critical variables
    $envContent = Get-Content .env -Raw
    
    # Check for default passwords (CRITICAL)
    if ($envContent -match "viraclip_password") {
        Write-Check "POSTGRES_PASSWORD uses default - CHANGE IMMEDIATELY" "FAIL"
    } else {
        Write-Check "POSTGRES_PASSWORD changed from default" "OK"
    }
    
    if ($envContent -match "viraclip_dev_secret") {
        Write-Check "BETTER_AUTH_SECRET uses default - CHANGE IMMEDIATELY" "FAIL"
    } else {
        Write-Check "BETTER_AUTH_SECRET changed from default" "OK"
    }
    
    # Check Redis password
    if ($envContent -match "REDIS_PASSWORD=\s*$" -or $envContent -notmatch "REDIS_PASSWORD") {
        Write-Check "REDIS_PASSWORD not set - CONFIGURE IMMEDIATELY" "FAIL"
    } else {
        Write-Check "REDIS_PASSWORD configured" "OK"
    }
    
    # Check API keys
    if ($envContent -match "GROQ_API_KEY=\w+") {
        Write-Check "GROQ_API_KEY configured" "OK"
    } else {
        Write-Check "GROQ_API_KEY not set - LLM features limited" "WARN"
    }
    
    if ($envContent -match "ASSEMBLY_AI_API_KEY=\w+") {
        Write-Check "ASSEMBLY_AI_API_KEY configured" "OK"
    } else {
        Write-Check "ASSEMBLY_AI_API_KEY not set - using local Whisper" "WARN"
    }
    
    if ($envContent -match "PEXELS_API_KEY=\w+") {
        Write-Check "PEXELS_API_KEY configured" "OK"
    } else {
        Write-Check "PEXELS_API_KEY not set - B-roll limited" "WARN"
    }
    
} else {
    Write-Check ".env file missing - copy from .env.example" "FAIL"
}

# 4. CHECK: Docker Compose config valid
Write-Host ""
Write-Host "[4] DOCKER COMPOSE VALIDATION" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

try {
    $configTest = docker compose config 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Check "docker-compose.yml syntax valid" "OK"
    } else {
        Write-Check "docker-compose.yml has errors" "FAIL"
        Write-Host $configTest -ForegroundColor Red
    }
} catch {
    Write-Check "Failed to validate docker-compose.yml" "FAIL"
}

# 5. CHECK: Services status
Write-Host ""
Write-Host "[5] DOCKER SERVICES STATUS" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

try {
    $services = docker compose ps --format json 2>$null | ConvertFrom-Json
    
    if ($services) {
        $runningCount = 0
        $healthyCount = 0
        $unhealthyCount = 0
        
        foreach ($service in $services) {
            $name = $service.Service
            $state = $service.State
            $health = $service.Health
            
            if ($state -eq "running") {
                $runningCount++
                if ($health -eq "healthy") {
                    $healthyCount++
                    Write-Check "$name - running (healthy)" "OK"
                } elseif ($health -eq "unhealthy") {
                    $unhealthyCount++
                    Write-Check "$name - running (UNHEALTHY)" "FAIL"
                } else {
                    Write-Check "$name - running (no healthcheck)" "INFO"
                }
            } else {
                Write-Check "$name - $state" "WARN"
            }
        }
        
        Write-Host ""
        Write-Check "Total services: $($services.Count)" "INFO"
        Write-Check "Running: $runningCount" "INFO"
        Write-Check "Healthy: $healthyCount" "INFO"
        if ($unhealthyCount -gt 0) {
            Write-Check "Unhealthy: $unhealthyCount - INVESTIGATE" "FAIL"
        }
    } else {
        Write-Check "No services running - start with: docker compose up -d" "WARN"
    }
} catch {
    Write-Check "Could not check service status" "WARN"
}

# 6. CHECK: Critical endpoints
Write-Host ""
Write-Host "[6] ENDPOINT HEALTH CHECKS" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

# Backend health
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health/db" -TimeoutSec 5 -UseBasicParsing 2>$null
    if ($response.StatusCode -eq 200) {
        Write-Check "Backend /health/db - responding" "OK"
    } else {
        Write-Check "Backend /health/db - status $($response.StatusCode)" "WARN"
    }
} catch {
    Write-Check "Backend /health/db - not responding (service down?)" "FAIL"
}

# Frontend health
try {
    $response = Invoke-WebRequest -Uri "http://localhost:3000/" -TimeoutSec 5 -UseBasicParsing 2>$null
    if ($response.StatusCode -eq 200) {
        Write-Check "Frontend / - responding" "OK"
    } else {
        Write-Check "Frontend / - status $($response.StatusCode)" "WARN"
    }
} catch {
    Write-Check "Frontend / - not responding (service down?)" "FAIL"
}

# 7. CHECK: Volume mounts
Write-Host ""
Write-Host "[7] DOCKER VOLUMES" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

$requiredVolumes = @(
    "viraclip_postgres_data",
    "viraclip_redis_data",
    "viraclip_uploads",
    "viraclip_whisper_models"
)

try {
    $volumes = docker volume ls --format "{{.Name}}" 2>$null
    foreach ($vol in $requiredVolumes) {
        if ($volumes -contains $vol) {
            Write-Check "$vol - exists" "OK"
        } else {
            Write-Check "$vol - missing (will be created on first run)" "WARN"
        }
    }
} catch {
    Write-Check "Could not list volumes" "WARN"
}

# 8. CHECK: Network connectivity
Write-Host ""
Write-Host "[8] NETWORK AND PORTS" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

$requiredPorts = @(
    @{Port=3000; Service="Frontend"},
    @{Port=8000; Service="Backend"},
    @{Port=5432; Service="PostgreSQL (internal)"},
    @{Port=6379; Service="Redis (internal)"},
    @{Port=11434; Service="Ollama"}
)

foreach ($portInfo in $requiredPorts) {
    $port = $portInfo.Port
    $service = $portInfo.Service
    
    try {
        $connection = Test-NetConnection -ComputerName localhost -Port $port -WarningAction SilentlyContinue 2>$null
        if ($connection.TcpTestSucceeded) {
            Write-Check "Port $port ($service) - listening" "OK"
        } else {
            Write-Check "Port $port ($service) - not listening" "WARN"
        }
    } catch {
        Write-Check "Port $port ($service) - cannot test" "INFO"
    }
}

# 9. CHECK: Recent logs for errors
Write-Host ""
Write-Host "[9] RECENT LOGS (Last 50 lines)" -ForegroundColor Magenta
Write-Host "-----------------------------------------------------" -ForegroundColor Gray

try {
    $backendErrors = docker compose logs backend --tail=50 2>$null | Select-String -Pattern "ERROR|CRITICAL|FATAL"
    if ($backendErrors.Count -gt 0) {
        Write-Check "Backend has $($backendErrors.Count) recent error(s)" "WARN"
    } else {
        Write-Check "Backend - no recent errors" "OK"
    }
    
    $workerErrors = docker compose logs worker --tail=50 2>$null | Select-String -Pattern "ERROR|CRITICAL|FATAL"
    if ($workerErrors.Count -gt 0) {
        Write-Check "Worker has $($workerErrors.Count) recent error(s)" "WARN"
    } else {
        Write-Check "Worker - no recent errors" "OK"
    }
} catch {
    Write-Check "Could not check logs - services may not be running" "INFO"
}

# 10. SUMMARY
Write-Host ""
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host "   VALIDATION SUMMARY" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════════════════════" -ForegroundColor Cyan
Write-Host ""
Write-Host "[OK] Passed:  $script:SuccessCount" -ForegroundColor Green
Write-Host "[WARN] Warnings: $script:WarningCount" -ForegroundColor Yellow
Write-Host "[FAIL] Failed:  $script:FailureCount" -ForegroundColor Red
Write-Host ""

if ($script:FailureCount -eq 0 -and $script:WarningCount -eq 0) {
    Write-Host "SUCCESS: PRODUCTION READY - All checks passed!" -ForegroundColor Green
    exit 0
} elseif ($script:FailureCount -eq 0) {
    Write-Host "WARNING: PRODUCTION READY with warnings - Review warnings above" -ForegroundColor Yellow
    exit 0
} else {
    Write-Host "FAILED: NOT PRODUCTION READY - Fix critical failures above" -ForegroundColor Red
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "1. Review EVALUATION_PRODUCCION_2026-04-12.md" -ForegroundColor White
    Write-Host "2. Update .env with secure passwords" -ForegroundColor White
    Write-Host "3. Re-run this validation script" -ForegroundColor White
    exit 1
}
