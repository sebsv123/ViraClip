# Launch_ViraClip.ps1 - Expert One-Click Start
Write-Host "--- ViraClip Pipeline ---" -ForegroundColor Green

Set-Location "C:\Users\Sebitas\SupoClip-Propio"

Write-Host "Starting Docker..." -ForegroundColor Cyan
docker-compose up -d --build

Write-Host "Opening Web UI..." -ForegroundColor Cyan
Start-Process "http://localhost:3000"

Write-Host "ViraClip is running!" -ForegroundColor Green
# No Read-Host to avoid PowerShell encoding/parser issues
