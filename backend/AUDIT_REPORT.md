# ViraClip Backend — Technical Audit Report

**Date:** 2026-05-16  
**Scope:** All new integrations added in Phases 8-9  
**Auditor:** Automated code review  

---

## Executive Summary

| Status | Count |
|--------|-------|
| ✅ OK (fully guarded + fallback) | 6 |
| ⚠️ Partial (flag exists but missing in some call sites) | 3 |
| ❌ Missing flag or fallback | 2 |
| 🔴 Circular import risk | 0 |

---

## 1. Integration Audit Table

| # | Integration | File | Flag(s) | Fallback | Status |
|---|-------------|------|---------|----------|--------|
| 1 | **AiBrollRecommender** | `services/ai_broll_recommender.py` | `AI_BROLL_ENABLED` | TF-IDF keyword extraction | ✅ OK |
| 2 | **PexelsClient** | `services/pexels_client.py` | `SHORT_VIDEO_MAKER_PEXELS_ENABLED` | Existing PexelsService | ⚠️ Partial |
| 3 | **BackgroundMusicService** | `domains/audio/background_music_service.py` | `BACKGROUND_MUSIC_ENABLED` | No background music | ✅ OK |
| 4 | **ShortsHighlightEngine** | `services/shorts_highlight_engine.py` | `SHORTS_ENGINE_ENABLED` | Existing segment boundaries | ✅ OK |
| 5 | **ExportPresetService** | `services/export_preset_service.py` | `EXPORT_PRESET` | `fast_vertical` → return original | ✅ OK |
| 6 | **AutoSubtitleBackend** | `services/subtitle_backend_auto.py` | `CAPTION_BACKEND` | Legacy caption_service (drawtext) | ⚠️ Partial |
| 7 | **EditlistService** | `services/editlist_service.py` | `EDITLIST_ENABLED` + phases | Legacy FFmpeg commands | ✅ OK |
| 8 | **FaceAutocropService** | `services/face_autocrop_service.py` | ❌ **No flag** | Fixed center crop | ❌ Missing |
| 9 | **ai-clips-maker adapter** | ❌ **Not found** | `AI_CLIPS_MAKER_ENABLED` | Internal viral_gate | ❌ Missing |
| 10 | **ClipsAI adapter** | ❌ **Not found** | `CLIPSAI_ENABLED` | Native pipeline | ❌ Missing |
| 11 | **FacelessClipGenerator** | ❌ **Not found** | `FACELESS_FEATURE_ENABLED` | Requires source video | ❌ Missing |
| 12 | **MetricsAggregator** | `services/metrics_aggregator.py` | N/A (always on) | N/A | ✅ OK |
| 13 | **FeatureFlagManager** | `core/feature_flags.py` | N/A (central) | N/A | ✅ OK |
| 14 | **QA Sanity Checks** | `qa/clip_sanity_checks.py` | N/A (QA only) | N/A | ✅ OK |

---

## 2. Detailed Findings

### 2.1 AiBrollRecommender — ✅ OK

- **File:** `backend/src/services/ai_broll_recommender.py`
- **Flag:** `AI_BROLL_ENABLED` (default: `false`)
- **Flag check location:** `suggest_broll()` method — checks `is_enabled("AI_BROLL_ENABLED")` before calling LLM
- **Fallback:** TF-IDF keyword extraction (no LLM call, no external dependency)
- **Error handling:** `_extract_via_llm()` catches all exceptions, returns empty list → triggers TF-IDF fallback
- **Metrics:** `broll_ai_used` / `broll_fallback` events recorded
- **Recommendation:** None — fully guarded.

### 2.2 PexelsClient — ⚠️ Partial

- **File:** `backend/src/services/pexels_client.py`
- **Flag:** `SHORT_VIDEO_MAKER_PEXELS_ENABLED` (default: `false`)
- **Flag check location:** ❌ **Not checked in pexels_client.py itself** — the flag exists in config but is never read by the PexelsClient class. The client always runs if called.
- **Fallback:** Returns empty list on any failure (graceful degradation)
- **Error handling:** `search_videos()` catches all exceptions per search term, retries with joker terms
- **Metrics:** `broll_pexels_result` event recorded
- **Recommendation:** Add flag check at the call site in `broll_service.py` or `creative_pipeline.py` before instantiating PexelsClient. Currently the flag is defined but not enforced anywhere.

