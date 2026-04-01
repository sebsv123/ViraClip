@echo off
echo Creating test user if not exists...
docker exec viraclip-postgres psql -U viraclip -d viraclip -c "INSERT INTO users (id, email, name) VALUES ('test-user', 'test@example.com', 'Test User') ON CONFLICT (id) DO NOTHING;" 2>nul
echo.
echo Submitting frankenstein test task...
curl -s -X POST http://localhost:8000/tasks/ -H "Content-Type: application/json" -H "user_id: test-user" -d "{\"source\":{\"url\":\"https://youtu.be/3wgwaxIfUJQ\"},\"processing_mode\":\"balanced\",\"output_format\":\"vertical\",\"add_subtitles\":true,\"include_broll\":true}"
echo.
echo.
echo To monitor this task, run: monitor_task.bat ^<task_id^>
