# Timeline System Quick Start Guide

**5-Minute Guide to Using Videofy Timeline Integration**

---

## Prerequisites

- ViraClip backend running (`docker-compose up -d`)
- OpenAI API key set (optional, for Vision AI)

---

## Step 1: Enable Timeline Building (30 seconds)

### Option A: Per-Task (Recommended for Testing)

```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "source_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
    "num_clips": 1,
    "config": {
      "enable_timeline": true,
      "enable_vision_ai": false
    }
  }'
```

### Option B: Global (docker-compose.yml)

```yaml
services:
  backend:
    environment:
      - ENABLE_TIMELINE=true
      - ENABLE_VISION_AI=false  # Set to true for Vision AI
      - OPENAI_API_KEY=sk-...   # Required if enable_vision_ai=true
```

---

## Step 2: Check Timeline was Built (10 seconds)

```bash
# Get timeline for task
curl http://localhost:8000/timeline/{task_id}

# Get metrics for task
curl http://localhost:8000/timeline/metrics/{task_id}
```

**Expected Response:**
```json
{
  "status": "success",
  "timeline": {
    "clip_id": "task-123-timeline",
    "segments": [
      {
        "id": 0,
        "virality_score": 85.0,
        "camera_movement": "zoom-in",
        "texts": [...],
        "assets": [...]
      }
    ]
  }
}
```

---

## Step 3: View Timeline Files (10 seconds)

Timeline files are saved in the project folder:

```
projects/<task_id>/
  working/
    timeline.json          ← Full ClipTimeline structure
    analysis/
      frames/*.jpg         ← Extracted frames (if Vision AI enabled)
      descriptions.json    ← Frame descriptions
      placements.json      ← Frame→segment mapping
```

**Docker command:**
```bash
docker exec viraclip-backend ls -la /app/projects/<task_id>/working/
```

---

## Step 4: Monitor Timeline Metrics (30 seconds)

### Aggregate Stats
```bash
curl http://localhost:8000/timeline/metrics/aggregate
```

**Response:**
```json
{
  "total_timelines": 10,
  "successful_timelines": 9,
  "success_rate": 0.9,
  "avg_total_duration": 1.2,
  "avg_vision_ai_duration": 12.5,
  "total_frames_extracted": 80,
  "vision_error_rate": 0.05
}
```

### Recent Timelines
```bash
curl http://localhost:8000/timeline/metrics/recent?limit=5
```

### Health Check
```bash
curl http://localhost:8000/timeline/health
```

---

## Step 5: Run Demo Script (2 minutes)

**Inside Docker container:**
```bash
docker exec -it viraclip-backend bash

# Run demo with sample video
python /app/scripts/demo_timeline.py \
  --video /app/temp/sample.mp4 \
  --enable-vision

# Or without Vision AI (faster)
python /app/scripts/demo_timeline.py \
  --video /app/temp/sample.mp4
```

**Expected output:**
```
[Step 1] Initializing project store...
[Step 2] Creating mock Whisper words...
[Step 3] Creating mock AI segment...
[Step 4] OpenAI client initialized for Vision AI
[Step 5] Building ClipTimeline...
[Timeline] Extracted 8 frames from video.mp4
[Timeline] Described 8 frames
[Timeline] Assigned 8 frames to segments
[Timeline] Built timeline with 1 segments, duration=3.8s

✅ Timeline Built Successfully!
```

---

## Common Use Cases

### Use Case 1: Enable Vision AI for Better Context

```json
{
  "config": {
    "enable_timeline": true,
    "enable_vision_ai": true  // Adds 10-15s, costs ~$0.001/clip
  }
}
```

**What you get:**
- GPT-4o descriptions of video frames
- Smart frame→segment assignments
- Visual context for future B-roll matching

### Use Case 2: Skip Vision AI for Speed

```json
{
  "config": {
    "enable_timeline": true,
    "enable_vision_ai": false  // <1s overhead
  }
}
```

**What you get:**
- ClipTimeline structure
- Camera movement assignments
- Word-level TextLines
- Restart capability

