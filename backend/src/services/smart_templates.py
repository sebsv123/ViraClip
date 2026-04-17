"""
Smart Templates — Phase 9 Creative Engine

Content-adaptive rendering presets per platform and detected content type.
Auto-detects tutorial / interview / education / high-energy from transcript.
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class RenderPreset:
    name: str
    platform: str
    resolution: "tuple[int, int]"
    fps: int
    subtitle_font_size: int
    subtitle_font_color: str
    subtitle_outline_color: str
    subtitle_position: str           # "top" | "center" | "bottom"
    zoom_punch_enabled: bool
    sfx_volume: float
    bgm_volume: float
    cut_density: str                 # "low" | "medium" | "high"
    max_duration_s: int
    aspect_ratio: str
    extra_vf_filters: "list[str]" = field(default_factory=list)


PRESETS: "dict[str, RenderPreset]" = {
    "tiktok_viral": RenderPreset(
        name="TikTok Viral",
        platform="tiktok",
        resolution=(1080, 1920),
        fps=30,
        subtitle_font_size=26,
        subtitle_font_color="#FFFFFF",
        subtitle_outline_color="#000000",
        subtitle_position="center",
        zoom_punch_enabled=True,
        sfx_volume=0.45,
        bgm_volume=0.10,
        cut_density="high",
        max_duration_s=60,
        aspect_ratio="9:16",
        extra_vf_filters=["eq=brightness=0.03:saturation=1.1"],  # sin vignette
    ),
    "reels_drama": RenderPreset(
        name="Reels Drama",
        platform="reels",
        resolution=(1080, 1920),
        fps=30,
        subtitle_font_size=24,
        subtitle_font_color="#FFFFFF",
        subtitle_outline_color="#000000",
        subtitle_position="bottom",
        zoom_punch_enabled=True,
        sfx_volume=0.35,
        bgm_volume=0.10,
        cut_density="high",
        max_duration_s=90,
        aspect_ratio="9:16",
        extra_vf_filters=["eq=contrast=1.05:saturation=1.15"],  # sin vignette
    ),
    "youtube_shorts": RenderPreset(
        name="YouTube Shorts",
        platform="shorts",
        resolution=(1080, 1920),
        fps=60,
        subtitle_font_size=22,
        subtitle_font_color="#FFFF00",
        subtitle_outline_color="#000000",
        subtitle_position="bottom",
        zoom_punch_enabled=False,
        sfx_volume=0.25,
        bgm_volume=0.08,
        cut_density="medium",
        max_duration_s=60,
        aspect_ratio="9:16",
        extra_vf_filters=["eq=brightness=0.02:saturation=1.05"],
    ),
    "tutorial": RenderPreset(
        name="Tutorial",
        platform="youtube",
        resolution=(1080, 1920),
        fps=30,
        subtitle_font_size=20,
        subtitle_font_color="#FFFFFF",
        subtitle_outline_color="#333333",
        subtitle_position="bottom",
        zoom_punch_enabled=False,
        sfx_volume=0.15,
        bgm_volume=0.06,
        cut_density="low",
        max_duration_s=120,
        aspect_ratio="9:16",
        extra_vf_filters=[],
    ),
    "interview": RenderPreset(
        name="Interview",
        platform="generic",
        resolution=(1080, 1920),
        fps=30,
        subtitle_font_size=21,
        subtitle_font_color="#FFFFFF",
        subtitle_outline_color="#000000",
        subtitle_position="bottom",
        zoom_punch_enabled=False,
        sfx_volume=0.10,
        bgm_volume=0.05,
        cut_density="low",
        max_duration_s=120,
        aspect_ratio="9:16",
        extra_vf_filters=[],
    ),
    "education": RenderPreset(
        name="Education",
        platform="generic",
        resolution=(1080, 1920),
        fps=30,
        subtitle_font_size=22,
        subtitle_font_color="#FFFFFF",
        subtitle_outline_color="#000000",
        subtitle_position="bottom",
        zoom_punch_enabled=False,
        sfx_volume=0.20,
        bgm_volume=0.08,
        cut_density="medium",
        max_duration_s=120,
        aspect_ratio="9:16",
        extra_vf_filters=[],
    ),
    "high_energy": RenderPreset(
        name="High Energy",
        platform="tiktok",
        resolution=(1080, 1920),
        fps=30,
        subtitle_font_size=28,
        subtitle_font_color="#FF4444",
        subtitle_outline_color="#000000",
        subtitle_position="center",
        zoom_punch_enabled=True,
        sfx_volume=0.50,
        bgm_volume=0.12,
        cut_density="high",
        max_duration_s=45,
        aspect_ratio="9:16",
        extra_vf_filters=["eq=contrast=1.1:saturation=1.2:brightness=0.05"],  # sin vignette
    ),
}

# Keyword signals per content type (Spanish + English)
_SIGNALS: "dict[str, list[str]]" = {
    "tutorial":   ["paso", "step", "cómo", "como", "how to", "primero", "segundo", "tercero",
                   "primero", "siguiente", "ahora", "next", "then", "finally"],
    "interview":  ["me dijiste", "you said", "pregunta", "question", "responde", "answer",
                   "cuéntame", "tell me", "entrevista", "interview"],
    "education":  ["aprender", "learn", "importante", "important", "porque", "because",
                   "significa", "means", "ejemplo", "example", "estudia", "study"],
    "high_energy": ["¡", "wow", "increíble", "increible", "amazing", "impresionante",
                    "loco", "crazy", "explosión", "explosion", "fire", "fuego"],
}


class SmartTemplateSelector:
    """Auto-selects the best RenderPreset for a given content + platform."""

    def select(
        self,
        platform: str,
        transcript: str,
        virality_score: float,
        audio_energy: float = 0.5,
    ) -> RenderPreset:
        content_type = self._detect(transcript, audio_energy)
        key = self._resolve(platform.lower(), content_type, virality_score, audio_energy)
        preset = PRESETS.get(key, PRESETS["tiktok_viral"])
        logger.debug("SmartTemplate: content=%s → preset=%s", content_type, preset.name)
        return preset

    def _detect(self, transcript: str, audio_energy: float) -> str:
        text = transcript.lower()
        scores: dict[str, int] = {k: 0 for k in _SIGNALS}
        for ctype, signals in _SIGNALS.items():
            for sig in signals:
                if sig in text:
                    scores[ctype] += 1
        if audio_energy > 0.75:
            scores["high_energy"] += 2
        best = max(scores, key=lambda k: scores[k])
        return best if scores[best] > 0 else "generic"

    def _resolve(
        self,
        platform: str,
        content_type: str,
        virality_score: float,
        audio_energy: float,
    ) -> str:
        if content_type == "tutorial":
            return "tutorial"
        if content_type == "interview":
            return "interview"
        if content_type == "education":
            return "education"
        if content_type == "high_energy" or audio_energy > 0.80:
            return "high_energy"
        if "reel" in platform:
            return "reels_drama"
        if "short" in platform:
            return "youtube_shorts"
        return "tiktok_viral"


# ── Singleton ─────────────────────────────────────────────────────────────────

_selector: "SmartTemplateSelector | None" = None


def get_template_selector() -> SmartTemplateSelector:
    global _selector
    if _selector is None:
        _selector = SmartTemplateSelector()
    return _selector