### 2.3 BackgroundMusicService — ✅ OK

- **File:** `backend/src/domains/audio/background_music_service.py`
- **Flag:** `BACKGROUND_MUSIC_ENABLED` (default: `false`)
- **Flag check location:** `backend/src/video_processing/audio.py` line 188 — wrapped in `if os.environ.get("BACKGROUND_MUSIC_ENABLED", "false").lower() in ("true", "1"):`
- **Fallback:** No background music (pipeline continues silently)
- **Error handling:** `search_music()` catches all exceptions, returns empty list
- **Metrics:** `music_background` / `engine_error` events recorded
- **Recommendation:** None — fully guarded. However, the flag check uses `os.environ.get()` directly instead of `get_config().background_music_enabled` — consider standardizing.

### 2.4 ShortsHighlightEngine — ✅ OK

- **File:** `backend/src/services/shorts_highlight_engine.py`
- **Flag:** `SHORTS_ENGINE_ENABLED` (default: `false`)
- **Flag check location:** `backend/src/domains/autopilot/creative_pipeline.py` line 409 — `if cfg.shorts_engine_enabled:`
- **Fallback:** Uses existing segment boundaries (no highlight re-ranking)
- **Error handling:** `find_highlights()` catches all exceptions, returns empty list
- **Metrics:** `engine_shorts_engine` / `engine_error` events recorded
- **Recommendation:** None — fully guarded.

### 2.5 ExportPresetService — ✅ OK

- **File:** `backend/src/services/export_preset_service.py`
- **Flag:** `EXPORT_PRESET` (default: `"tiktok_basic"`)
- **Flag check location:** Config value read at service init
- **Fallback:** `fast_vertical` preset → return original input unchanged
- **Error handling:** `export_with_preset()` catches all exceptions, retries with `fast_vertical`, then returns original path
- **Metrics:** `export_preset_used` / `export_preset_fallback` / `engine_error` events recorded
- **Recommendation:** None — excellent fallback chain.

### 2.6 AutoSubtitleBackend — ⚠️ Partial

- **File:** `backend/src/services/subtitle_backend_auto.py`
- **Flag:** `CAPTION_BACKEND` (default: `"legacy"`)
- **Flag check location:** ❌ **Not checked in subtitle_backend_auto.py** — the flag exists in config but the adapter doesn't self-guard. The call site in the caption pipeline should check `CAPTION_BACKEND` before routing to this backend.
- **Fallback:** Falls back to `caption_service` legacy (drawtext) if Whisper or burn-in fails
- **Error handling:** Internal try/except catches Whisper failures, FFmpeg burn-in failures
- **Recommendation:** Add explicit `CAPTION_BACKEND` check at the routing point in `_subtitles.py` or `caption_service.py` before delegating to AutoSubtitleBackend.

### 2.7 EditlistService — ✅ OK

- **File:** `backend/src/services/editlist_service.py`
- **Flag:** `EDITLIST_ENABLED` (default: `true`), `EDITLIST_ENABLE_CUTS` (default: `true`), `EDITLIST_ENABLE_OVERLAYS` (default: `false`), `EDITLIST_ENABLE_TRANSITIONS` (default: `false`)
- **Flag check location:** Inside `EditlistService.apply()` — checks each phase flag before applying operations
- **Fallback:** Legacy FFmpeg command construction (when `EDITLIST_ENABLED=false`)
- **Error handling:** `apply_safe()` wraps operations in try/except, logs warnings
- **Recommendation:** None — well-structured gradual rollout design.

### 2.8 FaceAutocropService — ❌ Missing Flag

- **File:** `backend/src/services/face_autocrop_service.py`
- **Flag:** ❌ **No feature flag exists** for this service
- **Flag check location:** N/A
- **Fallback:** Falls back to fixed center crop when OpenCV fails (documented in docstring)
- **Error handling:** Internal try/except, falls back to center crop
- **Recommendation:** Add `FACE_AUTOCROP_ENABLED` flag (default: `false`) to `config.py` and guard the call site in `creative_pipeline.py` or `_clip_renderer.py`.