### Use Case 3: Check if Timeline Exists

```bash
# Returns 404 if timeline not built
curl http://localhost:8000/timeline/{task_id}
```

---

## Troubleshooting

### Timeline Not Building

**Symptom:** No `timeline.json` file created

**Check:**
```bash
docker logs viraclip-backend | grep "\[Timeline\]"
```

**Solutions:**
1. Verify `enable_timeline: true` in config
2. Check logs for errors
3. Ensure sufficient disk space in `/app/projects`

### Vision AI Timeout

**Symptom:** Timeline building takes >30s

**Solution:** Disable Vision AI temporarily
```json
{"config": {"enable_vision_ai": false}}
```

### OpenAI API Errors

**Symptom:** `No Vision AI analysis found`

**Check API key:**
```bash
docker exec viraclip-backend env | grep OPENAI_API_KEY
```

**Solution:** Add to docker-compose.yml
```yaml
environment:
  - OPENAI_API_KEY=sk-...
```

---

## Performance Expectations

| Configuration | Build Time | Cost/Clip | Use When |
|--------------|------------|-----------|----------|
| Timeline only | <1s | $0 | Speed is critical |
| Timeline + Vision | 10-15s | ~$0.001 | Want visual context |

**For 100 clips/day:**
- Timeline only: ~2 minutes total
- Timeline + Vision: ~25 minutes total, ~$0.10/day

---

## API Endpoints Reference

### Timeline Access
- `GET /timeline/{task_id}` - Get full timeline
- `GET /timeline/{task_id}/segments` - Get segments only
- `GET /timeline/{task_id}/analysis` - Get Vision AI data

### Metrics
- `GET /timeline/metrics/aggregate` - Overall stats
- `GET /timeline/metrics/recent?limit=10` - Recent timelines
- `GET /timeline/metrics/{task_id}` - Task-specific metrics

### Health
- `GET /timeline/health` - System health check
- `DELETE /timeline/metrics/clear?max_age_hours=24` - Clear old metrics

---

## Next Steps

### Immediate
1. ✅ Enable timeline on test task
2. ✅ Check metrics endpoint
3. ✅ Verify timeline.json created

### Week 1
1. Enable on 10% of production tasks
2. Monitor performance metrics
3. Check Vision AI costs

### Week 2-4
1. Expand to 50% of tasks
2. Implement camera movement rendering
3. Merge with Phase 9 Creative Engine

---

## Integration with Existing Systems

### Frontend Integration
```typescript
// Check if timeline exists
const response = await fetch(`/api/timeline/${taskId}`);
if (response.ok) {
  const { timeline } = await response.json();
  // Display timeline UI
}
```

### Worker Integration
```python
# In coordinator.py
if config.get("enable_timeline"):
    timeline = await build_clip_timeline(...)
    # Timeline automatically saved to projects/<task_id>/working/
```

---

## FAQ

**Q: Does timeline building slow down clip generation?**  
A: Minimal impact (<1s without Vision AI, 10-15s with Vision AI)

**Q: Is it enabled by default?**  
A: No, opt-in via `config.enable_timeline = true`

**Q: Can I use timeline without Vision AI?**  
A: Yes, set `enable_vision_ai: false` for fast timeline building

**Q: Where are timeline files stored?**  
A: `projects/<task_id>/working/timeline.json` and `analysis/`

**Q: How do I render with camera movements?**  
A: Use `apply_timeline_to_clip()` from `timeline_renderer.py` (future feature)

**Q: Does it work with existing clips?**  
A: Only new clips with `enable_timeline: true`. Existing clips can't be retroactively analyzed (would need re-processing)

---

## Support

- **Documentation**: `VIDEOFY_INTEGRATION.md`, `CONFIG_VIDEOFY.md`
- **Logs**: `docker logs viraclip-backend | grep Timeline`
- **Metrics**: `GET /timeline/metrics/aggregate`
- **Health**: `GET /timeline/health`

---

**Ready to start?** Enable timeline on your next task and check the metrics! 🚀
