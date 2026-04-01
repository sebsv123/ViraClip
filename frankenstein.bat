@echo off
curl -s -X POST http://localhost:8000/tasks/ -H "Content-Type: application/json" -H "user_id: test-user" -d "{\"source\":{\"url\":\"https://youtu.be/3wgwaxIfUJQ\"},\"processing_mode\":\"balanced\",\"output_format\":\"vertical\",\"add_subtitles\":true,\"include_broll\":true}"
