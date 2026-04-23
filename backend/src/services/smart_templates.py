"""
Smart Templates

Content-adaptive rendering presets per platform and virality score.

Updated: 2026-04-23 - Added zoom_punch_zoom and zoom_punch_duration fields
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Preset:
    name: str
    zoom_punch_enabled: bool
    extra_vf_filters: "list[str]" = field(default_factory=list)
    caption_style: str = "default"
    beat_sync: bool = False
    # Campos adicionales esperados por creative_pipeline
    zoom_punch_zoom: float = 1.15
    zoom_punch_duration: float = 0.25


# 4 core presets as specified
_PRESETS: "dict[str, Preset]" = {
    "viral_energetic": Preset(
        name="viral_energetic",
        zoom_punch_enabled=True,
        zoom_punch_zoom=1.2,
        zoom_punch_duration=0.3,
        extra_vf_filters=["eq=contrast=1.1:saturation=1.2:brightness=0.02"],
        caption_style="bold_center",
        beat_sync=True,
    ),
    "cinematic_calm": Preset(
        name="cinematic_calm",
        zoom_punch_enabled=False,
        zoom_punch_zoom=1.0,
        zoom_punch_duration=0.0,
        extra_vf_filters=["eq=contrast=1.05:saturation=0.95:brightness=0.0"],
        caption_style="elegant_bottom",
        beat_sync=False,
    ),
    "talking_head": Preset(
        name="talking_head",
        zoom_punch_enabled=False,
        zoom_punch_zoom=1.0,
        zoom_punch_duration=0.0,
        extra_vf_filters=[],
        caption_style="standard_bottom",
        beat_sync=False,
    ),
    "high_energy": Preset(
        name="high_energy",
        zoom_punch_enabled=True,
        zoom_punch_zoom=1.25,
        zoom_punch_duration=0.35,
        extra_vf_filters=["eq=contrast=1.2:saturation=1.3:brightness=0.05"],
        caption_style="bold_large",
        beat_sync=True,
    ),
}


class TemplateSelector:
    """Select best rendering preset based on platform and content analysis."""

    def select(
        self,
        platform: str,
        transcript: str,
        virality_score: float,
        audio_energy: float = 0.5,
    ) -> Preset:
        """Select preset — never returns None, always returns a valid preset."""
        platform_lower = platform.lower()
        
        # High energy detection
        is_high_energy = audio_energy > 0.75 or virality_score > 80
        
        # Platform-specific logic
        if platform_lower in ("tiktok", "reels"):
            if is_high_energy:
                return _PRESETS["high_energy"]
            if virality_score > 60:
                return _PRESETS["viral_energetic"]
            return _PRESETS["talking_head"]
        
        if platform_lower in ("youtube_shorts", "shorts"):
            if virality_score > 70:
                return _PRESETS["viral_energetic"]
            return _PRESETS["talking_head"]
        
        if platform_lower in ("youtube", "long_form"):
            if is_high_energy:
                return _PRESETS["high_energy"]
            if virality_score < 50:
                return _PRESETS["cinematic_calm"]
            return _PRESETS["talking_head"]
        
        # Default fallback (never None)
        if virality_score > 70:
            return _PRESETS["viral_energetic"]
        if virality_score < 45:
            return _PRESETS["cinematic_calm"]
        
        # Ultimate fallback — always talking_head
        return _PRESETS["talking_head"]


# ── Singleton ─────────────────────────────────────────────────────────────────

_selector: "TemplateSelector | None" = None


def get_template_selector() -> TemplateSelector:
    """Get or create singleton template selector."""
    global _selector
    if _selector is None:
        _selector = TemplateSelector()
    return _selector
