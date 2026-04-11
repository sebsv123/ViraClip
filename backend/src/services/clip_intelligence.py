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

import json
import logging
import math
import os
from dataclasses import dataclass, field
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

    saturation:      float  # EditingPipeline saturation override
    contrast:        float  # EditingPipeline contrast override
    ai_keywords:     List[str] = field(default_factory=list)  # AI-chosen B-roll keywords
    content_category: str  = field(default="unknown")         # Editorial Brain category
    narrative:        Any  = field(default=None)               # NarrativeStructure | None

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


# ── AI Brain (Groq) ──────────────────────────────────────────────────────────

_VALID_LUTS      = {"teal_orange", "warm_film", "cold_blue", "vintage", "high_contrast", "flat"}
_VALID_CAPTIONS  = {"tiktok", "highlight", "neon", "minimal", "karaoke"}
_VALID_MOODS     = set(_MOOD_LUTS.keys())
_VALID_BGM       = {"hype", "upbeat", "midtempo", "slow"}
_VALID_ZOOM      = {"off", "subtle", "medium", "strong"}
_VALID_SFX       = {"curiosity_gap", "cliffhanger", "pattern_interrupt",
                    "scroll_stop", "insight_reveal", "transition", "emphasis_word"}

_AI_SYSTEM_PROMPT = """You are a professional viral video editor for TikTok, Reels, and YouTube Shorts.
You receive a video transcript and metadata, and you return a JSON object with precise editing decisions.
Your decisions must match the TONE and CONTENT of the clip — not just generic settings.
Return ONLY a valid JSON object, no markdown, no explanation."""

_AI_USER_TEMPLATE = """Analyze this video clip and decide how to edit it.

Transcript: \"{text}\"
Duration: {duration:.0f}s
Virality score: {virality:.0f}/100
Hook type: {hook_type}

Return a JSON object with EXACTLY these fields:
{{
  "mood": "energetic|dramatic|chill|warm|educational|inspirational",
  "energy": <float 0.0-1.0>,
  "lut": "teal_orange|warm_film|cold_blue|vintage|high_contrast|flat",
  "caption_style": "tiktok|highlight|neon|minimal|karaoke",
  "broll_keywords": [<3-5 specific visual concepts to illustrate the speech>],
  "bgm_category": "hype|upbeat|midtempo|slow",
  "zoom_intensity": "off|subtle|medium|strong",
  "sfx_emphasis": "curiosity_gap|cliffhanger|pattern_interrupt|scroll_stop|insight_reveal|transition",
  "saturation": <float 1.0-1.5>,
  "contrast": <float 1.0-1.3>
}}"""


async def _build_clip_profile_ai(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
) -> Optional[ClipProfile]:
    """
    Ask Groq (llama-3.1-8b-instant) for semantic editing decisions.
    Returns None on any failure — caller falls back to heuristics.
    """
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        return None

    text      = (segment.get("text") or "")[:600].strip()
    virality  = float(segment.get("virality_score", 50))
    hook_type = (segment.get("hook_type") or "insight_reveal").lower()

    if not text:
        return None

    user_msg = _AI_USER_TEMPLATE.format(
        text=text.replace('"', "'"),
        duration=duration,
        virality=virality,
        hook_type=hook_type,
    )

    try:
        import httpx
        async with httpx.AsyncClient(timeout=9.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}",
                          "Content-Type": "application/json"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": _AI_SYSTEM_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    "max_tokens": 320,
                    "temperature": 0.25,
                    "response_format": {"type": "json_object"},
                },
            )
        if resp.status_code != 200:
            logger.debug("[ClipIntel/AI] Groq HTTP %d", resp.status_code)
            return None

        parsed: Dict[str, Any] = resp.json()["choices"][0]["message"]["content"]
        if isinstance(parsed, str):
            parsed = json.loads(parsed)

        # ── Validate & clamp every field ─────────────────────────────────────
        mood          = parsed.get("mood", "warm")
        if mood not in _VALID_MOODS: mood = "warm"

        energy        = max(0.0, min(1.0, float(parsed.get("energy", 0.5))))

        lut           = parsed.get("lut", "teal_orange")
        if lut not in _VALID_LUTS: lut = _MOOD_LUTS.get(mood, ["teal_orange"])[0]

        caption_style = parsed.get("caption_style", "tiktok")
        if caption_style not in _VALID_CAPTIONS: caption_style = "tiktok"

        bgm_category  = parsed.get("bgm_category", "upbeat")
        if bgm_category not in _VALID_BGM: bgm_category = _MOOD_BGM.get(mood, "upbeat")

        zoom_intensity = parsed.get("zoom_intensity", "medium")
        if zoom_intensity not in _VALID_ZOOM: zoom_intensity = "medium"

        sfx_emphasis  = parsed.get("sfx_emphasis", "insight_reveal")
        if sfx_emphasis not in _VALID_SFX: sfx_emphasis = "insight_reveal"

        saturation    = max(1.0, min(1.5, float(parsed.get("saturation", 1.25))))
        contrast      = max(1.0, min(1.3, float(parsed.get("contrast",   1.10))))

        ai_keywords   = [str(k) for k in (parsed.get("broll_keywords") or []) if k][:5]

        # Derive broll count from mood interval
        interval    = _MOOD_BROLL_INTERVAL.get(mood, 7.0)
        broll_count = max(1, min(5, math.ceil(duration / interval)))
        broll_dur   = 3.5 if energy < 0.4 else (2.8 if energy < 0.7 else 2.2)
        wps         = len(text.split()) / max(1.0, duration)
        pace        = "fast" if wps > 3.5 else ("medium" if wps > 2.0 else "slow")

        profile = ClipProfile(
            mood=mood, energy=energy, pace=pace, virality=virality,
            lut=lut, caption_style=caption_style,
            broll_count=broll_count, broll_duration=broll_dur,
            bgm_category=bgm_category, zoom_intensity=zoom_intensity,
            sfx_emphasis=sfx_emphasis, saturation=saturation, contrast=contrast,
            ai_keywords=ai_keywords,
        )
        logger.info(
            "[ClipIntel/AI] clip=%d %s | broll_kw=%s",
            clip_index + 1, profile.describe(), ai_keywords,
        )
        return profile

    except Exception as exc:
        logger.debug("[ClipIntel/AI] Groq failed: %s", exc)
        return None


async def build_clip_profile_async(
    segment: Dict[str, Any],
    duration: float,
    clip_index: int,
    caption_template: str = "viral",
    words: Optional[List[Dict[str, Any]]] = None,
) -> ClipProfile:
    """
    Full intelligence pipeline:
      1. Groq AI brain → semantic editing decisions (fast, ~300 tokens)
      2. Editorial Brain → content-category specialization + narrative structure
      3. Heuristic fallback if either AI step fails
    Always returns a valid ClipProfile — never raises.
    """
    # Step 1: AI or heuristic base profile
    profile = await _build_clip_profile_ai(segment, duration, clip_index)
    ai_was_used = profile is not None
    if profile is None:
        profile = build_clip_profile(segment, duration, clip_index, caption_template)

    # Step 2: Editorial Brain — category identification + narrative structure
    try:
        from .editorial_brain import analyze_clip, apply_category_rules
        category, narrative = await analyze_clip(
            segment=segment,
            duration=duration,
            clip_index=clip_index,
            words=words,
        )
        profile = apply_category_rules(
            profile=profile,
            category_key=category,
            narrative=narrative,
            trust_ai_values=ai_was_used,
        )
    except Exception as _eb_e:
        logger.debug("[ClipIntel] EditorialBrain skipped: %s", _eb_e)

    return profile
