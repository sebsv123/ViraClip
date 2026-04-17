# Videofy Integration - ViraClip Enhancement

**Date**: April 5, 2026  
**Status**: Core Implementation Complete  
**Tests**: 23/23 passing ✅

## Overview

This integration applies patterns from [schibsted/videofy_minimal](https://github.com/schibsted/videofy_minimal) to solve ViraClip's critical data contract gap between AI analysis (`ai.py`) and video rendering (`video_utils.py`).

### The Problem We Solved

ViraClip had multiple parallel pipeline versions competing (`video_utils.py`, `video_utils_legacy.py`, `viraclip_pipeline.py`, etc.) with **no unified data contract** connecting AI analysis to rendering. This caused:

- Lost metadata on render failures
- No persistence of intermediate analysis
- Inability to restart failed renders
- Disconnected AI scoring and visual effects

### The Solution

Videofy provides a **structured timeline approach** that bridges analysis and rendering through a formal data contract:

```
AI Analysis → ClipTimeline → Renderer
(ai.py)      (schemas_v2)    (video_effects)
```

---

## Architecture

### New Files

| File | Purpose | Lines |
|------|---------|-------|
| `backend/src/schemas_v2.py` | Data contract: `Segment`, `TextLine`, `ClipTimeline` | 70 |
| `backend/src/asset_analysis.py` | Vision AI frame extraction, description, placement | 170 |
| `backend/src/project_store.py` | Persistent `input/working/output` state | 140 |
| `backend/src/services/timeline_builder.py` | Whisper + AI → `ClipTimeline` bridge | 220 |
| `backend/src/services/timeline_renderer.py` | `ClipTimeline` → FFmpeg render | 205 |
| `backend/tests/test_videofy_integration.py` | Integration tests (23 tests) | 400 |

### Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Input Phase                                                  │
│    YouTube/Upload → projects/<task_id>/input/video.mp4          │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. Analysis Phase (working/)                                    │
│    ├─ Whisper → transcript.json (word-level timestamps)         │
│    ├─ ai.py → segments.json (virality, hook, mood)              │
│    └─ Vision AI → analysis/                                     │
│         ├─ frames/*.jpg (extracted frames)                      │
│         ├─ descriptions.json (GPT-4o Vision)                    │
│         └─ placements.json (frame→segment mapping)              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Timeline Building (NEW - timeline_builder.py)                │
│    build_clip_timeline() combines:                              │
│    • Whisper words → TextLine[] (caption timing)                │
│    • AI segments → Segment[] (virality scores)                  │
│    • Vision frames → SegmentAsset[] (visual context)            │
│    • Camera movements (cyclic: zoom-in, pan-right, etc.)        │
│    Output: working/timeline.json (ClipTimeline)                 │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. Rendering Phase (NEW - timeline_renderer.py)                 │
│    apply_timeline_to_clip() generates:                          │
│    • FFmpeg zoompan filters (camera movements)                  │
│    • ASS subtitles (word-synced captions)                       │
│    • Final MP4 → output/clip_XX.mp4                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## Core Concepts

### 1. ClipTimeline (Data Contract)

Bridges the gap between AI and rendering:

```python
from src.schemas_v2 import ClipTimeline, Segment, TextLine

timeline = ClipTimeline(
    clip_id="task-123-timeline",
    task_id="task-123",
    source_url="https://youtube.com/...",
    preset="tiktok_viral",
    segments=[
        Segment(
            id=0,
            virality_score=85.0,      # From ai.py
            hook_score=22.0,
            hook_type="question",
            mood="hype",
            camera_movement="zoom-in", # From Videofy
            style="bottom",
            texts=[
                TextLine(
                    line_id=0,
                    text="Check out this hack",
                    start=0.0,
                    end=1.5
                )
            ],
            assets=[
                SegmentAsset(
                    type="frame",
                    path="/app/projects/.../frames/f001.jpg",
                    description="Person pointing at screen"
                )
            ],
            start=0.0,
            end=1.5
        )
    ],
    total_duration=1.5
)
```

### 2. ProjectStore (Persistence)

Solves the "render restart" problem:

```python
from src.project_store import ProjectStore

store = ProjectStore()

# Check if we can skip already-completed steps
if store.is_step_done(task_id, "transcript"):
    transcript = store.load_json(task_id, "transcript.json")
else:
    # Run Whisper...
    store.save_json(task_id, "transcript.json", transcript)

# Folder structure auto-created:
# projects/<task_id>/
#   input/video.mp4
#   working/transcript.json
#   output/clip_01.mp4
```

### 3. Vision AI Frame Analysis

GPT-4o Vision describes key frames:

```python
from src.asset_analysis import (
    extract_frames_from_clip,
    describe_frame,
    assign_frames_to_segments
)

# Extract 6-8 evenly-spaced frames
frames = extract_frames_from_clip(video_path, output_dir, "clip-1", n_frames=8)

# Describe each frame with Vision AI
for frame in frames:
    description = describe_frame(Path(frame["path"]), openai_client)
    # → "A person speaking enthusiastically while gesturing"

# AI assigns best frame to each segment
assignments = assign_frames_to_segments(
    segment_texts=["intro", "main point", "outro"],
    frame_descriptions=frames,
    client=openai_client
)
# → ["f001", "f003", "f006"]
```

### 4. Camera Movements (Videofy Pattern)

Cyclic zoom/pan patterns from `DEFAULT_CAMERA_MOVEMENTS`:

```python
# Segments automatically get cyclic camera movements:
movements = ["zoom-in", "pan-right", "zoom-in", "pan-left", "zoom-in", "zoom-out"]
# Segment 0 → zoom-in
# Segment 1 → pan-right
# Segment 2 → zoom-in
# ...
```

FFmpeg zoompan filters are generated in `timeline_renderer.py`:

```python
"zoom-in"   → zoompan=z='min(zoom+0.0015,1.5)':d=75:fps=25
"pan-right" → zoompan=z=1.2:x='iw/2-(iw/zoom/2)+t*8':d=75:fps=25
```

---

## Integration Points with Existing ViraClip

### Connects To

| Existing Module | Integration Point |
|----------------|-------------------|
| `ai.py` | Receives `virality_score`, `hook_score`, `hook_type`, `mood` |
| `video_processing.get_video_transcript()` | Receives Whisper `word_timings` with `start`/`end` |
| `creative_pipeline.py` | Can consume `ClipTimeline` for enhanced rendering |
| `coordinator.py` | Orchestrates `build_clip_timeline()` → `apply_timeline_to_clip()` |
| `video_effects.py` | Replaced by `timeline_renderer.apply_timeline_to_clip()` for timeline-based clips |

### Does NOT Break

- Existing Phase 9 Creative Engine (hook flash, zoom punch, B-roll, audio mastering)
- Existing caption templates (`caption_templates.py`)
- Existing viral metadata (`viral_metadata_service.py`)
- SmartAutoEditor text pops

### Migration Strategy

**Option A: Parallel Mode (Recommended)**
- Keep existing pipeline for backward compatibility
- Add new `--use-timeline` flag to coordinator
- New clips use `ClipTimeline`, old workflows unchanged

**Option B: Full Migration**
- Replace `video_effects.py` calls with `timeline_renderer.py`
- Merge Phase 9 creative effects into `ClipTimeline.Segment` metadata
- One unified rendering path

---

## Usage Examples

### Basic Timeline Building

```python
from src.services.timeline_builder import build_clip_timeline
from src.project_store import ProjectStore
from openai import OpenAI

store = ProjectStore()
openai_client = OpenAI(api_key="...")

timeline = await build_clip_timeline(
    task_id="task-123",
    video_path=Path("/app/projects/task-123/input/video.mp4"),
    whisper_words=[
        {"word": "hello", "start": 0.0, "end": 0.5},
        {"word": "world", "start": 0.6, "end": 1.0},
    ],
    ai_segments=[
        {
            "text": "hello world",
            "start_time": 0.0,
            "end_time": 1.0,
            "virality_score": 85.0,
            "hook_score": 20.0,
            "hook_type": "question",
            "mood": "hype"
        }
    ],
    store=store,
    openai_client=openai_client,
    preset="tiktok_viral",
    skip_vision=False,  # Enable Vision AI
)

# Timeline saved to: projects/task-123/working/timeline.json
```

### Rendering from Timeline

```python
from src.services.timeline_renderer import apply_timeline_to_clip

output = await apply_timeline_to_clip(
    timeline=timeline,
    source_video=Path("/app/projects/task-123/input/video.mp4"),
    output_path=Path("/app/projects/task-123/output/clip_01.mp4"),
)

# Output: clip_01.mp4 with:
# - Camera movements (zoom/pan per segment)
# - Word-synced captions (ASS format)
# - Original audio
```

### Skip Completed Steps

```python
# On restart, skip already-completed work
if not store.is_step_done(task_id, "timeline"):
    timeline = await build_clip_timeline(...)
    store.save_json(task_id, "timeline.json", timeline.model_dump())
else:
    timeline_data = store.load_json(task_id, "timeline.json")
    timeline = ClipTimeline(**timeline_data)

# Render only if not already done
if not store.is_step_done(task_id, "render"):
    await apply_timeline_to_clip(...)
```

---

## Testing

All 23 tests passing:

```bash
docker exec viraclip-backend .venv/bin/python -m pytest tests/test_videofy_integration.py -v
```

### Test Coverage

| Module | Tests | Coverage |
|--------|-------|----------|
| `schemas_v2.py` | 5 tests | Segment creation, asset types, timeline duration, camera movements |
| `project_store.py` | 6 tests | Path creation, JSON save/load, step tracking, cleanup |
| `asset_analysis.py` | 4 tests | Frame extraction, Vision AI description, cyclic fallback |
| `timeline_builder.py` | 2 tests | Basic timeline building, word grouping into TextLines |
| `timeline_renderer.py` | 6 tests | ASS subtitle generation, camera filters, FFmpeg rendering |

---

## Performance Characteristics

| Operation | Time | Notes |
|-----------|------|-------|
| Frame extraction (8 frames) | ~2s | FFmpeg, depends on video length |
| Vision AI descriptions (8 frames) | ~8-12s | GPT-4o-mini, parallel requests possible |
| Frame→segment assignment | ~1-2s | GPT-4o-mini JSON response |
| Timeline building | ~15s total | Includes all Vision AI steps |
| Rendering with camera movements | ~5-30s | Depends on clip length, FFmpeg zoompan |

**Optimization**: Set `skip_vision=True` to skip Vision AI (reduces timeline building to <1s)

---

## Configuration

### Environment Variables

```bash
# Required for Vision AI
OPENAI_API_KEY=sk-...

# Optional: disable Vision AI globally
ENABLE_VISION_ANALYSIS=false

# Project storage location
PROJECT_STORE_BASE=/app/projects
```

### Presets

Currently supported in `ClipTimeline.preset`:
- `default`
- `tiktok_viral`
- `reels_drama`
- `youtube_shorts`

(Future: map presets to specific camera movement patterns)

---

## Future Enhancements

### Immediate Next Steps

1. **Wire into coordinator.py**
   - Add `build_clip_timeline()` call after AI analysis
   - Use `apply_timeline_to_clip()` for final render
   - Persist timeline.json for restart capability

2. **Merge with Phase 9 Creative Engine**
   - Store Phase 9 metadata in `Segment.extra` field
   - Combine camera movements with zoom punch
   - Unified rendering path

3. **Multi-clip support**
   - Generate separate timeline per clip
   - `extract_segment_clip()` for individual exports

### Advanced Features (Post-MVP)

- **Dynamic camera movements**: AI decides movement based on segment mood
- **Hotspot detection**: Face detection → smart cropping in camera movements
- **B-roll integration**: `SegmentAsset` type="broll" with timeline sync
- **Effect stacking**: Multiple camera movements per segment (zoom + pan)
- **Preset templates**: Pre-defined movement sequences per niche

---

## Troubleshooting

### Timeline Not Saved

**Issue**: `timeline.json` not found after building  
**Fix**: Check `ProjectStore` base directory is writable:
```python
store = ProjectStore(base_dir="/app/projects")  # Must exist + writable
```

### Vision AI Timeout

**Issue**: OpenAI API timeout during frame description  
**Fix**: Reduce frame count or disable Vision:
```python
timeline = await build_clip_timeline(..., skip_vision=True)
```

### FFmpeg Rendering Fails

**Issue**: `apply_timeline_to_clip()` raises timeout  
**Fix**: Check FFmpeg logs, increase timeout:
```python
await asyncio.wait_for(proc.communicate(), timeout=1200.0)  # 20min
```

### Camera Movement Not Applied

**Issue**: Video renders without zoom/pan  
**Fix**: Ensure segment has valid `camera_movement`:
```python
seg.camera_movement in VALID_CAMERA_MOVEMENTS  # Must be true
```

---

## Comparison: Before vs After

### Before (ViraClip Original)

```
YouTube → Whisper → ai.py → video_utils.py → clip.mp4
                      ↓           ↓
                   (lost)     (ephemeral)
```

**Problems**:
- AI analysis not persisted
- Render failure = recompute everything
- No connection between AI scores and visual effects
- Multiple pipeline versions

### After (Videofy Integration)

```
YouTube → ProjectStore/input/
            ↓
        Whisper → working/transcript.json ✓
            ↓
        ai.py → working/segments.json ✓
            ↓
        Vision AI → working/analysis/* ✓
            ↓
        build_clip_timeline → working/timeline.json ✓
            ↓
        apply_timeline_to_clip → output/clip.mp4 ✓
```

**Benefits**:
- Every step persisted
- Restart from any point
- Formal data contract (ClipTimeline)
- Vision AI context for segments
- Cyclic camera movements
- One source of truth

---

## Credits

- **Videofy Minimal**: [schibsted/videofy_minimal](https://github.com/schibsted/videofy_minimal)
- **ViraClip Team**: Integration and adaptation
- **OpenAI GPT-4o**: Vision AI frame descriptions

---

## License

Same as ViraClip parent project.
