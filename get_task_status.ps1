param(
    [string]$TaskId
)

if (-not $TaskId) {
    Write-Error "TaskId is required"
    exit 1
}

$headers = @{ "user_id" = "86419bd0-053f-47d8-ba6a-8d17d21b325a" }

$response = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/tasks/$TaskId" -Headers $headers

$response | ConvertTo-Json -Depth 6
