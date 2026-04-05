# Week 1 Foundation - Testing Guide

Quick guide to test all implemented Week 1 features.

---

## Prerequisites

```powershell
# Start required services
cd C:\Users\rosav\ViraClip
docker-compose up -d backend redis postgres
```

---

## Test 1: Diagnostics Endpoint ✅

### Via PowerShell
```powershell
# Basic health check
curl http://localhost:8000/health

# Comprehensive diagnostics
curl http://localhost:8000/health/diagnostics | python -m json.tool
```

### Via Python Script
```powershell
docker-compose exec backend python /app/scripts/test_diagnostics.py
```

### Expected Output
```json
{
  "status": "healthy",
  "checks": {
    "ffmpeg": {"ok": true, "path": "/usr/bin/ffmpeg"},
    "ffprobe": {"ok": true, "path": "/usr/bin/ffprobe"},
    "groq_api": {"ok": true, "status_code": 200, "models_available": 10},
    "ollama": {"ok": true, "models": ["qwen3-vl:8b"], "vision_available": true},
    "redis": {"ok": true, "host": "redis", "port": 6379},
    "postgres": {"ok": true, "connection": "healthy"},
    "disk_space": {"ok": true, "free_gb": 50.2, "total_gb": 100.0},
    "python_modules": {
      "faster_whisper": {"ok": true},
      "moviepy": {"ok": true},
      "pydantic": {"ok": true},
      "httpx": {"ok": true}
    }
  }
}
```

---

## Test 2: SSE Progress Streaming ✅

### Browser Console (Chrome DevTools)
```javascript
// Open http://localhost:8000 in browser
// Open DevTools (F12) → Console

const taskId = 'test-' + Date.now();
const source = new EventSource(`http://localhost:8000/api/tasks/${taskId}/stream`);

source.onmessage = (e) => {
    const data = JSON.parse(e.data);
    console.log(`[${data.stage}] ${data.progress}% - ${data.message}`);
    
    if (data.stage === 'done' || data.stage === 'error') {
        source.close();
        console.log('Stream closed');
    }
};

source.onerror = (err) => {
    console.error('SSE error:', err);
    source.close();
};

// After 30s of no activity, you'll get a timeout
// This is expected - test passes if connection establishes
```

### Expected Output
```
[connected] 0% - Stream connected
(waits for events from backend)
```

---

## Test 3: Background Task Creation ✅

### Create Task
```powershell
# Create a processing task
$body = @{
    video_path = "/app/temp/test.mp4"
    language = "es"
    num_clips = 3
    processing_mode = "fast"
} | ConvertTo-Json

curl -X POST http://localhost:8000/api/tasks/process `
  -H "Content-Type: application/json" `
  -d $body
```

### Expected Response
```json
{
  "task_id": "abc-123-def-456",
  "status": "running",
  "stream_url": "/api/tasks/abc-123-def-456/stream",
  "created_at": "2024-04-04T12:30:00.000000"
}
```

### Check Task Status
```powershell
curl http://localhost:8000/api/tasks/abc-123-def-456/status
```

### Cancel Task
```powershell
curl -X DELETE http://localhost:8000/api/tasks/abc-123-def-456
```

### List All Tasks
```powershell
curl http://localhost:8000/api/tasks/all
```

---

## Test 4: Pydantic Validation ✅

### Python REPL
```python
# Inside Docker container
docker-compose exec backend python

>>> from backend.src.models.viral_segment import ViralSegment
>>> 
>>> # Valid segment
>>> segment = ViralSegment(
...     start="0:30",
...     end="1:15",
...     hook_strength=8.0,
...     emotional_peak=7.5,
...     shareability=9.0,
...     retention=8.5,
...     viral_score=8.25,
...     reason="Strong hook"
... )
>>> print(f"✅ Valid: {segment.start} - {segment.end}")
✅ Valid: 0:30 - 1:15

>>> # Invalid segment (too short)
>>> bad_segment = ViralSegment(
...     start="0:00",
...     end="0:20",  # Only 20 seconds!
...     hook_strength=8.0,
...     emotional_peak=7.5,
...     shareability=9.0,
...     retention=8.5,
...     viral_score=8.25,
...     reason="Too short"
... )
ValidationError: Segment duration must be at least 30 seconds, got 20s
```

---

## Test 5: Cache Checker ✅

### Python Script
```python
docker-compose exec backend python

>>> import asyncio
>>> from backend.src.services.cache_checker import get_cache_checker
>>> 
>>> async def test():
...     checker = get_cache_checker()
...     stats = await checker.get_cache_stats()
...     print(f"Total clips cached: {stats.get('total_clips', 0)}")
...     print(f"Cache size: {stats.get('total_size_gb', 0)} GB")
>>> 
>>> asyncio.run(test())
Total clips cached: 0
Cache size: 0.0 GB
```

