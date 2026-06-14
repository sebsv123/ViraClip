# VPI Reference Outputs

These are local reference outputs for human comparison. Do not copy videos into the repository.

## Best General Clip

- Task: `d2cef629-b8f0-4214-b4d3-bfa0052f15a9`
- Clip: `C0`
- Strength: balanced editorial selection, complete opening/closure, visible premium stack, captions/music/SFX preserved.
- Why it is useful: reference for overall VPI pacing and production feel.

## Travel Final Corrected

- Task: `62cf81df-eee7-47b3-ba5f-93b9c2360511`
- Pixel validation reference: `33a2b08f-974f-4636-8cfd-136c73a6acbf`
- Clip: candidate 4 / generated `clip_01`
- Strength: corrected visual fallback duration, final MP4 around 43.412s, ASS around 43.28s, closure contained, audio/caption sync OK.
- Features visible: clean opening, visual card support, semantic icon, captions, music, editorial SFX, final timeline gate.
- Why it is useful: reference for the exact root cause fixed in OUTPUT-TIMELINE-25: icon loop no longer truncates video.

## Salud / Decesos

- Task: `d8001582-1632-434e-9bfc-3afb28a90f38`
- Clip: generated clips 1-2
- Strength: silence treatment, sensitive-content restraint, voice/music preservation, and frontend delivery with warnings rather than hard failure.
- Features visible: dead-air reduction, local visual stack, controlled SFX, captions, music, closure guard.
- Why it is useful: reference for conservative handling of sensitive insurance content and no overuse of silence punctuation.
