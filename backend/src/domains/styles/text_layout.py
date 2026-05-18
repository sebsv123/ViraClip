"""
Text Layout — Vertical zone definitions for text elements on 1080×1920 canvas.

Defines three non-overlapping vertical zones for:
  - HOOK text (center-top)
  - CONTEXTUAL OVERLAYS / CTA (center or lateral)
  - SUBTITLES / CAPTIONS (bottom)

All coordinates are in pixels for a 1080×1920 (9:16) canvas.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Canvas dimensions ─────────────────────────────────────────────────────────
CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920

# ── Vertical zones (y0 = top, y1 = bottom, both inclusive) ───────────────────
# These zones are designed to NOT overlap with each other or with platform UI
# elements (TikTok bottom bar ~280px, Reels ~260px, Shorts ~300px).

ZONES = {
    # Hook text: attention-grabbing sentence, centered in upper portion
    # Safe from captions below and from platform top UI (status bar, etc.)
    "hook": (240, 640),
    # Contextual overlays / CTA: middle band, below hook, above captions
    # Used for speaker bubbles, keyword overlays, call-to-action buttons
    "overlay": (640, 1200),
    # Subtitles / captions: bottom band, above platform UI buttons
    # MarginV of 280px from bottom ensures no overlap with TikTok UI
    "caption": (1440, 1800),
}

# Platform-specific bottom safe zones (pixels from bottom)
PLATFORM_BOTTOM_MARGIN = {
    "tiktok": 280,
    "reels": 260,
    "shorts": 300,
    "universal": 180,
    "default": 180,
}


@dataclass
class TextElement:
    """A positioned text element on the canvas."""
    zone: str           # "hook", "overlay", "caption"
    y: int              # Top edge of the text (pixels from top)
    estimated_height: int  # Estimated height of the rendered text (pixels)
    content: str = ""   # The text content (for logging)

    @property
    def y_bottom(self) -> int:
        """Bottom edge of the text element."""
        return self.y + self.estimated_height


def get_zone_bounds(zone_name: str) -> Tuple[int, int]:
    """Get the (y_top, y_bottom) bounds for a named zone.

    Args:
        zone_name: One of "hook", "overlay", "caption".

    Returns:
        (y_top, y_bottom) tuple. Returns (0, 0) for unknown zones.
    """
    return ZONES.get(zone_name, (0, 0))


def get_platform_margin_v(platform: str) -> int:
    """Get the bottom margin (MarginV) for a given platform.

    This is the safe distance from the bottom edge to avoid platform UI.
    """
    return PLATFORM_BOTTOM_MARGIN.get(
        platform.lower(),
        PLATFORM_BOTTOM_MARGIN["default"],
    )


def validate_text_layout(
    elements: List[TextElement],
    canvas_height: int = CANVAS_HEIGHT,
) -> List[str]:
    """Validate that text elements don't overlap vertically.

    Checks:
      1. Each element is within its designated zone bounds.
      2. No two elements overlap vertically.
      3. No element extends below the platform-safe bottom margin.

    Args:
        elements: List of TextElement to validate.
        canvas_height: Canvas height in pixels (default: 1920).

    Returns:
        List of warning messages (empty if all checks pass).
    """
    warnings: List[str] = []

    for i, el in enumerate(elements):
        zone_bounds = get_zone_bounds(el.zone)
        if zone_bounds == (0, 0):
            warnings.append(f"[Layout] Unknown zone '{el.zone}' for element {i}")
            continue

        zone_top, zone_bottom = zone_bounds

        # Check: element is within its zone
        if el.y < zone_top:
            warnings.append(
                f"[Layout] Element {i} ('{el.zone}') starts at y={el.y}, "
                f"above zone top {zone_top}"
            )
        if el.y_bottom > zone_bottom:
            warnings.append(
                f"[Layout] Element {i} ('{el.zone}') ends at y={el.y_bottom}, "
                f"below zone bottom {zone_bottom}"
            )

        # Check: element doesn't extend below safe bottom margin
        min_margin = min(PLATFORM_BOTTOM_MARGIN.values())
        if el.y_bottom > canvas_height - min_margin:
            warnings.append(
                f"[Layout] Element {i} ('{el.zone}') ends at y={el.y_bottom}, "
                f"below safe bottom margin ({canvas_height - min_margin})"
            )

    # Check for overlaps between elements
    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            a = elements[i]
            b = elements[j]
            # Check vertical overlap
            if a.y < b.y_bottom and b.y < a.y_bottom:
                warnings.append(
                    f"[Layout] OVERLAP: Element {i} ('{a.zone}', y={a.y}-{a.y_bottom}) "
                    f"overlaps with Element {j} ('{b.zone}', y={b.y}-{b.y_bottom})"
                )

    return warnings


def suggest_y_for_zone(
    zone_name: str,
    estimated_height: int,
    platform: str = "universal",
) -> int:
    """Suggest a y position for a text element within its zone.

    Centers the element vertically within the zone.

    Args:
        zone_name: One of "hook", "overlay", "caption".
        estimated_height: Estimated height of the rendered text.
        platform: Target platform for margin calculation.

    Returns:
        Suggested y position (top edge).
    """
    zone_top, zone_bottom = get_zone_bounds(zone_name)
    if zone_bottom - zone_top < estimated_height:
        # Zone too small — place at zone top with warning
        logger.warning(
            "[Layout] Zone '%s' (%d-%d) too small for estimated height %d",
            zone_name, zone_top, zone_bottom, estimated_height,
        )
        return zone_top

    # Center vertically within zone
    return zone_top + (zone_bottom - zone_top - estimated_height) // 2
