# ViraClip Pipeline Trace — Real Clip Flow Analysis

**Date:** 2026-05-16  
**Test clip:** 5-10 min talking-head/podcast (e.g., interview format)  
**Staging flags:** All integrations enabled (see §1)  

---

## 1. Staging Configuration

```env
CAPTION_BACKEND=auto_subtitle
EXPORT_PRESET=tiktok_basic
AI_BROLL_ENABLED=True
SHORT_VIDEO_MAKER_PEXELS_ENABLED=True
BACKGROUND_MUSIC_ENABLED=True
AI_CLIPS_MAKER_ENABLED=True
CLIPSAI_ENABLED=True
SHORTS_ENGINE_ENABLED=True
EDITLIST_ENABLED=True
EDITLIST_ENABLE_CUTS=True
EDITLIST_ENABLE_OVERLAYS=True
EDITLIST_ENABLE_TRANSITIONS=True
```

---

## 2. Full Pipeline Trace (Numbered Steps)

### Phase A — Preflight & Ingestion

```
A1. process_task() entry
    [_processor_mixin.py:51]
    ├── Validate task_id, url, source_type
    ├── Download source video → /tmp/viraclip/inputs/{task_id}.mp4
    ├── Detect GPU capabilities → render_concurrency
    └── Create output directories

A2. Preflight analysis
    [_processor_mixin.py ~line 200]
    ├── Probe video: duration, resolution, codec, fps (ffprobe)
    ├── Detect aspect ratio → decide if reframe needed
    └── Extract audio track → /tmp/viraclip/audio/{task_id}.wav

A3. Transcription
    [_processor_mixin.py ~line 300]
    ├── Whisper (large-v3) → segments with word-level timestamps
    │   └── [FLAG] WHISPER_MODEL_SIZE=large-v3
    ├── AssemblyAI (if ASSEMBLY_AI_API_KEY set) → confidence scores
    │   └── [FLAG] CAPTION_BACKEND=auto_subtitle → uses confidence data
    └── Store: transcript dict with segments[{start, end, text, words[]}]

A4. Vision analysis (multimodal)
    [_processor_mixin.py ~line 400]
    ├── Extract keyframes (1 per 5s)
    ├── LLM vision (Gemini/Groq) → scene descriptions, topics, mood
    └── Store: vision_meta with topics[], mood, energy_level

A5. Viral gate — segment scoring
    [_processor_mixin.py ~line 500]
    ├── Score each transcript segment (0-100) based on:
    │   - Hook potential (first 3s grab)
    │   - Emotional peaks
    │   - Opinion/controversy signals
    │   - Topic density
    ├── Filter: keep segments with score >= VIRAL_THRESHOLD (default 60)
    └── Store: ranked_segments[{start, end, score, text}]
```

### Phase B — External Engine Integration (Optional)

```
B1. ai-clips-maker adapter
    [FLAG: AI_CLIPS_MAKER_ENABLED=True]
    ⚠️ ADAPTER NOT FOUND — flag exists but no code implements it
    → Falls through to internal viral_gate segmentation

B2. ClipsAI adapter
    [FLAG: CLIPSAI_ENABLED=True]
    ⚠️ ADAPTER NOT FOUND — flag exists but no code implements it
    → Falls through to native pipeline

B3. ShortsHighlightEngine
    [FLAG: SHORTS_ENGINE_ENABLED=True]
    [creative_pipeline.py ~line 409]
    ├── Calls find_highlights(transcript, num_clips=6)
    │   ├── LLM (Groq) → highlight candidates with scores
    │   └── Score fusion with existing segments
    ├── Returns List[Highlight] sorted by score
    └── [METRICS] engine_shorts_engine event recorded

B4. Segment selection (final)
    [_processor_mixin.py ~line 600]
    ├── Merge: viral_gate segments + ShortsEngine highlights
    ├── Deduplicate overlapping segments
    ├── Limit to num_clips (default 6)
    └── For each segment: extract clip via FFmpeg (trim)
```

