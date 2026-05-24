# Transitions — ViraClip

## Overview

ViraClip provides 5 transition effects for seamless clip concatenation. All
transitions are implemented in `backend/src/clip_editor.py` and exposed through
`backend/src/transition_selector.py`.

## Effects

| # | Effect | Function | Description |
|---|--------|----------|-------------|
| 1 | **match_cut** | `match_cut_transition()` | Zoom + pan towards/from object center with smoothstep easing |
| 2 | **glitch** | `glitch_transition()` | RGB shift, scanlines, or freeze-frame glitch via FFmpeg |
| 3 | **sweep_mask** | `sweep_mask_transition()` | Expansive mask (circle, diagonal, or wipe) via FFmpeg geq |
| 4 | **mask_reveal** | `mask_reveal_transition()` | Auto edge-detection or semantic-category mask reveal |
| 5 | **shape_morph** | `shape_morph_transition()` | SAM/rembg segmentation + Procrustes contour morphing |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RENDER3D_URL` | `http://render3d:5000` | URL for the render3d service (3D asset rendering) |
| `ICONSCOUT_API_KEY` | *(none)* | IconScout API key for icon assets (optional) |
| `SAM_MODEL` | `vit_b` | SAM model to download at build time (`vit_b`, `vit_h`, or `all`) |

## SAM Model Notes

- **vit_b** (375 MB): Default, downloaded when `SAM_MODEL=vit_b` or `SAM_MODEL=all`.
- **vit_h** (2.6 GB): High-quality, downloaded when `SAM_MODEL=vit_h` or `SAM_MODEL=all`.
- Models are stored at `/app/models/sam_vit_{model_type}.pth` inside the container.
- The worker logs a WARNING at startup if models are missing (startup never fails).
- Used by `shape_morph_transition` with `quality="high"` (vit_b) or `quality="ultra"` (vit_h).

## Test Commands

```bash
# Run all transition tests (CPU-only tests)
cd backend && uv run pytest src/tests/test_transitions.py -v -m "not gpu"

# Run all tests including GPU-requiring ones (shape_morph with SAM/rembg)
cd backend && uv run pytest src/tests/test_transitions.py -v

# Run a specific test class
cd backend && uv run pytest src/tests/test_transitions.py -v -k TestMatchCut

# Run with coverage
cd backend && uv run pytest src/tests/test_transitions.py -v --cov=clip_editor --cov=transition_selector
```

## IconScout Plan Note

IconScout integration (`fetch_iconscout_asset`) is optional and degrades
gracefully when `ICONSCOUT_API_KEY` is not set. The function returns `None`
and logs a warning. Redis caching is attempted but falls back to an in-memory
dictionary if Redis is unavailable.

## Architecture

```
transition_selector.py          # High-level dispatch (select_and_apply_transition, merge_with_transitions)
    │
    ├── clip_editor.py          # Low-level effect implementations
    │   ├── match_cut_transition()
    │   ├── glitch_transition()
    │   ├── sweep_mask_transition()
    │   ├── mask_reveal_transition()
    │   └── shape_morph_transition()
    │
    └── render3d (service)      # Optional 3D asset rendering (port 5000)
```

All effects degrade gracefully: if an effect fails, it logs the error and
returns a hard cut (simple concatenation) instead of raising an exception.