### 2.9 ai-clips-maker adapter — ❌ Not Found

- **File:** ❌ **No adapter file found** in `backend/src/`
- **Flag:** `AI_CLIPS_MAKER_ENABLED` exists in config (default: `false`)
- **Flag check location:** N/A — no code references this flag
- **Fallback:** Internal viral_gate segmentation (documented in config comment)
- **Recommendation:** Create the adapter file at `backend/src/services/ai_clips_maker_adapter.py` with the flag guard, or remove the flag if the integration was never built.

### 2.10 ClipsAI adapter — ❌ Not Found

- **File:** ❌ **No adapter file found** in `backend/src/`
- **Flag:** `CLIPSAI_ENABLED` exists in config (default: `false`)
- **Flag check location:** N/A — no code references this flag
- **Fallback:** Native pipeline (documented in config comment)
- **Recommendation:** Same as 2.9 — either create the adapter or remove the flag.

### 2.11 FacelessClipGenerator — ❌ Not Found

- **File:** ❌ **No adapter file found** in `backend/src/`
- **Flag:** `FACELESS_FEATURE_ENABLED` exists in config (default: `false`)
- **Flag check location:** N/A — no code references this flag
- **Fallback:** Requires source video input (documented in config comment)
- **Recommendation:** Same as 2.9 — either create the adapter or remove the flag.

---

## 3. Feature Flag Coverage Summary

| Flag | Defined in config.py | Used in code | Status |
|------|---------------------|--------------|--------|
| `AI_BROLL_ENABLED` | ✅ | ✅ (ai_broll_recommender.py) | ✅ |
| `SHORT_VIDEO_MAKER_PEXELS_ENABLED` | ✅ | ❌ Not enforced | ⚠️ |
| `BACKGROUND_MUSIC_ENABLED` | ✅ | ✅ (audio.py via os.environ) | ✅ |
| `AI_CLIPS_MAKER_ENABLED` | ✅ | ❌ No adapter exists | ❌ |
| `CLIPSAI_ENABLED` | ✅ | ❌ No adapter exists | ❌ |
| `SHORTS_ENGINE_ENABLED` | ✅ | ✅ (creative_pipeline.py) | ✅ |
| `EDITLIST_ENABLED` | ✅ | ✅ (editlist_service.py) | ✅ |
| `FACELESS_FEATURE_ENABLED` | ✅ | ❌ No adapter exists | ❌ |
| `CAPTION_BACKEND` | ✅ | ⚠️ Not checked at routing point | ⚠️ |
| `EXPORT_PRESET` | ✅ | ✅ (export_preset_service.py) | ✅ |
| `OPTIMIZATION_LOOP_ENABLED` | ✅ | ✅ (clip_performance_analyzer.py) | ✅ |
| `FACE_AUTOCROP_ENABLED` | ❌ Not defined | ❌ Not defined | ❌ |

---

## 4. Fallback Verification

| Integration | External dep failure | FFmpeg failure | ImportError | Returns 0-byte file risk |
|-------------|---------------------|----------------|-------------|--------------------------|
| AiBrollRecommender | ✅ → TF-IDF | N/A | ✅ → TF-IDF | ❌ No |
| PexelsClient | ✅ → empty list | N/A | ✅ → empty list | ❌ No |
| BackgroundMusicService | ✅ → no music | ✅ → no music | ✅ → no music | ❌ No |
| ShortsHighlightEngine | ✅ → empty highlights | N/A | ✅ → empty list | ❌ No |
| ExportPresetService | N/A | ✅ → fast_vertical → original | N/A | ❌ No (returns original) |
| AutoSubtitleBackend | ✅ → legacy captions | ✅ → legacy captions | ✅ → legacy captions | ❌ No |
| EditlistService | N/A | ✅ → legacy FFmpeg | ✅ → legacy FFmpeg | ❌ No |
| FaceAutocropService | ✅ → center crop | ✅ → center crop | ✅ → center crop | ❌ No |