---

## Test 6: Static/Dynamic Prompts ✅

### Python REPL
```python
docker-compose exec backend python

>>> from backend.src.services.ai_prompts import VIRAL_SCORER_SYSTEM_PROMPT, build_dynamic_user_prompt
>>> 
>>> # Static prompt (cached by Groq)
>>> print(f"Static prompt length: {len(VIRAL_SCORER_SYSTEM_PROMPT)} chars")
Static prompt length: 789 chars
>>> 
>>> # Dynamic prompt
>>> prompt = build_dynamic_user_prompt(
...     transcript="Este es un video sobre motivación",
...     language="es",
...     num_clips=3
... )
>>> print(f"Dynamic prompt length: {len(prompt)} chars")
Dynamic prompt length: 156 chars
>>> 
>>> # With error context
>>> prompt_retry = build_dynamic_user_prompt(
...     transcript="Test",
...     language="en",
...     num_clips=2,
...     previous_error="Duration too short"
... )
>>> print("Duration too short" in prompt_retry)
True
```

---

## Test 7: Full Pytest Suite ✅

### Run All Tests
```powershell
# From host
cd C:\Users\rosav\ViraClip\backend
python -m pytest tests/test_week1_foundation.py -v

# Or inside container
docker-compose exec backend python -m pytest tests/test_week1_foundation.py -v
```

### Expected Output
```
tests/test_week1_foundation.py::TestPydanticValidation::test_valid_segment PASSED
tests/test_week1_foundation.py::TestPydanticValidation::test_duration_too_short PASSED
tests/test_week1_foundation.py::TestPydanticValidation::test_end_before_start PASSED
tests/test_week1_foundation.py::TestPydanticValidation::test_viral_score_average_validation PASSED
tests/test_week1_foundation.py::TestPydanticValidation::test_distinct_scores_validation PASSED
tests/test_week1_foundation.py::TestAIValidator::test_successful_validation_first_attempt PASSED
tests/test_week1_foundation.py::TestAIValidator::test_retry_on_invalid_json PASSED
tests/test_week1_foundation.py::TestAIValidator::test_max_retries_exceeded PASSED
tests/test_week1_foundation.py::TestCacheChecker::test_cache_miss_no_clips PASSED
tests/test_week1_foundation.py::TestCacheChecker::test_cache_hit_valid_clips PASSED
tests/test_week1_foundation.py::TestCacheChecker::test_cache_invalid_old_clips PASSED
tests/test_week1_foundation.py::TestTaskManager::test_create_and_track_task PASSED
tests/test_week1_foundation.py::TestTaskManager::test_cancel_task PASSED
tests/test_week1_foundation.py::TestAIPrompts::test_static_prompt_is_string PASSED
tests/test_week1_foundation.py::TestAIPrompts::test_dynamic_prompt_generation PASSED
tests/test_week1_foundation.py::TestAIPrompts::test_dynamic_prompt_with_error PASSED

======================== 16 passed in 2.34s ========================
```

---

## Troubleshooting

### Issue: Diagnostics shows Redis error
**Solution**: Ensure Redis is running
```powershell
docker-compose up -d redis
curl http://localhost:8000/health/redis
```

### Issue: SSE connection refused
**Solution**: Check backend is running and CORS is configured
```powershell
docker-compose logs backend
```

### Issue: Task creation fails
**Solution**: Check video path exists
```powershell
docker-compose exec backend ls -la /app/temp/
```

### Issue: Pytest imports fail
**Solution**: Install test dependencies
```powershell
docker-compose exec backend pip install pytest pytest-asyncio
```

---

## Performance Benchmarks (TODO)

| Feature | Target | Actual | Status |
|---------|--------|--------|--------|
| SSE latency | < 500ms | TBD | ⏳ |
| Pydantic validation | > 95% success | TBD | ⏳ |
| Cache hit response | < 100ms | TBD | ⏳ |
| Parallel rendering | 2-3x faster | TBD | ⏳ |
| Diagnostics endpoint | < 5s | TBD | ⏳ |

Run benchmarks after integration with VideoService.

---

## Next Steps

1. ✅ Run all tests to verify Week 1 implementation
2. ⏳ Integrate coordinator with VideoService
3. ⏳ Add frontend EventSource client
4. ⏳ Collect performance benchmarks
5. ⏳ Deploy with feature flag (10% canary)
