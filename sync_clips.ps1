# Script de sincronización de clips desde Docker a Windows
# Ejecutar: .\sync_clips.ps1

$ErrorActionPreference = "SilentlyContinue"

Write-Host "Sincronizando clips desde Docker..." -ForegroundColor Green

# Crear carpeta si no existe
New-Item -ItemType Directory -Path "C:\Users\Sebitas\ViraClip\exports\clips" -Force | Out-Null

# Copiar clips desde ubicación unificada en todos los contenedores
docker cp viraclip-backend:/app/exports/clips/. "C:\Users\Sebitas\ViraClip\exports\clips\" 2>$null
docker cp viraclip-worker:/app/exports/clips/. "C:\Users\Sebitas\ViraClip\exports\clips\" 2>$null
docker cp viraclip-worker-2:/app/exports/clips/. "C:\Users\Sebitas\ViraClip\exports\clips\" 2>$null
docker cp viraclip-worker-3:/app/exports/clips/. "C:\Users\Sebitas\ViraClip\exports\clips\" 2>$null

# Limpiar archivos basura (solo dejar .mp4)
Get-ChildItem "C:\Users\Sebitas\ViraClip\exports\clips" | Where-Object { $_.Extension -ne ".mp4" } | Remove-Item -Recurse -Force

# Mostrar resultado
$clips = Get-ChildItem "C:\Users\Sebitas\ViraClip\exports\clips\*.mp4" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
Write-Host "`n✅ $($clips.Count) clips sincronizados:" -ForegroundColor Green
$clips | ForEach-Object { Write-Host "  - $($_.Name) ($([math]::Round($_.Length/1MB,1)) MB)" }
