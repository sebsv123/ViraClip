$headers = @{
    "user_id" = "86419bd0-053f-47d8-ba6a-8d17d21b325a"
}

$body = @{
    source = @{
        url = "https://youtu.be/bsw9jy-rYzw?si=MnsOshi3G9i9Gc_h"
    }
    processing_mode = "fast"
    output_format = "vertical"
    add_subtitles = $true
} | ConvertTo-Json -Depth 6

$response = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/tasks" -Headers $headers -ContentType "application/json" -Body $body

$response | ConvertTo-Json -Depth 6
