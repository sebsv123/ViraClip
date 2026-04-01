# Video Utils Refactoring Plan

## Current State
- **File:** `backend/src/video_utils.py`
- **Size:** 3158 lines
- **Functions:** ~80+ functions
- **Problem:** Monolithic file, hard to maintain

## Target Structure

```
backend/src/
├── video_utils.py (backward compatibility wrapper - 50 lines)
└── video_processing/
    ├── __init__.py (exports for backward compatibility)
    ├── utils.py (shared utilities - DONE ✅)
    ├── transcription.py (transcription & caching - ~500 lines)
    ├── face_detection.py (face/speaker detection - ~600 lines)
    ├── subtitles.py (subtitle generation - ~800 lines)
    ├── audio.py (background music - ~200 lines)
    └── clip_creation.py (main rendering - ~800 lines)
```

## Module Breakdown

### ✅ utils.py (DONE)
- `inject_emoji()`
- `format_ms_to_timestamp()`
- `round_to_even()`
- `get_scaled_font_size()`
- `get_subtitle_max_width()`
- `get_safe_vertical_position()`
- `parse_timestamp_to_seconds()`

### 🔄 transcription.py (IN PROGRESS)
Functions to extract:
- `_get_video_content_hash()`
- `_hash_cache_path()`
- `_get_whisper_model()`
- `get_video_transcript()`
- `cache_transcript_data()`
- `load_cached_transcript_data()`
- `snap_to_word_boundary()`
- `_serialize_transcript_word()`
- `format_transcript_for_analysis()`

### 📋 face_detection.py
Functions to extract:
- `detect_optimal_crop_region()`
- `detect_faces_in_clip()`
- `filter_face_outliers()`
- `detect_face_trajectory()`
- `_mouth_openness()`
- `detect_active_speaker_trajectory()`
- `_smooth_1d()`
- `create_dynamic_crop_clip()`

### 📝 subtitles.py
Functions to extract:
- `get_words_in_range()`
- `adaptive_word_groups()`
- `create_bounce_subtitles()`
- `create_assemblyai_subtitles()`
- `create_static_subtitles()`
- `create_karaoke_subtitles()`
- `create_pop_subtitles()`
- `create_fade_subtitles()`

### 🎵 audio.py
Functions to extract:
- `_get_background_music_path()`
- `fetch_pixabay_music()`
- `get_background_music_for_niche()`
- `mix_background_music()`

### 🎬 clip_creation.py
Functions to extract:
- `VideoProcessor` class
- `create_optimized_clip()` (main function)

## Benefits

1. **Maintainability:** 6 focused modules vs 1 monolith
2. **Testability:** Easier to test individual modules
3. **Readability:** Clear separation of concerns
4. **Scalability:** Easy to add new features to specific modules
5. **Backward Compatibility:** Old imports still work via wrapper

## Migration Strategy

1. ✅ Create `video_processing/` package
2. ✅ Extract `utils.py` (shared utilities first)
3. 🔄 Extract remaining modules in dependency order
4. ✅ Create `video_processing/__init__.py` with re-exports
5. ⏳ Create `video_utils.py` wrapper (backward compatibility)
6. ⏳ Update imports in dependent files (if needed)
7. ⏳ Run tests to verify no breakage
8. ⏳ Document changes

## Backward Compatibility

Old code will continue to work:
```python
# Old way (still works)
from src.video_utils import create_optimized_clip

# New way (preferred)
from src.video_processing import create_optimized_clip
```

## Testing Plan

1. Run existing tests
2. Process a sample video end-to-end
3. Verify all subtitle styles work
4. Verify face detection works
5. Verify background music mixing works

---

**Status:** 🔄 IN PROGRESS (2/7 modules complete)
**ETA:** ~20 minutes
