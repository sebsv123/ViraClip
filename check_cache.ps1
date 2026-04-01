$taskId = "29db5919-c5b9-49a2-a2a0-4a42198f6fb8"

Write-Host "=== Checking transcript cache ===" -ForegroundColor Cyan
$transcriptPath = "/app/temp/cache/transcripts/$taskId.json"
try {
    $result = docker-compose exec -T worker cat $transcriptPath 2>$null
    if ($result) {
        $result | ConvertFrom-Json | ConvertTo-Json -Depth 3 | Select-Object -First 50
    } else {
        Write-Host "Transcript cache not found or empty" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Error reading transcript: $_" -ForegroundColor Red
}

Write-Host "`n=== Checking analysis cache ===" -ForegroundColor Cyan
$analysisPath = "/app/temp/cache/analysis/$taskId.json"
try {
    $result = docker-compose exec -T worker cat $analysisPath 2>$null
    if ($result) {
        $result | ConvertFrom-Json | ConvertTo-Json -Depth 3 | Select-Object -First 100
    } else {
        Write-Host "Analysis cache not found or empty" -ForegroundColor Yellow
    }
} catch {
    Write-Host "Error reading analysis: $_" -ForegroundColor Red
}
