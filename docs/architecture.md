# ViraClip — Architecture Deep-Dive

## Overview

ViraClip is a self-hostable SaaS platform that converts long-form video into viral short-form clips. The system is designed around an async, event-driven pipeline with a clear separation between ingestion, AI processing, rendering, and distribution.

```
┌─────────────────────────────────────────────────────────────────┐
│                         User / API Client                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │  HTTP / SSE
┌─────────────────────────────▼───────────────────────────────────┐
│                   FastAPI Backend  (:8000)                        │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────────────┐ │
│  │   REST API │  │  SSE Events  │  │  Auth (better-auth)       │ │
│  └────────────┘  └──────────────┘  └──────────────────────────┘ │
└─────────────┬───────────────────────────┬───────────────────────┘
              │ Enqueue task               │ Read/Write
┌─────────────▼──────────┐   ┌────────────▼───────────────────────┐
│   Redis (arq queue)     │   │   PostgreSQL (persistent state)     │
└─────────────┬──────────┘   └────────────────────────────────────┘
              │ Dequeue
┌─────────────▼──────────────────────────────────────────────────┐
│                    arq Worker  (async)                           │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    coordinator.py                         │   │
│  │                                                           │   │
│  │  cache/preflight → parallel analysis → viral gate        │   │
│  │       → segment scoring → creative pipeline              │   │
│  │       → parallel render → post-render gate               │   │
│  │       → export/finalization                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                  │
│  External services called during render:                         │
│  • Whisper / AssemblyAI  (transcription)                         │
│  • Groq / OpenAI / Gemini  (LLM scoring, hooks, captions)        │
│  • Pexels API  (stock B-roll)                                     │
│  • ComfyUI  (:8188, generative B-roll via LTXV)                  │
│  • ElevenLabs / Suno  (AI audio, optional)                       │
└─────────────────────────────────────────────────────────────────┘
              │
┌─────────────▼──────────────────────────────────────────────────┐
│               Export / Storage / Distribution                    │
│   • Local disk  (exports/)                                       │
│   • AWS S3 / Cloudflare R2  (cloud storage)                      │
│   • CDN edge  (clip delivery)                                     │
│   • TikTok / Instagram / YouTube  (publishing, Phase 3)          │
└─────────────────────────────────────────────────────────────────┘
```

---

## Pipeline Phases

The coordinator (`backend/src/services/coordinator.py`) structures the pipeline into sequential phases with gates that can abort early:

| Phase | Key Services | Gate |
|---|---|---|
| **1. Cache / Preflight** | `cache_checker`, `preflight_gate` | Abort if already processed or material fails basic checks |
| **2. Parallel Analysis** | `VideoService.generate_transcript`, `vision_service.analyze_clip_visually` | — |
| **3. Viral Gate** | LLM via Groq, `VIRAL_SCORER_SYSTEM_PROMPT` | Abort if no segments pass virality threshold |
| **4. Segment Scoring** | `get_validated_segments`, `build_dynamic_user_prompt` | — |
| **5. Scene Refinement** | `scene_aware_segmenter` | Optional — aligns cuts to visual scene boundaries |
| **6. Creative Pipeline** | `langgraph_pipeline` | Enriches each segment: hook, edit decisions, audio, captions, quality score |
| **7. Parallel Render** | `_parallel_rendering` → per-clip sub-pipeline | — |
| **8. Post-render Gate** | Duration + quality validation | Drop clips that fail output checks |
| **9. Export / Finalization** | `export_service`, `cdn_service`, `clip_share_link_service` | — |

### Per-Clip Sub-Pipeline

Each clip runs its own enrichment chain inside `_parallel_rendering`:

```
clip_validator
  → VideoService.create_single_clip
  → beat_sync_service
  → creative_pipeline
  → caption_service  (ASS subtitles)
  → hook_visual_service
  → lut_service
  → smart_auto_editor
  → timeline (optional)
  → emoji_overlay_service
  → variant_generator (A/B variants)
  → transition_service
  → audio_ducking_service
  → cta_service
  → brand_overlay_service
  → audio_denoiser
  → cut_zoom_service
  → language_detection
  → clip_health_service
  → metadata persistence
```

---

## Domain Structure

The backend is organized by **business domain**, not by technical layer:

```
backend/src/domains/
├── ai/           # LLMs, vision analysis, editorial scoring
├── audio/        # BGM, SFX, voice enhancement, beat sync, ducking
├── broll/        # Stock (Pexels) + generative (ComfyUI) B-roll
├── captions/     # ASS subtitles, translation, word-level timing
├── detection/    # CV, face tracking, scene detection
├── video/        # Core clip rendering, FFmpeg orchestration
├── virality/     # Segment scoring, hook generation, ML models
├── publishing/   # Social platform OAuth, post scheduling
├── billing/      # Stripe subscriptions, usage metering
├── analytics/    # Engagement metrics, feedback loops, ML virality predictor
└── platform/     # Auth, teams, collaboration, notifications
```

---

## Key Design Decisions

### Async-first with `asyncio.gather`
All parallelizable work (transcript + vision analysis, multi-clip rendering) runs concurrently via `asyncio.gather`. This means a 10-clip job renders all clips in parallel rather than sequentially.

### Smart caching before heavy compute
Before invoking Whisper or any LLM, the system checks `cache_checker` for existing transcripts/analysis. Re-uploads of the same video cost near-zero compute.

### LangGraph for creative enrichment
`langgraph_pipeline` uses a multi-agent graph to produce structured decisions per segment (hook type, edit style, caption preset, quality warnings). Results above a quality threshold are stored in `rag_memory` as winning patterns for future jobs.

### Graceful degradation
Every service wraps its FFmpeg calls and external API calls in try/except with explicit fallbacks. A failed B-roll fetch falls back to no B-roll; a failed music mix falls back to the original audio. The pipeline never hard-crashes on a single service failure.

---

## Infrastructure

| Service | Image | Port |
|---|---|---|
| `frontend` | Next.js 15 | 3000 |
| `backend` | FastAPI + uvicorn | 8000 |
| `worker` | arq async worker | — |
| `postgres` | PostgreSQL 16 | 5432 |
| `redis` | Redis 7 | 6379 |
| `comfyui` | ComfyUI + CUDA | 8188 |
| `watchdog` | Health monitor | — |
| `diagnostic` | System diagnostics | — |

All services are defined in `docker-compose.yml`. Local development overrides (volume mounts, debug ports) live in `docker-compose.override.yml`.

---

## Data Flow: Video → Clips

```
1. User uploads video or pastes YouTube URL
2. yt-dlp downloads / file is stored in uploads/
3. Task enqueued to Redis via arq
4. Worker picks up task → coordinator.py takes over
5. Whisper transcribes → word-level timestamps in DB
6. LLM scores every 15-60s segment for virality (0-100)
7. Top N segments selected (viral_gate filters the rest)
8. Each segment rendered to 9:16 vertical clip with:
   - Smart crop / face tracking
   - Hook visual (first 3s)
   - ASS subtitles burned in
   - B-roll inserted at scene breaks
   - Beat-synced BGM mixed at -12dB under voice
   - LUT color grade applied
9. Clips exported to exports/ and optionally uploaded to S3/R2
10. Frontend polls via SSE for progress events
11. User downloads or schedules publishing
```

---

For local setup: [`docs/development.md`](development.md)  
For production deployment: [`DEPLOY_GUIDE.md`](../DEPLOY_GUIDE.md)  
For configuration reference: [`docs/configuration.md`](configuration.md)
