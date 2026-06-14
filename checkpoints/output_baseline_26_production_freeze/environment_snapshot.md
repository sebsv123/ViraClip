# OUTPUT-BASELINE-26 Environment Snapshot

Captured: 2026-06-14

## Git

- Branch: `version-basica`
- HEAD before baseline commit: `c787e3645cbffd68b8327e57cbd5cc645e6e79ce`
- Working tree before freeze: dirty, with accumulated VPI product changes plus many historical untracked checkpoints/assets/scripts.
- Commit policy for this block: stage only production code/assets required by current baseline plus baseline docs/checkpoint text. Do not stage outputs, generated MP4s, reports, or heavy checkpoint artifacts.

## Modified / New Production Files Expected In Baseline

- `backend/src/services/task_service.py`
- `backend/src/services/video_service.py`
- `backend/src/services/vpi_asset_library_service.py`
- `backend/src/services/vpi_broll_intent.py`
- `backend/src/services/vpi_editorial_contract.py`
- `backend/src/services/vpi_music_service.py`
- `backend/src/services/vpi_silence_editor.py`
- `backend/src/services/vpi_editorial_sfx_service.py`
- `backend/src/services/vpi_final_timeline_contract.py`
- `backend/src/services/vpi_post_silence_remap.py`
- `backend/src/services/vpi_visual_fallback_service.py`
- `assets/icons/`
- `assets/lottie/`
- `assets/overlays/`

## Docker Services

```text
NAMES               STATUS                    IMAGE
viraclip-frontend   Up 32 hours (healthy)     viraclip-frontend
viraclip-worker     Up 30 minutes (healthy)   viraclip-worker
viraclip-backend    Up 32 hours (healthy)     viraclip-backend
viraclip-postgres   Up 4 days (healthy)       postgres:16-alpine
viraclip-redis      Up 4 days (healthy)       redis:7-alpine
```

## Runtime Versions

- FFmpeg: `ffmpeg version n8.1.1`
- Host Python: `Python 3.14.5`
- Backend test runtime: container `/app/.venv/bin/python3`

## Production Flags Observed

```text
BROLL_ENABLED=true
BROLL_ENABLE_PREMIUM=false
BROLL_ENABLE_STOCK=true
BROLL_FORCE_CPU=true
BROLL_PROVIDER_PRIORITY=stock_first
COMFYUI_ENABLED=false
CONTEXTUAL_OVERLAYS_ENABLED=true
FREESOUND_SFX_ENABLED=true
SFX_LIBRARY_PATH=/app/assets/sounds
T2V_ENABLED=false
VIRACLIP_BETA_CLEAN=true
VIRACLIP_DEADLINE_SAFE_MODE=false
VIRACLIP_EDITORIAL_QC_BLOCKING=false
VIRACLIP_ENABLE_EDITORIAL_BROLL=true
VIRACLIP_ENABLE_NVENC=true
VIRACLIP_ENABLE_PREMIUM_EDITING=true
VIRACLIP_ENABLE_TORCH_CUDA=true
VIRACLIP_GPU_PROBE_ON_START=true
VIRACLIP_MODE=premium_productive
VPI_DAILY_MODE=true
VPI_DAILY_MODE_ALLOW_UNSAFE=false
VPI_PRODUCTION_SAFE_EDIT=true
VPI_SHOW_DEBUG_OVERLAYS=false
WHISPER_COMPUTE_TYPE=float16
WHISPER_DEVICE=cuda
WHISPER_MODEL_SIZE=small
```

## GPU / CPU Notes

- Container advertises CUDA 12.8 runtime variables and `WHISPER_DEVICE=cuda`.
- Test execution emitted a CUDA initialization warning and continued; current validated path tolerates CPU fallback for local editorial features.
- `BROLL_FORCE_CPU=true` keeps local B-roll processing on the safe CPU route.

## Existing Test Suites Used

- `py_compile` for production services and existing harnesses.
- TIMELINE-25 canonical keep segments.
- TIMELINE-24 post-silence remap.
- TIMELINE-23 final duration reconciliation.
- SFX-19 payoff/risk policy.
- VISUALS-17 semantic icon mapping.
- VISUALS-16 icon/object polish.
- BROLL-14 asset intake safety.
- BROLL-13 visual polish.
- NARRATIVE-9 closure planner.
- OUTPUT-SELECTION-5B caption contract.