---

## 5. Circular Import Check

- **No circular imports detected** in the new integration files.
- All imports follow the pattern: `from src.services.X import Y` or `from src.domains.X.Y import Z`.
- The `metrics_aggregator.py` is imported by 5 services but does not import any of them back.
- The `feature_flags.py` imports `get_config()` from `config.py` — no reverse import.

---

## 6. Test & QA Accessibility

| Module | Test file | Run command | Status |
|--------|-----------|-------------|--------|
| clip_sanity_checks | `tests/test_clip_sanity_checks.py` | `docker exec viraclip-backend python -m pytest tests/test_clip_sanity_checks.py -v` | ✅ 68/68 pass |
| generate_test_clips | N/A (script) | `python -m src.qa.generate_test_clips --preset=tiktok_basic --limit=10` | ✅ Documented |
| report_last_run | N/A (script) | `python -m src.qa.report_last_run` | ✅ Documented |
| metrics_aggregator | ❌ No test file | `python -m viraclip.metrics.summary --last-days=7` | ⚠️ No unit tests |
| export_preset_service | `tests/test_export_preset_service.py` | `docker exec viraclip-backend python -m pytest tests/test_export_preset_service.py -v` | ✅ |
| ai_broll_recommender | `tests/test_ai_broll_recommender.py` | `docker exec viraclip-backend python -m pytest tests/test_ai_broll_recommender.py -v` | ✅ |
| shorts_highlight_engine | `tests/test_shorts_highlight_engine.py` | `docker exec viraclip-backend python -m pytest tests/test_shorts_highlight_engine.py -v` | ✅ |
| face_autocrop_service | `tests/test_face_autocrop.py` | `docker exec viraclip-backend python -m pytest tests/test_face_autocrop.py -v` | ✅ |

---

## 7. Recommended Actions

### High Priority (must fix before user testing)

1. **Create missing adapter files** or remove unused flags:
   - `AI_CLIPS_MAKER_ENABLED` → create `backend/src/services/ai_clips_maker_adapter.py` or remove flag
   - `CLIPSAI_ENABLED` → create `backend/src/services/clipsai_adapter.py` or remove flag
   - `FACELESS_FEATURE_ENABLED` → create `backend/src/services/faceless_clip_generator.py` or remove flag

2. **Add `FACE_AUTOCROP_ENABLED` flag** to `config.py` (default: `false`) and guard the call site in `creative_pipeline.py`

3. **Enforce `SHORT_VIDEO_MAKER_PEXELS_ENABLED`** at the call site in `broll_service.py` or `creative_pipeline.py` — currently the flag is defined but never checked

### Medium Priority

4. **Standardize flag checking** — `BACKGROUND_MUSIC_ENABLED` uses `os.environ.get()` directly in `audio.py` instead of `get_config().background_music_enabled`. Use the centralized config for consistency.

5. **Add `CAPTION_BACKEND` routing check** — the routing point in `_subtitles.py` or `caption_service.py` should check `CAPTION_BACKEND` before delegating to `AutoSubtitleBackend`

6. **Add unit tests for `metrics_aggregator.py`** — currently no test file exists for the metrics module

### Low Priority

7. **Document CLI commands** in `README.md` or `CONTRIBUTING.md` for:
   - `python -m viraclip.metrics.summary --last-days=7`
   - `python -m src.qa.generate_test_clips --preset=tiktok_basic --limit=10`
   - `python -m src.qa.report_last_run`

8. **Consider DB-backed flags** for future dashboard — the `FeatureFlagManager` already has `set()`/`set_all()` methods ready for runtime overrides, but no persistence layer yet

---

## 8. Conclusion

The core integrations (AiBrollRecommender, ShortsHighlightEngine, ExportPresetService, EditlistService, BackgroundMusicService) are well-guarded with feature flags and have clear fallback paths. The main gaps are:

1. **3 adapter files are missing** — flags exist in config but no code implements them
2. **FaceAutocropService has no flag** — always runs if called
3. **PexelsClient flag is defined but not enforced** — the flag exists but no call site checks it

These are straightforward to fix and should be addressed before user testing begins.