### Phase C — Creative Pipeline (per segment, 8 steps)

```
For each selected segment:

C1. Silence removal
    [creative_pipeline.py Step 1/8]
    ├── librosa silence detection (gaps > 1.5s)
    ├── FFmpeg: remove silences, re-concatenate
    └── [FLAG] SILENCE_THRESHOLD_SECONDS=0.4

C2. Caption/subtitle burn-in
    [creative_pipeline.py Step 2/8]
    ├── [FLAG] CAPTION_BACKEND=auto_subtitle
    │   ├── AutoSubtitleBackend.generate()
    │   │   ├── Whisper re-transcribe (if needed)
    │   │   ├── Generate SRT with confidence-based styling
    │   │   └── FFmpeg burn-in via subtitles filter
    │   └── Fallback: legacy caption_service (drawtext)
    └── [METRICS] export_preset_used event

C3. Hook visual analysis
    [creative_pipeline.py Step 3/8]
    ├── Identify hook sentence (first 3s of segment)
    ├── HookRewriterAgent → rewrite for max impact
    ├── HookVisualService → generate visual hook overlay
    │   ├── Slow-motion intro (if HOOK_SLOWMO_ENABLED)
    │   └── Text overlay with hook sentence
    └── [FLAG] HOOK_SLOWMO_ENABLED=false (default)

C4. Face autocrop / Impact zoom
    [creative_pipeline.py Step 4/8]
    ├── ⚠️ FaceAutocropService — NO FEATURE FLAG
    │   ├── OpenCV face detection (Haar cascade)
    │   ├── Moving-average trajectory smoothing
    │   └── FFmpeg crop filter with time-varying x(t):y(t)
    ├── ImpactZoomService — applied AFTER autocrop
    │   ├── Zoom punch at emphasis word timestamps
    │   └── Ken Burns effect when no emphasis words
    └── ⚠️ CONFLICT: face_autocrop + impact_zoom both modify crop
        → face_autocrop sets crop window, impact_zoom adds zoom
        → They compose (crop then zoom) but can produce jitter

C4.5 Shorts Engine crop hints
    [creative_pipeline.py Step 4.5/8]
    ├── [FLAG] SHORTS_ENGINE_ENABLED=True
    ├── compute_crop_for_highlight() → CropInfo
    └── Passed to FaceAutocropService as hint

C5. B-roll overlay
    [creative_pipeline.py Step 5/8]
    ├── [FLAG] AI_BROLL_ENABLED=True
    │   ├── AiBrollRecommender.suggest_broll()
    │   │   ├── LLM (Groq) → visual keywords
    │   │   └── Fallback: TF-IDF keyword extraction
    │   └── [METRICS] broll_ai_used / broll_fallback
    ├── [FLAG] SHORT_VIDEO_MAKER_PEXELS_ENABLED=True
    │   ├── PexelsClient.search_videos() → download clips
    │   │   ⚠️ FLAG DEFINED BUT NOT ENFORCED AT CALL SITE
    │   └── [METRICS] broll_pexels_result
    ├── BrollService.compose_overlay()
    │   ├── Detect silence gaps in segment audio
    │   ├── Insert B-roll at silence timestamps (fade in/out)
    │   └── FFmpeg overlay filter
    └── [METRICS] broll_service_result

C5.5 Contextual overlays
    [creative_pipeline.py Step 5.5/8]
    ├── ContextualOverlayEngine
    │   ├── Speaker bubble overlay (PiP)
    │   ├── Keyword-based image overlays
    │   └── Adaptive frequency based on virality score
    └── [FLAG] CONTEXTUAL_OVERLAYS_ENABLED=true

C6. Video effects (zoom + color grade)
    [creative_pipeline.py Step 6/8]
    ├── apply_preset_effects()
    │   ├── Zoom punch (at emphasis word timestamps)
    │   ├── Color grading (eq + unsharp)
    │   ├── Vignette
    │   ├── Pattern interrupts (micro-zoom every 12s)
    │   └── Lower thirds (animated speaker/topic text)
    └── ⚠️ CONFLICT: Step C4 (face_autocrop + impact_zoom) + Step C6 (zoom_punch)
        → Three zoom/crop mechanisms applied sequentially
        → face_autocrop → impact_zoom → zoom_punch
        → Risk of over-zooming or conflicting crop windows

C6.5 Speed control
    [creative_pipeline.py Step 6.5/8]
    ├── SpeedControlService
    │   ├── Playback speed adjustment
    │   └── Dramatic slow-motion on hook
    └── [FLAG] SPEED_CONTROL_ENABLED=true

C6.5 SFX Orchestrator
    [creative_pipeline.py Step 6.5/8]
    ├── SFXOrchestrator
    │   ├── Freesound API → download SFX
    │   ├── LLM → semantic SFX matching
    │   └── FFmpeg: mix SFX at jump cut timestamps
    └── [FLAG] SFX_ENABLED=false (default)

C7. Audio mastering
    [creative_pipeline.py Step 7/8]
    ├── SmartAudio.master()
    │   ├── Loudnorm → -14 LUFS
    │   ├── Background music mix
    │   │   └── [FLAG] BACKGROUND_MUSIC_ENABLED=True
    │   │       ├── BackgroundMusicService.search_music()
    │   │       │   └── [METRICS] music_background
    │   │       └── Fallback: no music
    │   └── SFX injection
    ├── Audio ducking (if word timings available)
    │   └── AudioDuckingService → voice-aware volume
    └── [METRICS] loudnorm_applied, audio_ducking_applied

C8. QA + render manifest
    [creative_pipeline.py Step 8/8]
    ├── LearningLoop.post_render_analysis()
    │   ├── Validate output file (exists, non-zero)
    │   ├── Check creative_enhanced flag (>=2 creative steps)
    │   └── Store manifest for future optimization
    └── [METRICS] qa_passed, qa_issues
```

