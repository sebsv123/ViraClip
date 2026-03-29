# Monitor_ViraClip.ps1 - Expert Monitoring
Write-Host "--- 🟢 ViraClip Expert Log Monitor 🟢 ---" -ForegroundColor Green
Write-Host "Presiona Ctrl+C para detener." -ForegroundColor Cyan

# Unified monitoring command
docker logs -f --tail 100 supoclip-worker supoclip-backend
