"""
Clip Intelligence — Context-Aware Effect Selection
====================================================
Analyzes each clip's text, energy, virality and hook-type to produce a
ClipProfile that drives intelligent selection of ALL post-processing
effects: LUT colour grade, caption style, B-roll density/duration,
BGM category, SFX selection, zoom intensity, and editing parameters.

Called once per clip in video_service.create_single_clip and passed
through to every feature that supports per-clip configuration.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Sentiment / energy word sets ──────────────────────────────────────────────

_HIGH_ENERGY = {
    "fire", "insane", "crazy", "amazing", "unbelievable", "shocking",
    "explosive", "epic", "massive", "huge", "incredible", "wild",
    "viral", "secret", "exposed", "reveal", "truth", "never", "always",
    "stop", "wait", "listen", "watch", "now", "today", "free", "money",
    "hack", "trick", "cheat", "fastest", "easiest", "biggest", "best",
}
_CALM = {
    "peaceful", "simple", "easy", "gentle", "calm", "slow", "relax",
    "breathe", "focus", "mindful", "quiet", "soft", "natural", "organic",
    "meditat", "breathe", "sleep", "rest", "balance",
}
_DRAMATIC = {
    "dead", "kill", "wrong", "fail", "mistake", "disaster", "crisis",
    "danger", "warning", "critical", "urgent", "breaking", "alert",
    "scam", "fraud", "banned", "illegal", "toxic", "abuse", "scary",
}
_INSPIRATIONAL = {
    "inspir", "motivat", "success", "dream", "goal", "achiev", "possible",
    "believe", "mindset", "growth", "potential", "journey", "purpose",
}

# ── Mood → LUT options (cycle within mood across clips) ───────────────────────

_MOOD_LUTS: Dict[str, List[str]] = {
    "energetic":     ["high_contrast", "teal_orange", "warm_film", "high_contrast"],
    "dramatic":      ["cold_blue", "teal_orange", "high_contrast", "cold_blue"],
    "warm":          ["warm_film", "vintage", "teal_orange", "warm_film"],
    "chill":         ["vintage", "warm_film", "cold_blue", "vintage"],
    "educational":   ["flat", "cold_blue", "minimal_clean", "warm_film"],
    "inspirational": ["warm_film", "vintage", "teal_orange", "warm_film"],
}
# LUT fallback if named preset file is missing
_LUT_FALLBACK = "teal_orange"

# ── Mood → caption style options ─────────────────────────────────────────────

_MOOD_CAPTIONS: Dict[str, List[str]] = {
    "energetic":     ["tiktok", "highlight", "neon", "tiktok"],
    "dramatic":      ["highlight", "neon", "tiktok", "highlight"],
    "warm":          ["karaoke", "tiktok", "minimal", "karaoke"],
    "chill":         ["minimal", "karaoke", "tiktok", "minimal"],
    "educational":   ["minimal", "karaoke", "minimal", "tiktok"],
    "inspirational": ["tiktok", "karaoke", "minimal", "tiktok"],
}

# ── Mood → BGM category ───────────────────────────────────────────────────────

_MOOD_BGM: Dict[str, str] = {
    "energetic":     "hype",
    "dramatic":      "midtempo",
    "warm":          "upbeat",
    "chill":         "slow",
    "educational":   "midtempo",
    "inspirational": "upbeat",
}

# ── Mood → B-roll interval (seconds between insertions) ──────────────────────

_MOOD_BROLL_INTERVAL: Dict[str, float] = {
    "energetic":     5.5,
    "dramatic":      6.0,
    "warm":          7.0,
    "chill":         8.0,
    "educational":   7.5,
    "inspirational": 7.0,
}

# ── Template explicit overrides ───────────────────────────────────────────────

_TEMPLATE_CAPTION: Dict[str, str] = {
    "tutorial":   "minimal",
    "interview":  "minimal",
    "education":  "minimal",
    "neon":       "neon",
    "highlight":  "highlight",
    "karaoke":    "karaoke",
}


# ── ClipProfile dataclass ─────────────────────────────────────────────────────

@dataclass
class ClipProfile:
    mood:           str    # energetic | dramatic | warm | chill | educational | inspirational
    energy:         float  # 0.0 – 1.0
    pace:           str    # fast | medium | slow
    virality:       float  # 0 – 100

    lut:            str    # LUT preset id for colour grade
    caption_style:  str    # ASS caption style id
    broll_count:    int    # number of B-roll overlays to insert
    broll_duration: float  # seconds per overlay
    bgm_category:   str    # BGM category hint for BeatSyncService

    zoom_intensity: str    # off | subtle | medium | strong
    sfx_emphasis:   str    # primary SFX hook type

    saturation:     float  # EditingPipeline saturation override
    contrast:       float  # EditingPipeline contrast override

    def describe(self) -> str:
        return (
            f"mood={self.mood} energy={self.energy:.2f} pace={self.pace} "
            f"lut={self.lut} caption={self.caption_style} "
            f"broll={self.broll_count}x{self.broll_duration:.1f}s "
            f"bgm={self.bgm_category} zoom={self.zoom_intensity}"
        )


# ── Main builder ─────────────────────────────────────────────────────────────

def build_clip_profile(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
    caption_template: str = "viral",
) -> ClipProfile:
    """
    Derive a ClipProfile for a single clip segment.

    Args:
        segment:          The segment dict (text, virality_score, hook_type, theme).
        duration:         Clip duration in seconds.
        clip_index:       0-based index within the task (for variety cycling).
        caption_template: Template name from the render request.

    Returns:
        ClipProfile — all effect decisions for this clip.
    """
    text      = (segment.get("text") or "").lower()
    virality  = float(segment.get("virality_score", 50))
    hook_type = (segment.get("hook_type") or "insight_reveal").lower()
    words     = text.split()
    wcount    = len(words)

    # ── 1. Energy score ───────────────────────────────────────────────────────
    energy_hits   = sum(1 for w in words if any(e in w for e in _HIGH_ENERGY))
    calm_hits     = sum(1 for w in words if any(c in w for c in _CALM))
    dramatic_hits = sum(1 for w in words if any(d in w for d in _DRAMATIC))
    inspir_hits   = sum(1 for w in words if any(i in w for i in _INSPIRATIONAL))
    excl          = text.count("!")
    ques          = text.count("?")
    caps_ratio    = sum(1 for c in text if c.isupper()) / max(1, len(text))

    raw_energy = (
        energy_hits   * 0.12
        + excl        * 0.07
        + ques        * 0.03
        + caps_ratio  * 0.30
        + virality / 100.0 * 0.45
        - calm_hits   * 0.08
    )
    energy = max(0.0, min(1.0, raw_energy))

    # ── 2. Speech pace ────────────────────────────────────────────────────────
    wps  = wcount / max(1.0, duration)
    if wps > 3.5:   pace = "fast"
    elif wps > 2.0: pace = "medium"
    else:           pace = "slow"

    # ── 3. Mood classification ────────────────────────────────────────────────
    if dramatic_hits >= 2 or hook_type in ("cliffhanger", "pattern_interrupt"):
        mood = "dramatic"
    elif inspir_hits >= 2 or hook_type in ("motivation",):
        mood = "inspirational"
    elif energy >= 0.65 or hook_type in ("scroll_stop",):
        mood = "energetic"
    elif calm_hits >= 2 or pace == "slow":
        mood = "chill"
    elif hook_type in ("insight_reveal", "curiosity_gap") and energy < 0.45:
        mood = "educational"
    else:
        mood = "warm"

    # ── 4. LUT selection — varied within mood by clip_index ──────────────────
    lut_list = _MOOD_LUTS.get(mood, ["teal_orange", "warm_film", "cold_blue", "vintage"])
    lut = lut_list[clip_index % len(lut_list)]

    # ── 5. Caption style — template takes priority, then mood ─────────────────
    caption_style = (
        _TEMPLATE_CAPTION.get(caption_template)
        or _MOOD_CAPTIONS.get(mood, ["tiktok", "minimal", "karaoke", "neon"])[
            clip_index % 4
        ]
    )

    # ── 6. B-roll density ─────────────────────────────────────────────────────
    interval      = _MOOD_BROLL_INTERVAL.get(mood, 7.0)
    broll_count   = max(1, min(5, math.ceil(duration / interval)))
    broll_dur     = 3.5 if energy < 0.4 else (2.8 if energy < 0.7 else 2.2)

    # ── 7. BGM category ───────────────────────────────────────────────────────
    bgm_category = _MOOD_BGM.get(mood, "upbeat")

    # ── 8. Zoom intensity ─────────────────────────────────────────────────────
    if energy >= 0.75:    zoom_intensity = "strong"
    elif energy >= 0.45:  zoom_intensity = "medium"
    elif energy >= 0.20:  zoom_intensity = "subtle"
    else:                 zoom_intensity = "off"

    # ── 9. Primary SFX type ───────────────────────────────────────────────────
    _hook_sfx = {
        "curiosity_gap":    "curiosity_gap",
        "cliffhanger":      "cliffhanger",
        "pattern_interrupt": "pattern_interrupt",
        "scroll_stop":      "scroll_stop",
        "insight_reveal":   "insight_reveal",
    }
    sfx_emphasis = _hook_sfx.get(hook_type, "transition")

    # ── 10. Editing pipeline adjustments ──────────────────────────────────────
    saturation = round(1.10 + energy * 0.30, 3)   # 1.10–1.40
    contrast   = round(1.03 + energy * 0.22, 3)   # 1.03–1.25

    profile = ClipProfile(
        mood=mood, energy=energy, pace=pace, virality=virality,
        lut=lut, caption_style=caption_style,
        broll_count=broll_count, broll_duration=broll_dur,
        bgm_category=bgm_category, zoom_intensity=zoom_intensity,
        sfx_emphasis=sfx_emphasis, saturation=saturation, contrast=contrast,
    )
    logger.info("[ClipIntel] clip=%d %s", clip_index + 1, profile.describe())
    return profile