### Phase D — Editlist & Export

```
D1. Editlist backend (optional)
    [FLAG: EDITLIST_ENABLED=True]
    ├── EditlistService.apply()
    │   ├── [FLAG] EDITLIST_ENABLE_CUTS=True → trim/split/concat
    │   ├── [FLAG] EDITLIST_ENABLE_OVERLAYS=True → PiP, split-screen
    │   └── [FLAG] EDITLIST_ENABLE_TRANSITIONS=True → crossfade, slide
    └── Fallback: legacy FFmpeg command construction

D2. Export preset
    [FLAG: EXPORT_PRESET=tiktok_basic]
    ├── ExportPresetService.export_with_preset()
    │   ├── Try tiktok_basic (9:16, 30fps, AAC 128k)
    │   ├── Fallback: fast_vertical (veryfast, crf 21)
    │   └── Final fallback: return original input
    └── [METRICS] export_preset_used / export_preset_fallback

D3. Output
    ├── Write final clip → /tmp/viraclip/outputs/{task_id}/{clip_index}.mp4
    ├── Generate thumbnail
    └── Update task status → completed
```

---

## 3. Overlap & Redundancy Detection

### 🔴 CONFLICT 1: Triple Zoom/Crop Stack

Three separate mechanisms modify the crop window sequentially:

| Step | Service | What it does |
|------|---------|-------------|
| C4 | FaceAutocropService | Sets crop window based on face tracking |
| C4 | ImpactZoomService | Adds zoom punch at emphasis words |
| C6 | apply_preset_effects | Adds zoom_punch + Ken Burns |

**Problem:** Face autocrop sets a crop window, then impact zoom adds a zoom factor, then zoom_punch adds another zoom. These compose via FFmpeg filter chains but can produce:
- Over-zooming (crop 1.2x × zoom 1.12x × punch 1.15x = 1.54x total)
- Conflicting trajectories (face tracking vs. emphasis word zoom)
- Jitter from competing smoothings

**Recommendation:** Disable ImpactZoomService when FaceAutocropService is active, or merge them into a single crop decision.

