# VPI Production Baseline

Baseline date: 2026-06-14

This document freezes the current VPI production behavior after OUTPUT-TIMELINE-25. It is a functional internal-production baseline, not a feature expansion target.

## Active Functions

- Editorial segment selection with narrative opening and closure constraints.
- Opening planner for clean, context-complete starts.
- Closure planner for complete final ideas and contained endings.
- Retake/disfluency cuts with physical cut application.
- Silence editing with dead-air reduction, compression, preservation of useful pauses, and conservative silence punctuation.
- Caption contract after trims/cuts, with synchronized ASS captions.
- Local full-frame B-roll when a compatible local asset exists.
- Internal editorial visual fallback cards when B-roll is unavailable and the intent is clear.
- Semantic icon mapping for visual fallback cards.
- Editorial SFX for visual transitions, payoff/risk moments, and strict silence punctuation cases.
- Deterministic SFX variation and task-local anti-repetition.
- Final timeline gate reconciling MP4 duration, audio duration, caption duration, speech coverage, and closure containment.

## Active Guards

- Typewriter/click/glitch routes remain disabled or forbidden.
- Legacy `smart_audio` remains disabled.
- Editorial SFX budget remains capped: clips under 25s receive at most one event; clips 25s or longer receive at most two events; minimum spacing is 8s.
- No repeated SFX family inside a clip.
- B-roll has priority over visual fallback cards when a valid local stock cutaway exists.
- Visual support is skipped for flagged weak-opening or weak-closure clips.
- Local B-roll is full-frame cutaway only; no PiP fallback.
- Travel/student intents do not fall back to unrelated `family_relief` stock.
- Closure containment and final speech coverage gates are active.
- Audio/captions/MP4 reconciliation is active after final visual stages.
- Debug overlays are off in production mode.

## Production Flags

Observed runtime flags in `viraclip-backend`:

```text
BROLL_ENABLED=true
BROLL_ENABLE_STOCK=true
BROLL_FORCE_CPU=true
COMFYUI_ENABLED=false
CONTEXTUAL_OVERLAYS_ENABLED=true
T2V_ENABLED=false
VIRACLIP_BETA_CLEAN=true
VIRACLIP_ENABLE_EDITORIAL_BROLL=true
VIRACLIP_ENABLE_PREMIUM_EDITING=true
VIRACLIP_MODE=premium_productive
VPI_DAILY_MODE=true
VPI_DAILY_MODE_ALLOW_UNSAFE=false
VPI_PRODUCTION_SAFE_EDIT=true
VPI_SHOW_DEBUG_OVERLAYS=false
```

Operational requirements:

- Use `include_broll=true` for daily VPI runs.
- Keep daily mode enabled.
- Keep production safe edit enabled.
- Keep debug overlays disabled.
- Do not enable ComfyUI, T2V, external B-roll providers, typewriter, click, glitch, or dual-riser during the observation period.

## Known Non-Blocking Limits

- Local B-roll stock can repeat when the compatible asset family has low variety.
- Travel currently uses `folder_paperwork` as the visual card icon because there is no dedicated travel icon.
- ASR can produce occasional cosmetic transcript errors.
- `soft_whoosh` and `soft_impact` have a single usable local variant.
- Dual-riser is intentionally not enabled.
- No external providers are used for B-roll, cards, icons, SFX, or T2V.

## Verdict

This baseline is fit for internal VPI production. Publish only after brief human QC. Do not add features during the observation phase; only fix reproducible blockers with a minimal patch, microtest, and one targeted smoke.
