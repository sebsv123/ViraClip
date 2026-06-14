# VPI Daily Production Checklist

Target QC time: under 2 minutes per clip.

## Before Running

- Docker services are healthy.
- Worker is ready.
- Frontend returns 200.
- `include_broll=true`.
- Source video is the intended source.
- Daily mode and production-safe edit are enabled.
- Debug overlays are off.

## After Rendering

- Opening is complete and starts cleanly.
- Closing idea is complete; final phrase is not cut.
- Captions are visible, legible, and synchronized.
- Voice remains dominant.
- Music is present but not masking voice.
- Visual support is semantic: local B-roll or fallback card/icon when useful.
- SFX count is controlled: normally 1, maximum 2 for longer clips.
- No click, typewriter, glitch, or cheap repetitive punctuation.
- Timeline gate passes.
- Frontend task page loads and downloads/plays the MP4.

## Verdict

- `PUBLICABLE`: publish after normal review.
- `CASI_PUBLICABLE`: usable with caution or minor human judgement.
- `RECHAZAR`: do not publish; document the blocker and reproduce before changing code.