### 🟡 CONFLICT 2: Captions vs. Hook vs. Overlays Text

Three text overlay mechanisms:

| Step | Service | Text type |
|------|---------|-----------|
| C2 | CaptionService / AutoSubtitleBackend | Word-by-word subtitles (bottom) |
| C3 | HookVisualService | Hook sentence overlay (center/top) |
| C5.5 | ContextualOverlayEngine | Keyword overlays, speaker bubble |

**Problem:** Hook text and captions can overlap visually. Contextual overlays may cover captions.

**Recommendation:** Ensure hook text is positioned above captions (y < 30%) and contextual overlays avoid the bottom 30% of the frame.

### 🟡 CONFLICT 3: B-roll vs. Transitions

| Step | Service | What it does |
|------|---------|-------------|
| C5 | BrollService | Inserts B-roll clips at silence gaps (fade in/out) |
| D1 | EditlistService | Applies transitions between clips (crossfade, slide) |

**Problem:** B-roll is inserted as an overlay on the main clip, not as a separate clip. Transitions apply between main clips. If B-roll is inserted at a cut point, the transition may conflict with the B-roll fade.

**Recommendation:** B-roll should be applied AFTER transitions, or transitions should be aware of B-roll insertion points.

### ✅ NO CONFLICT: Audio Chain

The audio processing chain is well-ordered:
1. Silence removal (C1) → removes gaps
2. B-roll audio ducking (C5) → lowers B-roll volume during speech
3. Audio mastering (C7) → loudnorm + music mix + SFX
4. Audio ducking (C7) → voice-aware volume adjustment

Each step operates on the output of the previous step. No conflicts.

---

## 4. Observations by Step

| Step | Status | Notes |
|------|--------|-------|
| A1-A5 | ✅ | Well-structured preflight |
| B1 | ❌ | ai-clips-maker adapter missing |
| B2 | ❌ | ClipsAI adapter missing |
| B3 | ✅ | ShortsEngine works, guarded by flag |
| C1 | ✅ | Silence removal, stable |
| C2 | ⚠️ | CAPTION_BACKEND routing not enforced at call site |
| C3 | ✅ | Hook visual, guarded by flag |
| C4 | ❌ | FaceAutocropService has NO flag |
| C4.5 | ✅ | ShortsEngine crop hints, guarded |
| C5 | ⚠️ | PexelsClient flag not enforced at call site |
| C5.5 | ✅ | Contextual overlays, guarded |
| C6 | ⚠️ | Triple zoom/crop conflict risk |
| C6.5 | ✅ | Speed control, guarded |
| C7 | ✅ | Audio mastering, well-ordered |
| C8 | ✅ | QA + manifest |
| D1 | ✅ | Editlist, well-structured phases |
| D2 | ✅ | Export preset, excellent fallback chain |

---

## 5. Recommended Corrections (Before Public Testing)

### High Priority
1. **Fix triple zoom/crop conflict** — Disable ImpactZoomService when FaceAutocropService is active. Add `FACE_AUTOCROP_ENABLED` flag.
2. **Add missing adapter files** — Create or remove flags for ai-clips-maker, ClipsAI, FacelessClipGenerator.
3. **Enforce PexelsClient flag** — Add `SHORT_VIDEO_MAKER_PEXELS_ENABLED` check at the call site in broll_service.py.

### Medium Priority
4. **Add CAPTION_BACKEND routing check** — Ensure the caption pipeline checks the flag before delegating to AutoSubtitleBackend.
5. **Prevent text overlap** — Ensure hook text, captions, and contextual overlays have non-overlapping vertical positions.
6. **B-roll + transition ordering** — Document that B-roll should be applied after transitions, or skip transitions when B-roll is active.

### Low Priority
7. **Standardize flag checking** — Use `get_config()` instead of `os.environ.get()` for BACKGROUND_MUSIC_ENABLED.
8. **Add metrics_aggregator unit tests** — Currently no test coverage for the metrics module.
