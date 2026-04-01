@echo off
echo Creating test user...
docker exec viraclip-postgres psql -U viraclip -d viraclip -c "INSERT INTO users (id, email, name, created_at) VALUES ('test-user', 'test@example.com', 'Test User', NOW()) ON CONFLICT (id) DO NOTHING;"
echo.
echo Submitting frankenstein test task...
curl -s -X POST http://localhost:8000/tasks/ -H "Content-Type: application/json" -H "user_id: test-user" -d "{\"source\":{\"url\":\"https://youtu.be/3wgwaxIfUJQ\"},\"processing_mode\":\"balanced\",\"output_format\":\"vertical\",\"add_subtitles\":true,\"include_broll\":true}"
echo.
echo.
echo To monitor worker logs, run in another terminal:
echo docker-compose logs -f worker 2^>^&1 ^| findstr /i "TRANSCRIPTION SUBTITLES CROP EXPORT"
