# Videofy Timeline Configuration

## Overview

The Videofy timeline integration is **opt-in** and runs in parallel with the existing ViraClip pipeline. When enabled, it builds a structured `ClipTimeline` that can be used for advanced rendering features.

## Configuration Flags

Add these to your task configuration or environment variables:

### Enable Timeline Building

```python
config = {
    "enable_timeline": True,  # Build ClipTimeline during processing
    "enable_vision_ai": True,  # Use GPT-4o Vision for frame analysis (requires OPENAI_API_KEY)
}
```

### Environment Variables

```bash
# Required for Vision AI frame descriptions
OPENAI_API_KEY=sk-...

# Optional: customize project storage location
PROJECT_STORE_BASE=/app/projects

# Optional: disable Vision AI globally (faster, but no visual context)
ENABLE_VISION_ANALYSIS=false
```

## Usage

### Option 1: Enable in Task Request

```python
POST /tasks
{
    "source_url": "https://youtube.com/watch?v=...",
    "num_clips": 3,
    "config": {
        "enable_timeline": true,
        "enable_vision_ai": true
    }
}
```

### Option 2: Enable in docker-compose.yml

```yaml
services:
  backend:
    environment:
      - ENABLE_TIMELINE=true
      - ENABLE_VISION_AI=true
      - OPENAI_API_KEY=${OPENAI_API_KEY}
```

## What Happens When Enabled

1. **After AI Analysis** - Coordinator calls `build_clip_timeline()`
2. **Timeline Saved** - Persisted to `projects/<task_id>/working/timeline.json`
3. **Vision AI (if enabled)** - Frames extracted, described with GPT-4o, assigned to segments
4. **Metadata Added** - `timeline_built: true` added to clip creative_meta

## File Structure

When timeline is enabled:

```
projects/<task_id>/
  input/
    video.mp4
  working/
    transcript.json
    segments.json
    timeline.json          ← NEW: ClipTimeline data contract
    analysis/
      frames/
        f001.jpg
        f002.jpg
        ...
      descriptions.json    ← Vision AI frame descriptions
      placements.json      ← Frame→segment assignments
  output/
    clip_01.mp4
```

## Timeline JSON Structure

```json
{
  "clip_id": "task-123-timeline",
  "task_id": "task-123",
  "preset": "tiktok_viral",
  "segments": [
    {
      "id": 0,
      "virality_score": 85.0,
      "hook_score": 22.0,
      "hook_type": "question",
      "mood": "hype",
      "camera_movement": "zoom-in",
      "texts": [
        {
          "line_id": 0,
          "text": "Check out this hack",
          "start": 0.0,
          "end": 1.5
        }
      ],
      "assets": [
        {
          "type": "frame",
          "path": "/app/projects/.../f001.jpg",
          "description": "Person pointing at screen"
        }
      ],
      "start": 0.0,
      "end": 1.5
    }
  ],
  "total_duration": 1.5
}
```

## Performance Impact

| Operation | Time | Impact |
|-----------|------|--------|
| Timeline building (no Vision) | <1s | Minimal |
| Vision AI (8 frames) | ~10-15s | Adds to total processing time |
| Timeline saving | <100ms | Minimal |

**Recommendation**: Start with `enable_vision_ai: false` to test, then enable for production.

## Backward Compatibility

- **Default**: Timeline building is **disabled**
- **Existing workflows**: Continue working unchanged
- **No breaking changes**: All existing clips render normally
- **Gradual rollout**: Enable per-task or globally

## Future Features (Using Timeline)

Once timeline is built, future features can use it:

1. **Camera Movement Rendering** - `apply_timeline_to_clip()` with zoom/pan
2. **Multi-segment clips** - Extract individual segments from timeline
3. **Visual context B-roll** - Use frame descriptions for better asset matching
4. **Advanced caption timing** - Use TextLine word-level sync

## Example: Full Timeline Workflow

```python
from src.project_store import ProjectStore
from src.services.timeline_builder import build_clip_timeline
from src.services.timeline_renderer import apply_timeline_to_clip
from src.schemas_v2 import ClipTimeline

# 1. Build timeline (done automatically by coordinator if enabled)
store = ProjectStore()
timeline = await build_clip_timeline(
    task_id="task-123",
    video_path=Path("/app/projects/task-123/input/video.mp4"),
    whisper_words=words,
    ai_segments=segments,
    store=store,
    openai_client=openai_client,
    skip_vision=False,
)

# 2. Later: render with timeline
output = await apply_timeline_to_clip(
    timeline=timeline,
    source_video=Path("/app/projects/task-123/input/video.mp4"),
    output_path=Path("/app/projects/task-123/output/timeline_render.mp4"),
)
```

## Troubleshooting

### Timeline not building

**Check**: `enable_timeline` in config
```python
logger.info(f"Timeline enabled: {config.get('enable_timeline', False)}")
```

### Vision AI timing out

**Solution**: Disable Vision AI temporarily
```python
config["enable_vision_ai"] = False
```

### OpenAI API errors

**Check**: API key is set
```bash
docker exec viraclip-backend env | grep OPENAI_API_KEY
```

## Monitoring

Check logs for timeline steps:

```
[Timeline] Extracted 8 frames from video.mp4
[Timeline] Described 8 frames
[Timeline] Assigned 8 frames to segments
[Timeline] Built timeline with 3 segments, duration=15.2s
```

## Cost Estimation

Vision AI costs (GPT-4o-mini):

- Frame description: ~$0.0001 per frame
- Frame placement: ~$0.0001 per request
- **Total per clip**: ~$0.001 (8 frames + 1 placement)

For 100 clips/day: **~$0.10/day** in Vision AI costs.
