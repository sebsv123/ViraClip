"""Debug: print the exact filter_complex being generated."""
import sys
sys.path.insert(0, '/app')

from src.video_processing.editing_pipeline import (
    _build_filter_complex, _emphasis_items, PI_FRAMES, ZOOM_FRAMES, PI_ZOOM, PI_INTERVAL
)

print(f"PI_FRAMES={PI_FRAMES}, ZOOM_FRAMES={ZOOM_FRAMES}, PI_ZOOM={PI_ZOOM}, PI_INTERVAL={PI_INTERVAL}")

words = [
    {"start": 2.0, "end": 2.2, "word": "INCREDIBLE", "is_emphasis": True, "confidence": 0.99},
    {"start": 7.0, "end": 7.3, "word": "AMAZING",    "is_emphasis": True, "confidence": 0.98},
]

emphasis_items = _emphasis_items(words, max_zooms=4)
print(f"emphasis_items={emphasis_items}")

# Case 1: with emphasis → should use punch-in, NO pattern interrupts
fc, vl, al = _build_filter_complex(
    w=1080, h=1920, fps=30.0, dur=15.0,
    emphasis_items=emphasis_items,
    has_audio=True,
    segment_text="Test",
    flash_timestamps=[3.5],
)
print(f"\n--- With emphasis ({len(emphasis_items)} zooms) ---")
for i, step in enumerate(fc.split(";")):
    print(f"  [{i}] {step[:120]}")

# Case 2: no emphasis → Ken Burns + pattern interrupts
fc2, vl2, al2 = _build_filter_complex(
    w=1080, h=1920, fps=30.0, dur=15.0,
    emphasis_items=[],
    has_audio=True,
    segment_text="",
    flash_timestamps=[],
)
print(f"\n--- No emphasis (Ken Burns + PI) ---")
for i, step in enumerate(fc2.split(";")):
    print(f"  [{i}] {step[:120]}")
