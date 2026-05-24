import os
_ENV = os.getenv("APP_ENV", "production")
COMFYUI_LOCK_KEY = f"{_ENV}:lock:comfyui"
from src.constants import BROLL_HTTP_TIMEOUT, COMFYUI_LOCK_TIMEOUT_SECONDS
"""
BRoll Service - AI-powered B-roll injection for viral video enhancement.

Pipeline:
  1. Keyword extraction   — Groq llama-3.1-8b-instant extracts 2-3 visual search terms
  2. Asset fetch          — Pexels API (portrait video); Pixabay API as fallback
  3. Silence detection    — librosa finds gaps > 1.5 s in segment audio
  4. FFmpeg overlay       — inserts B-roll with 0.3 s fade-in/out at silence timestamps
                           (or at t=5 s if no silences found)
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from src import gpu_utils

import httpx

from ...config import Config, get_config
from ...comfyui_bridge import COMFYUI_ENABLED, ComfyUIBridge  # ComfyUIBridge reservado para LTXV intro
from .comfyui_integration import comfyui_integration
from .broll_compositor import compose_overlay, probe_duration
from .scene_broll_placer import get_insert_timestamps

logger = logging.getLogger(__name__)

# Configuraciones B-roll via environment variables para fácil tuning
_BROLL_DOWNLOAD_TIMEOUT = int(os.environ.get("BROLL_DOWNLOAD_TIMEOUT", "30"))   # seconds per file
from .broll_config import (
    MIN_OVERLAY_DURATION_S,
    MIN_ASSET_DURATION_S,
    FADE_DURATION_S,
    DEFAULT_OVERLAY_DURATION_S,
)

_MIN_SILENCE_SEC = float(os.environ.get("BROLL_MIN_SILENCE_SEC", "1.5"))       # minimum silence gap
_BROLL_DURATION = float(os.environ.get("BROLL_DURATION", "4.5"))               # seconds of B-roll - más largo para presencia
_FADE_DURATION = float(os.environ.get("BROLL_FADE_DURATION", "0.6"))             # fade-in / fade-out length - suave
_CACHE_TTL_DAYS = int(os.environ.get("BROLL_CACHE_TTL_DAYS", "7"))               # cache stale days
_BROLL_MAX_OVERLAYS = int(os.environ.get("BROLL_MAX_OVERLAYS", "3"))             # max overlays per clip
_BROLL_MIN_DURATION_S = float(os.environ.get("BROLL_MIN_DURATION_S", "1.0"))     # minimum asset duration to use (FIX 3)
# Shared minimum overlay duration — b-roll never renders shorter than this.
# Used consistently across all paths that compute b-roll overlay duration.
BROLL_MIN_OVERLAY_DURATION_S = MIN_OVERLAY_DURATION_S

# ── Multi-provider Pexels key pool (round-robin) ────────────────────────────
_PEXELS_KEYS = [
    k for k in [
        os.environ.get("PEXELS_API_KEY", ""),
        os.environ.get("PEXELS_API_KEY_2", ""),
        os.environ.get("PEXELS_API_KEY_3", ""),
    ] if k
]
_PEXELS_KEY_INDEX = 0
# ── Source rotation counter ──────────────────────────────────────────────────
# Incremented per keyword call to alternate between Pexels and Coverr as the
# primary source. This prevents visual monotony from a single source.
_BROLL_SOURCE_ROTATION = 0

def _get_next_pexels_key() -> str:
    """Return the next Pexels API key in round-robin order."""
    global _PEXELS_KEY_INDEX
    if not _PEXELS_KEYS:
        return ""
    key = _PEXELS_KEYS[_PEXELS_KEY_INDEX % len(_PEXELS_KEYS)]
    _PEXELS_KEY_INDEX = (_PEXELS_KEY_INDEX + 1) % len(_PEXELS_KEYS)
    return key

# ── Brand Config ────────────────────────────────────────────────────────────
# Task-level brand intro/outro configuration.
# Controls branded opening and closing for each clip in the task.
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class LowerThirdConfig:
    """Lower-third overlay configuration for speaker identification and key labels.

    All fields are optional — if not set, no lower-third is rendered.

    Fields:
        speaker_name: Name of the speaker to display.
        speaker_title: Title/role of the speaker (e.g., "Insurance Advisor").
        label_text: Key label text (e.g., "Key Fact" or "Important").
        primary_color: Hex color for the accent bar and text.
        font_family: Font to use (default "THEBOLDFONT").
        position_y: Vertical position as fraction of height (0.0–1.0, default 0.85).
        duration: How long the lower-third stays visible in seconds (default 4.0).
        animation: Animation style — "slide_in" or "fade_in" (default "slide_in").
    """
    speaker_name: Optional[str] = None
    speaker_title: Optional[str] = None
    label_text: Optional[str] = None
    primary_color: str = "#0055AA"
    font_family: str = "THEBOLDFONT"
    position_y: float = 0.85
    duration: float = 4.0
    animation: str = "slide_in"

    def is_active(self) -> bool:
        """Return True if any lower-third content is configured."""
        return bool(self.speaker_name or self.speaker_title or self.label_text)

    def to_drawtext_filter(self, video_w: int = 1080, video_h: int = 1920) -> str:
        """Build an FFmpeg drawtext filter string for this lower-third.

        Creates a branded lower-third with:
        - Colored accent bar on the left
        - Speaker name in bold (top line)
        - Speaker title in smaller text (bottom line, if provided)
        - Optional label badge on the right side

        The filter uses the task's font file and brand colors.
        """
        if not self.is_active():
            return ""

        _font_path = f"/app/fonts/{self.font_family}.ttf"
        _bar_w = int(video_w * 0.06)  # 6% of width = accent bar
        _bar_h = int(video_h * 0.07)  # 7% of height
        _bar_x = 0
        _bar_y = int(video_h * self.position_y)

        _text_x = _bar_w + 20  # 20px padding from accent bar
        _text_y = _bar_y + int(_bar_h * 0.3)

        _parts = []

        # Accent bar (colored rectangle)
        _parts.append(
            f"drawbox=x={_bar_x}:y={_bar_y}:w={_bar_w}:h={_bar_h}:"
            f"color={self.primary_color}@0.9:t=fill"
        )

        # Speaker name
        if self.speaker_name:
            _name_escaped = self.speaker_name.replace("'", "'\\\\\\''").replace(":", "\\\\:")
            _parts.append(
                f"drawtext=text='{_name_escaped}':"
                f"x={_text_x}:y={_text_y}:"
                f"fontfile={_font_path}:fontsize=28:fontcolor=white:"
                f"box=1:boxcolor=black@0.5:boxborderw=8"
            )

        # Speaker title (below name)
        if self.speaker_title:
            _title_escaped = self.speaker_title.replace("'", "'\\\\\\''").replace(":", "\\\\:")
            _title_y = _text_y + 36
            _parts.append(
                f"drawtext=text='{_title_escaped}':"
                f"x={_text_x}:y={_title_y}:"
                f"fontfile={_font_path}:fontsize=20:fontcolor={self.primary_color}:"
                f"box=1:boxcolor=black@0.4:boxborderw=6"
            )

        # Label text (right side badge)
        if self.label_text:
            _label_escaped = self.label_text.replace("'", "'\\\\\\''").replace(":", "\\\\:")
            _label_x = int(video_w * 0.65)
            _parts.append(
                f"drawtext=text='{_label_escaped}':"
                f"x={_label_x}:y={_bar_y + 8}:"
                f"fontfile={_font_path}:fontsize=22:fontcolor=white:"
                f"box=1:boxcolor={self.primary_color}@0.85:boxborderw=10"
            )

        return ":".join(_parts)


@dataclass
class BrandConfig:
    """Brand intro/outro configuration for consistent branded openings and closings.

    All fields are optional — if not set, no branding is applied.

    Fields:
        logo_path: Path to brand logo image (PNG with transparency).
        primary_color: Hex color for text and accents (e.g., "#0055AA").
        secondary_color: Hex color for secondary elements (e.g., "#FF6600").
        intro_text: Text to display in the intro (e.g., brand name or tagline).
        outro_text: Text to display in the outro (e.g., "Subscribe for more").
        intro_duration: Duration of the intro overlay in seconds (default 1.5).
        outro_duration: Duration of the outro overlay in seconds (default 2.0).
        font_family: Font to use for intro/outro text (default "THEBOLDFONT").
        lower_third: Optional LowerThirdConfig for speaker identification.
    """
    logo_path: Optional[str] = None
    primary_color: str = "#0055AA"
    secondary_color: str = "#FF6600"
    intro_text: Optional[str] = None
    outro_text: Optional[str] = None
    intro_duration: float = 1.5
    outro_duration: float = 2.0
    font_family: str = "THEBOLDFONT"
    lower_third: Optional[LowerThirdConfig] = None

    def is_active(self) -> bool:
        """Return True if any branding is configured."""
        return bool(self.logo_path or self.intro_text or self.outro_text or
                    (self.lower_third and self.lower_third.is_active()))

    def to_caption_style(self) -> Dict[str, Any]:
        """Map BrandConfig to a caption template dict for CaptionService.

        Returns a dict with the same keys as CAPTION_TEMPLATES entries,
        using brand colors and font. This ensures captions match the
        task's visual style (intro/outro/lower-third).

        Mapping:
        - font_family: from BrandConfig (default "THEBOLDFONT")
        - font_color: white (always readable)
        - highlight_color: primary_color (brand accent for karaoke)
        - stroke_color: black (always readable)
        - background_color: primary_color at 30% opacity (subtle brand tint)
        - animation: "karaoke" (word-by-word highlight)
        - position_y: 0.75 (standard caption position, below lower-third)
        """
        return {
            "name": "Branded",
            "description": f"Branded captions ({self.primary_color})",
            "font_family": self.font_family,
            "font_size": 32,
            "font_color": "#FFFFFF",
            "highlight_color": self.primary_color,
            "stroke_color": "#000000",
            "stroke_width": 2,
            "background": True,
            "background_color": f"{self.primary_color}4D",  # 30% opacity
            "animation": "karaoke",
            "shadow": False,
            "position_y": 0.75,
        }


# ── Visual Style Profile ────────────────────────────────────────────────────
# Task-level visual preferences that control B-roll selection, transitions,
# and overall brand look. Stored per task and passed to process_clip().

VisualTone = Literal["corporate", "testimonial", "explainer", "premium", "minimal"]
MotionLevel = Literal["low", "medium", "high"]
ColorTemp = Literal["warm", "neutral", "cool"]
CutDensity = Literal["sparse", "balanced", "dense"]
TransitionStyle = Literal["soft", "standard", "none"]


@dataclass
class MotionStyle:
    """Unified motion style for all visual elements in a task.

    Ensures B-roll transitions, intros, lower-thirds, and captions
    use the same easing and animation language. Prevents mixing
    soft corporate motion with aggressive punchy motion in the same clip.

    Fields:
        easing: Easing function for all animations.
        broll_motion: Camera motion type for B-roll assets.
        transition_type: Overlay transition between B-roll scenes.
        caption_animation: Caption word highlight animation.
        lower_third_animation: Lower-third entry animation.
        intro_animation: Intro overlay animation.
        outro_animation: Outro overlay animation.
    """
    easing: str = "ease_out"  # ease_out, ease_in_out, linear
    broll_motion: str = "ken_burns"  # ken_burns, slow_pan, static, zoom_in
    transition_type: str = "crossfade"  # crossfade, fade, cut
    caption_animation: str = "karaoke"  # karaoke, pop, fade, bounce, none
    lower_third_animation: str = "slide_in"  # slide_in, fade_in, none
    intro_animation: str = "fade_in"  # fade_in, slide_down, none
    outro_animation: str = "fade_out"  # fade_out, slide_up, none

    @classmethod
    def from_profile(cls, profile: "VisualStyleProfile") -> "MotionStyle":
        """Derive a unified MotionStyle from a VisualStyleProfile.

        Mapping:
        - motion_level low → ken_burns, ease_out
        - motion_level medium → slow_pan, ease_in_out
        - motion_level high → zoom_in, linear
        - transition_style soft → crossfade
        - transition_style standard → fade
        - transition_style none → cut
        """
        _motion_map = {
            "low": ("ken_burns", "ease_out"),
            "medium": ("slow_pan", "ease_in_out"),
            "high": ("zoom_in", "linear"),
        }
        _broll_motion, _easing = _motion_map.get(profile.motion_level, ("slow_pan", "ease_in_out"))

        _transition_map = {"soft": "crossfade", "standard": "fade", "none": "cut"}
        _transition = _transition_map.get(profile.transition_style, "fade")

        return cls(
            easing=_easing,
            broll_motion=_broll_motion,
            transition_type=_transition,
            caption_animation="karaoke",
            lower_third_animation="slide_in" if _transition != "cut" else "none",
            intro_animation="fade_in" if _transition != "cut" else "none",
            outro_animation="fade_out" if _transition != "cut" else "none",
        )


@dataclass
class VisualStyleProfile:
    """Task-level visual style profile for consistent brand look.

    All fields have defaults so the profile is optional — tasks without
    a profile use the existing category-based selection.

    Fields:
        visual_tone: Brand tone — controls preferred asset kinds and tags.
        motion_level: Camera motion intensity — affects shot selection.
        color_temperature: Color grade preference — passed to EditingPipeline.
        cut_density: B-roll frequency — sparse=1/min, balanced=2/min, dense=3/min.
        transition_style: Overlay transition type — soft=crossfade, standard=fade, none=cut.
    """
    visual_tone: VisualTone = "explainer"
    motion_level: MotionLevel = "medium"
    color_temperature: ColorTemp = "neutral"
    cut_density: CutDensity = "balanced"
    transition_style: TransitionStyle = "standard"

    def to_motion_style(self) -> MotionStyle:
        """Derive a unified MotionStyle from this profile."""
        return MotionStyle.from_profile(self)

    def to_broll_style_name(self) -> str:
        """Map visual_tone to a BROLL_STYLE_PROFILES key."""
        _map = {
            "corporate": "insurance_corporate",
            "testimonial": "insurance_testimonial",
            "explainer": "insurance_explainer",
            "premium": "insurance_advisor",
            "minimal": "generic",
        }
        return _map.get(self.visual_tone, "generic")

    def to_density_budget(self) -> int:
        """Map cut_density to max B-rolls per clip."""
        _map = {"sparse": 1, "balanced": 2, "dense": 3}
        return _map.get(self.cut_density, 2)

    def to_motion_preference(self) -> List[str]:
        """Map motion_level to preferred camera motion keywords."""
        _map = {
            "low": ["static", "slow pan"],
            "medium": ["pan", "slow pan", "ken burns"],
            "high": ["zoom", "track", "dolly", "camera move"],
        }
        return _map.get(self.motion_level, ["pan", "slow pan"])

    def to_transition_duration(self) -> float:
        """Map transition_style to crossfade duration in seconds."""
        _map = {"soft": 0.4, "standard": 0.2, "none": 0.0}
        return _map.get(self.transition_style, 0.2)


# ── B-roll style profiles ──────────────────────────────────────────────────
# Each profile defines preferred asset kinds, max density, and tag preferences.
# Used by _apply_style_preferences() to filter/rank assets per clip category.
BROLL_STYLE_PROFILES: Dict[str, Dict[str, Any]] = {
    "finance": {
        "preferred_tags": ["chart", "city", "office", "business", "money", "graph", "building", "professional"],
        "max_per_min": 6,
        "prefer_kind": "abstract",
    },
    "podcast": {
        "preferred_tags": ["microphone", "studio", "interview", "conversation", "podcast", "recording"],
        "max_per_min": 4,
        "prefer_kind": "human",
    },
    "coaching": {
        "preferred_tags": ["motivation", "success", "people", "team", "presentation", "seminar", "training"],
        "max_per_min": 6,
        "prefer_kind": "human",
    },
    # ── Insurance-specific style profiles ──
    "insurance_testimonial": {
        "preferred_tags": [
            "family", "home", "protection", "happy", "smiling",
            "couple", "parent", "child", "elderly", "peaceful",
        ],
        "max_per_min": 4,
        "prefer_kind": "human",
        "description": "Warm, emotional scenes of protected families and peaceful homes",
    },
    "insurance_claim": {
        "preferred_tags": [
            "car accident", "damage", "repair", "document", "claim",
            "form", "clipboard", "signing", "inspecting", "emergency",
        ],
        "max_per_min": 3,
        "prefer_kind": "object",
        "description": "Practical scenes of claim filing, damage inspection, and resolution",
    },
    "insurance_explainer": {
        "preferred_tags": [
            "advisor", "consultation", "office", "desk", "laptop",
            "explaining", "chart", "graph", "planning", "meeting",
        ],
        "max_per_min": 5,
        "prefer_kind": "human",
        "description": "Educational scenes of advisors explaining policies and options",
    },
    "insurance_advisor": {
        "preferred_tags": [
            "advisor", "agent", "broker", "consultation", "office",
            "professional", "suit", "meeting", "handshake", "trust",
        ],
        "max_per_min": 4,
        "prefer_kind": "human",
        "description": "Professional advisor scenes building trust and rapport",
    },
    "insurance_corporate": {
        "preferred_tags": [
            "building", "office", "corporate", "professional", "meeting",
            "presentation", "team", "boardroom", "strategy", "planning",
        ],
        "max_per_min": 6,
        "prefer_kind": "abstract",
        "description": "Corporate scenes for business insurance and enterprise content",
    },
    "generic": {
        "preferred_tags": [
            "nature", "landscape", "people", "city", "technology", "abstract",
            "success", "achievement", "goal", "motivation", "determination",
            "fitness", "workout", "sport", "running", "exercise", "health",
            "business", "office", "meeting", "presentation", "team",
            "travel", "adventure", "sunrise", "sunset", "mountain", "ocean",
            "lifestyle", "happy", "smile", "family", "friends", "love",
            "education", "learning", "study", "book", "knowledge",
            "creative", "design", "art", "music", "inspiration",
            "food", "cooking", "nature", "garden", "plant", "flower",
            "meditation", "yoga", "wellness", "calm", "peaceful",
            "celebration", "party", "fun", "dance", "music",
            "innovation", "future", "digital", "data", "connection",
        ],
        "max_per_min": 8,
        "prefer_kind": "abstract",
    },
}

# Enriquecimiento de keywords para nicho seguros (ES->EN stock-friendly)
INSURANCE_KEYWORD_MAP: Dict[str, List[str]] = {
    "seguro de vida": ["life insurance family", "family protection"],
    "seguro de coche": ["car insurance", "car accident road"],
    "seguro del hogar": ["home insurance", "modern family home"],
    "ahorro": ["financial planning", "saving money"],
    "protección": ["family protection", "safety concept"],
    "precio": ["budget planning", "insurance quote"],
    "accidente": ["car accident", "medical support"],
    "tranquilidad": ["peaceful family", "stress free home"],
    "contrato": ["signing contract", "agreement handshake"],
    "mutua": ["health insurance", "doctor consultation"],
    "fallecimiento": ["family support", "life coverage"],
    "cobertura": ["insurance coverage", "policy details"],
    "indemnización": ["insurance claim", "compensation process"],
}

# ── Insurance-native b-roll concepts ──────────────────────────────────────────
# These are the ONLY acceptable b-roll concepts for insurance/finance content.
# Each concept is a concrete, visual, insurance-domain idea that can be searched
# on stock video sites. Generic motivational or unrelated concepts are rejected.
# Used by _filter_insurance_keywords() to harden keyword selection.
INSURANCE_NATIVE_CONCEPTS: List[str] = [
    "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "risk", "responsibility",
    "payments", "approval", "documents", "contracts",
    "advisor", "customer", "office", "calculator",
    "forms", "phone call", "consultation",
    # Additional concrete insurance visuals
    "insurance", "life insurance", "health insurance",
    "car insurance", "home insurance", "insurance agent",
    "insurance broker", "insurance document", "insurance policy",
    "claim form", "claim approval", "coverage plan",
    "financial advisor", "financial planning", "retirement planning",
    "family protection", "safety concept", "peace of mind",
    "signing contract", "agreement handshake", "handshake deal",
    "doctor consultation", "medical support", "hospital",
    "car accident", "road accident", "accident scene",
    "budget planning", "money savings", "piggy bank",
    "modern family home", "family home", "house",
    "office desk", "office meeting", "business meeting",
    "professional", "businessman", "businesswoman",
    "customer service", "help desk", "support",
    "paperwork", "filing documents", "document signing",
    "calculator counting", "counting money", "finance graph",
    "chart", "graph", "statistics", "data analysis",
    "approval stamp", "approved", "signature",
    "phone consultation", "phone call", "calling",
    "online banking", "laptop finance", "digital insurance",
]

# ── Generic concepts REJECTED for insurance content ──────────────────────────
# These concepts are never acceptable when the transcript is about insurance.
# They are generic motivational or unrelated stock concepts that would dilute
# the insurance visual narrative.
GENERIC_REJECTED_CONCEPTS: List[str] = [
    "success", "achievement", "determination", "winner", "champion",
    "sunrise", "mountains", "nature", "landscape", "people",
    "ocean", "beach", "sunset", "forest", "waterfall",
    "meditation", "yoga", "fitness", "workout", "gym",
    "party", "celebration", "fireworks", "confetti",
    "travel", "vacation", "holiday", "adventure",
    "space", "globe", "earth", "universe", "stars",
    "abstract", "colorful", "animation", "background",
    "motivation", "inspiration", "dream", "goal",
    "team building", "leadership", "seminar", "training",
    "podcast", "microphone", "recording studio",
    "dance", "music", "concert", "festival",
    "food", "cooking", "restaurant", "kitchen",
    "fashion", "shopping", "clothes", "model",
    "sports", "running", "cycling", "swimming",
    "gaming", "video game", "esports",
    "pets", "dogs", "cats", "animals",
    "wedding", "romance", "dating", "love",
    "technology abstract", "circuit board", "coding",
    "city skyline", "night city", "street photography",
]


# ── In-memory cache for deep context queries ───────────────────────────────
_DEEP_QUERY_CACHE: Dict[str, List[str]] = {}

# ── B-roll concept feedback tracker ────────────────────────────────────────
# Tracks per-concept performance across tasks using a simple JSON file.
# Fields per concept: uses, avg_watch_pct, avg_retention_drop, completion_rate
_BROLL_FEEDBACK_PATH = Path("/tmp/viraclip_broll_feedback.json")
_BROLL_FEEDBACK_CACHE: Dict[str, Dict[str, float]] = {}

def _load_broll_feedback() -> Dict[str, Dict[str, float]]:
    """Load B-roll concept feedback from JSON file."""
    global _BROLL_FEEDBACK_CACHE
    if _BROLL_FEEDBACK_CACHE:
        return _BROLL_FEEDBACK_CACHE
    if _BROLL_FEEDBACK_PATH.exists():
        try:
            _BROLL_FEEDBACK_CACHE = json.loads(_BROLL_FEEDBACK_PATH.read_text())
        except Exception:
            _BROLL_FEEDBACK_CACHE = {}
    return _BROLL_FEEDBACK_CACHE

def _save_broll_feedback(feedback: Dict[str, Dict[str, float]]) -> None:
    """Save B-roll concept feedback to JSON file."""
    global _BROLL_FEEDBACK_CACHE
    _BROLL_FEEDBACK_CACHE = feedback
    try:
        _BROLL_FEEDBACK_PATH.write_text(json.dumps(feedback, indent=2))
    except Exception as _e:
        logger.debug("[BRoll] Failed to save feedback: %s", _e)

def _record_broll_feedback(
    concept: str,
    watch_pct: float = 0.0,
    retention_drop: float = 0.0,
    completion_rate: float = 0.0,
) -> None:
    """
    Record feedback for a B-roll concept.
    
    Updates running averages for:
    - watch_pct: percentage of viewers who watched through the B-roll
    - retention_drop: drop in retention at B-roll start (negative = bad)
    - completion_rate: rate at which viewers completed the clip
    
    Uses exponential moving average (alpha=0.3) to weight recent data more.
    """
    feedback = _load_broll_feedback()
    key = concept.lower().strip()
    
    if key not in feedback:
        feedback[key] = {
            "uses": 0,
            "avg_watch_pct": 0.0,
            "avg_retention_drop": 0.0,
            "completion_rate": 0.0,
        }
    
    entry = feedback[key]
    uses = entry["uses"]
    alpha = 0.3  # EMA weight for new data
    
    if uses == 0:
        entry["avg_watch_pct"] = watch_pct
        entry["avg_retention_drop"] = retention_drop
        entry["completion_rate"] = completion_rate
    else:
        entry["avg_watch_pct"] = (1 - alpha) * entry["avg_watch_pct"] + alpha * watch_pct
        entry["avg_retention_drop"] = (1 - alpha) * entry["avg_retention_drop"] + alpha * retention_drop
        entry["completion_rate"] = (1 - alpha) * entry["completion_rate"] + alpha * completion_rate
    
    entry["uses"] = uses + 1
    _save_broll_feedback(feedback)
    logger.info(
        "[BRoll] Feedback recorded for '%s': uses=%d watch=%.1f%% drop=%.1f%% complete=%.1f%%",
        key, entry["uses"], entry["avg_watch_pct"],
        entry["avg_retention_drop"], entry["completion_rate"],
    )

def _get_broll_feedback_adjustment(concept: str) -> float:
    """
    Get a multiplier for B-roll frequency based on historical feedback.
    
    Returns:
    - > 1.0: increase frequency (concept performs well)
    - < 1.0: decrease frequency (concept causes drops)
    - 1.0: neutral (no data or average performance)
    """
    feedback = _load_broll_feedback()
    key = concept.lower().strip()
    entry = feedback.get(key)
    
    if not entry or entry["uses"] < 3:
        return 1.0  # not enough data
    
    # Score based on watch_pct and retention_drop
    watch_score = entry["avg_watch_pct"] / 50.0  # 50% = neutral
    drop_score = 1.0 + (entry["avg_retention_drop"] / 10.0)  # -5% drop = 0.5x, +5% = 1.5x
    
    adjustment = (watch_score * 0.6 + drop_score * 0.4)
    adjustment = max(0.3, min(2.0, adjustment))  # clamp to [0.3, 2.0]
    
    logger.info(
        "[BRoll] Feedback adjustment for '%s': watch=%.1f%% drop=%.1f%% → multiplier=%.2f",
        key, entry["avg_watch_pct"], entry["avg_retention_drop"], adjustment,
    )
    return adjustment


class BrollService:
    """AI-powered B-roll injection service."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.broll_dir = Path(self.config.temp_dir) / "uploads/broll"
        self.broll_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. KEYWORD EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _insurance_enriched_keywords(text: str) -> List[str]:
        """Return extra stock-friendly keywords when insurance concepts are present."""
        text_lower = text.lower()
        enriched: List[str] = []
        for trigger, mapped in INSURANCE_KEYWORD_MAP.items():
            if trigger in text_lower:
                for kw in mapped:
                    if kw not in enriched:
                        enriched.append(kw)
        return enriched

    @staticmethod
    def _merge_keywords(primary: List[str], fallback: List[str], limit: int = 6) -> List[str]:
        merged: List[str] = []
        for kw in primary + fallback:
            kw = str(kw).strip()
            if kw and kw not in merged:
                merged.append(kw)
            if len(merged) >= limit:
                break
        return merged

    @staticmethod
    def _filter_insurance_keywords(keywords: List[str], is_insurance_content: bool) -> List[str]:
        """
        Harden b-roll keyword selection for insurance/finance content.

        When *is_insurance_content* is True:
        1. Prefer keywords that match INSURANCE_NATIVE_CONCEPTS (insurance-domain
           objects and situations: policy, claim, coverage, premium, protection,
           family, savings, risk, responsibility, payments, approval, documents,
           contracts, advisor, customer, office, calculator, forms, phone call,
           consultation, and related concrete visuals).
        2. Reject any keyword that matches GENERIC_REJECTED_CONCEPTS (generic
           motivational or unrelated stock concepts like success, achievement,
           determination, winner, champion, sunrise, mountains, nature, etc.).
        3. If ALL keywords are rejected, fall back to insurance_enriched keywords
           from INSURANCE_KEYWORD_MAP (the ES→EN mapped keywords).
        4. If even that yields nothing, return an empty list (no b-roll is better
           than irrelevant b-roll).

        When *is_insurance_content* is False, returns keywords unchanged
        (no-op for non-insurance domains).

        Each rejected keyword is logged with the exact reason.
        """
        if not is_insurance_content:
            return keywords

        if not keywords:
            return keywords

        # Build lowercase sets for matching
        _native_lower = [c.lower() for c in INSURANCE_NATIVE_CONCEPTS]
        _rejected_lower = [c.lower() for c in GENERIC_REJECTED_CONCEPTS]

        kept: List[str] = []
        rejected: List[str] = []

        for kw in keywords:
            kw_lower = kw.lower().strip()

            # Check if keyword matches any rejected concept (substring match)
            _is_rejected = False
            for _rej in _rejected_lower:
                if _rej in kw_lower or kw_lower in _rej:
                    _is_rejected = True
                    rejected.append(kw)
                    logger.info(
                        "[BRoll/InsuranceFilter] ⛔ REJECTED keyword '%s' — "
                        "matches generic rejected concept '%s'. "
                        "Insurance content requires insurance-native visuals.",
                        kw, _rej,
                    )
                    break

            if _is_rejected:
                continue

            # Check if keyword matches any native concept (substring match)
            _is_native = False
            for _nat in _native_lower:
                if _nat in kw_lower or kw_lower in _nat:
                    _is_native = True
                    break

            if _is_native:
                kept.append(kw)
            else:
                # Keyword is neither rejected nor native — log as borderline
                logger.info(
                    "[BRoll/InsuranceFilter] ⚠️ BORDERLINE keyword '%s' — "
                    "not in insurance-native concepts list, but not rejected either. "
                    "Keeping it as it may still support the insurance message.",
                    kw,
                )
                kept.append(kw)

        if rejected:
            logger.info(
                "[BRoll/InsuranceFilter] Filtered %d/%d keywords for insurance content: "
                "kept=%s, rejected=%s",
                len(rejected), len(keywords), kept, rejected,
            )

        # If everything was rejected, fall back to empty list
        # (no b-roll is better than irrelevant b-roll)
        if not kept:
            logger.warning(
                "[BRoll/InsuranceFilter] ⛔ ALL %d keywords rejected for insurance content. "
                "Returning empty list — no b-roll is better than irrelevant b-roll.",
                len(keywords),
            )

        return kept

    async def extract_keywords(
        self,
        text: str,
        video_path: Optional[Path] = None,
        clip_duration: float = 0.0,
    ) -> List[str]:
        """
        Extract 2-3 visual B-roll keywords from *text*.

        If *video_path* is provided, YOLOv10 visual grounding filters out
        keywords whose subject is already visible in the clip — no B-roll
        needed for what the viewer can already see.
        """
        groq_key = os.getenv("GROQ_API_KEY", "")
        insurance_enriched = self._insurance_enriched_keywords(text)
        is_insurance_content = len(insurance_enriched) > 0

        if not groq_key:
            logger.warning("[BRoll] GROQ_API_KEY not set — falling back to first 3 nouns")
            keywords = self._simple_keyword_fallback(text)
            # ── BLOCK FALLBACK PATH A: _simple_keyword_fallback() for insurance content ──
            # When the transcript contains insurance/finance keywords, the generic fallback
            # ["nature", "landscape", "people"] is completely irrelevant. Using it would
            # inject generic stock footage unrelated to insurance concepts, diluting the
            # visual narrative. Instead, use only insurance_enriched keywords.
            if is_insurance_content:
                logger.warning(
                    "[BRoll] ⛔ BLOCKED fallback path A: _simple_keyword_fallback() "
                    "returned %s but transcript contains insurance keywords. "
                    "Generic keywords would inject irrelevant stock footage. "
                    "Using only insurance_enriched keywords: %s",
                    keywords, insurance_enriched,
                )
                merged = insurance_enriched[:3] if insurance_enriched else []
                # ── HARDEN: Apply insurance keyword filter ──
                merged = self._filter_insurance_keywords(merged, is_insurance_content)
                return await self._apply_yolo_filter(merged, video_path, clip_duration)
            merged = self._merge_keywords(insurance_enriched, keywords)
            return await self._apply_yolo_filter(merged, video_path, clip_duration)

        # ── HARDEN: Insurance-specific prompt instructions ──
        # When the transcript is about insurance/finance, the LLM must generate
        # insurance-native concepts (policy, claim, coverage, family protection,
        # office, documents, etc.) and NEVER generic motivational words.
        if is_insurance_content:
            prompt = (
                "You are a video editor choosing B-roll footage for an INSURANCE video. "
                "Read this transcript and extract 2-3 SPECIFIC English search terms for stock video footage. "
                "Rules:\n"
                "- The transcript is in Spanish. Generate your stock footage search "
                "queries in ENGLISH only, as the stock library requires English queries.\n"
                "- The transcript is about INSURANCE. Your keywords MUST be concrete, "
                "action-oriented insurance scenes that a stock library can return.\n"
                "- PREFER these specific visual scenes (choose the one that best matches "
                "what the speaker is describing):\n"
                "  * person signing insurance policy document at desk\n"
                "  * family sitting with insurance advisor in office\n"
                "  * driver exchanging insurance information after car accident\n"
                "  * person filling out claim form on clipboard\n"
                "  * doctor consulting with patient in medical office\n"
                "  * elderly couple reviewing savings plan with agent\n"
                "  * person making phone call while holding insurance card\n"
                "  * hand signing on digital tablet insurance form\n"
                "  * family standing in front of their home\n"
                "  * person reading insurance coverage certificate\n"
                "  * customer paying premium at bank counter\n"
                "  * insurance agent explaining policy to couple at kitchen table\n"
                "  * person using laptop to compare insurance plans online\n"
                "  * car with visible damage being inspected\n"
                "  * paramedic helping person after accident\n"
                "- NEVER use these generic terms (they return irrelevant stock footage):\n"
                "  success, growth, teamwork, leadership, innovation, handshake,\n"
                "  business meeting, city skyline, abstract background, nature,\n"
                "  landscape, mountains, ocean, beach, sunset, forest, meditation,\n"
                "  yoga, fitness, party, travel, space, motivation, inspiration,\n"
                "  winner, achievement, determination, dream, goal, people hugging,\n"
                "  globe, piggy bank, counting money, finance graph, chart.\n"
                "- Choose the most VISUAL and CONCRETE insurance scene the speaker is describing.\n"
                "- Must be searchable on a stock video site (e.g. Pexels, Pixabay).\n"
                "- Reply with ONLY a JSON array, e.g. [\"person signing insurance policy document at desk\", "
                "\"family sitting with insurance advisor in office\"]\n\n"
                f"Transcript: {text[:500]}"
            )
        else:
            prompt = (
                "You are a video editor choosing B-roll footage. "
                "Read this transcript and extract 2-3 SPECIFIC English search terms for stock video footage. "
                "Rules:\n"
                "- The transcript is in Spanish. Generate your stock footage search "
                "queries in ENGLISH only, as the stock library requires English queries.\n"
                "- Keywords MUST directly match a noun/action/place MENTIONED in the transcript\n"
                "- NO generic motivational words (success, winner, achievement, determination)\n"
                "- Choose the most VISUAL and CONCRETE thing the speaker is talking about\n"
                "- Must be searchable on a stock video site (e.g. Pexels, Pixabay)\n"
                "- Reply with ONLY a JSON array, e.g. [\"stock market chart\", \"office meeting\", \"coffee cup\"]\n\n"
                f"Transcript: {text[:500]}"
            )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 60,
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Safer JSON parsing: try to extract array from markdown code blocks first,
                # then try direct json.loads, then try ast.literal_eval for single-quoted strings.
                keywords = []
                try:
                    # Strip markdown code fences if present
                    _clean = content.strip()
                    if _clean.startswith("```"):
                        _clean = _clean.split("\n", 1)[-1]
                        _clean = _clean.rsplit("\n", 1)[0] if "```" in _clean else _clean
                        _clean = _clean.strip()
                    keywords = json.loads(_clean)
                except (json.JSONDecodeError, ValueError):
                    try:
                        import ast
                        keywords = ast.literal_eval(_clean)
                    except (ValueError, SyntaxError):
                        # Last resort: extract quoted strings with regex
                        import re
                        keywords = re.findall(r'"([^"]*)"', _clean)
                        if not keywords:
                            keywords = re.findall(r"'([^']*)'", _clean)
                if isinstance(keywords, list) and len(keywords) > 0:
                    result = [str(k).strip() for k in keywords[:3] if k]
                    merged = self._merge_keywords(insurance_enriched, result)
                    # ── HARDEN: Apply insurance keyword filter ──
                    merged = self._filter_insurance_keywords(merged, is_insurance_content)
                    logger.info(f"[BRoll] Keywords extracted: {merged}")
                    return await self._apply_yolo_filter(merged, video_path, clip_duration)
        except Exception as e:
            logger.warning(f"[BRoll] Keyword extraction failed: {e}")
        # ── BLOCK FALLBACK PATH A (2nd occurrence): _simple_keyword_fallback() for insurance content ──
        # When the Groq API call fails AND the transcript contains insurance/finance keywords,
        # the generic fallback ["nature", "landscape", "people"] is completely irrelevant.
        # Using it would inject generic stock footage unrelated to insurance concepts.
        # Instead, use only insurance_enriched keywords or return empty list.
        if is_insurance_content:
            logger.warning(
                "[BRoll] ⛔ BLOCKED fallback path A (2nd occurrence): "
                "_simple_keyword_fallback() after Groq exception. "
                "Transcript contains insurance keywords. "
                "Generic keywords would inject irrelevant stock footage. "
                "Using only insurance_enriched keywords: %s",
                insurance_enriched,
            )
            merged = insurance_enriched[:3] if insurance_enriched else []
            # ── HARDEN: Apply insurance keyword filter ──
            merged = self._filter_insurance_keywords(merged, is_insurance_content)
            return await self._apply_yolo_filter(merged, video_path, clip_duration)
        fallback = self._simple_keyword_fallback(text)
        merged = self._merge_keywords(insurance_enriched, fallback)
        return await self._apply_yolo_filter(merged, video_path, clip_duration)

    async def extract_deep_context_queries(
        self,
        transcript_window: str,
        cache_key: str = "",
    ) -> List[str]:
        """
        Extract 3 specific, visual stock footage queries from a transcript window.
        
        Uses Groq LLM with a detailed system prompt that forces concrete,
        visual queries tied to what the speaker is actually saying.
        Results are cached per transcript window to avoid repeated API calls.
        
        Args:
            transcript_window: 30-second window of transcript text
            cache_key: Optional cache key (e.g. hash of transcript window)
            
        Returns:
            List of up to 3 English stock footage search queries
        """
        # Check in-memory cache first
        if cache_key:
            _cached = _DEEP_QUERY_CACHE.get(cache_key)
            if _cached:
                logger.info("[BRoll] Deep query cache hit for key '%s'", cache_key[:16])
                return _cached
        
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key or not transcript_window:
            return []
        
        prompt = (
            "You are a video editor. Given this speech transcript excerpt, "
            "generate 3 specific, visual, concrete search queries for stock footage "
            "that would visually illustrate what the speaker is talking about.\n"
            "Rules:\n"
            "- Queries must be in English\n"
            "- Queries must be specific and visual (avoid abstract concepts)\n"
            "- Never use: hands, people, camera, office, generic\n"
            "- Example: if speaker talks about housing prices → "
            "'real estate apartment building', 'house for sale sign', "
            "'mortgage document signing'\n"
            f"Transcript: {transcript_window[:600]}\n"
            "Return JSON: {\"queries\": [\"query1\", \"query2\", \"query3\"]}"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 100,
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"},
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                parsed = json.loads(content)
                queries = parsed.get("queries", [])
                if isinstance(queries, list):
                    result = [str(q).strip() for q in queries[:3] if q]
                    logger.info(
                        "[BROLL] Context window: '%s...' → queries: %s",
                        transcript_window[:80], result,
                    )
                    # Cache result
                    if cache_key:
                        _DEEP_QUERY_CACHE[cache_key] = result
                    return result
        except Exception as e:
            logger.warning(f"[BRoll] Deep context query extraction failed: {e}")
        return []

    async def _apply_yolo_filter(
        self,
        keywords: List[str],
        video_path: Optional[Path],
        clip_duration: float,
    ) -> List[str]:
        """Filter *keywords* using YOLOv10 visual grounding on *video_path*."""
        if not video_path or clip_duration <= 0:
            return keywords
        try:
            from ...domains.detection.yolo_detector import get_visual_context, filter_keywords_with_yolo
            ctx = await get_visual_context(video_path, clip_duration)
            filtered = filter_keywords_with_yolo(keywords, ctx["detected_labels"])
            if filtered != keywords:
                logger.info(
                    "[BRoll] YOLO filtered %d → %d keywords: %s → %s",
                    len(keywords), len(filtered), keywords, filtered,
                )
            return filtered
        except Exception as exc:
            logger.debug("[BRoll] YOLO filter skipped: %s", exc)
            return keywords

    @staticmethod
    def _simple_keyword_fallback(text: str) -> List[str]:
        """Return safe English stock-video keywords as a basic fallback.

        ⛔ BLOCKED for insurance/finance content: This fallback returns generic
        keywords ["nature", "landscape", "people"] that are completely irrelevant
        for insurance/finance transcripts. Callers MUST check
        _insurance_enriched_keywords() first and skip this fallback when
        insurance content is detected.

        The callers in extract_keywords() already enforce this guard at two
        points (lines 280-289 and 334-344). This docstring serves as a
        additional safeguard for any future callers.
        """
        # Always return generic English terms — never pass raw transcript words
        # (which may be in another language and return irrelevant stock footage)
        return ["nature", "landscape", "people"]

    # ──────────────────────────────────────────────────────────────────────────
    # 2. ASSET FETCH (Pexels → Pixabay fallback)
    # ──────────────────────────────────────────────────────────────────────────

    def _is_cache_fresh(self, path: Path) -> bool:
        """Return True if *path* exists and was modified within _CACHE_TTL_DAYS."""
        import time as _time
        if not path.exists() or path.stat().st_size < 1_000:
            return False
        age_days = (_time.time() - path.stat().st_mtime) / 86400
        return age_days <= _CACHE_TTL_DAYS

    async def fetch_broll_asset(self, keyword: str, video_path: Optional[str] = None, task_id: Optional[str] = None, used_urls: Optional[set] = None) -> Optional[Path]:
        """Fetch the most relevant B-roll asset for *keyword*.

        Strategy: controlled by BROLL_MODE env var:
          hybrid (default) — try ComfyUI/LTX first, fallback to stock APIs
          generative       — try ComfyUI/LTX only, fallback to stock on failure/timeout
          stock_only       — skip ComfyUI/LTX entirely, use stock APIs only
        0. If BROLL_MODE is hybrid or generative, try LTX-Video generation first
        1. Query Pexels + Pixabay + Coverr in parallel (best result for this keyword)
        2. If all APIs fail → fall back to Pexels Photos (static image via API)
        3. If all APIs are unavailable (no keys / network error) → use local cache
        Cache is a safety net, not the primary source.

        Anti-repetition: if *used_urls* is provided, skip any asset whose URL
        is already in the set. This prevents the same B-roll appearing in
        multiple clips of the same task.
        """
        if used_urls is None:
            used_urls = set()
        _broll_mode = os.getenv("BROLL_MODE", "hybrid").lower()
        _ltx_enabled = os.getenv("BROLL_USE_LTX", "false").lower() == "true"
        _comfy_enabled = os.getenv("COMFYUI_ENABLED", "false").lower() == "true"
        _comfy_timeout = int(os.getenv("BROLL_COMFYUI_TIMEOUT", "10"))
        _try_generative = _broll_mode in ("hybrid", "generative") and _comfy_enabled and _ltx_enabled
        logger.info(
            "[BRoll] Provider chain for '%s': BROLL_MODE=%s, ComfyUI/LTX=%s → Pexels → Coverr → Pixabay → Cache",
            keyword, _broll_mode, _try_generative,
        )
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        cached_video = self.broll_dir / f"{safe}.mp4"
        cached_photo = self.broll_dir / f"{safe}.jpg"

        _broll_timeout = int(os.getenv("BROLL_TIMEOUT_SECONDS", "30"))

        # ── 0. ComfyUI/LTX-Video generation (BROLL_MODE=hybrid|generative) ───
        if _try_generative and task_id:

            # Try to acquire Redis lock (max 1 concurrent ComfyUI process)
            _lock_acquired = False
            try:
                import redis.asyncio as aioredis
                from ...config import get_config
                _cfg = get_config()
                _r = aioredis.Redis(host=_cfg.redis_host, port=_cfg.redis_port, password=_cfg.redis_password or None, decode_responses=True)
                for _attempt in range(3):
                    _lock_acquired = await _r.set(COMFYUI_LOCK_KEY, "1", nx=True, ex=COMFYUI_LOCK_TIMEOUT_SECONDS)
                    if _lock_acquired:
                        break
                    await asyncio.sleep(2)
                await _r.aclose()
            except Exception:
                logger.warning("[BRoll] Redis unavailable, ComfyUI lock disabled — OOM risk with parallel workers")
                _lock_acquired = True  # proceed without lock

            if not _lock_acquired:
                logger.warning(f"[BRoll] ComfyUI busy (lock held), falling back to Pexels")
            else:
                try:
                    prompt = (
                        f"cinematic B-roll footage of {keyword}, professional quality, smooth motion, 9:16 vertical, "
                        "photorealistic, 4K, cinematic footage, real video, "
                        "sharp focus, professional camera, natural lighting, "
                        "documentary style, high detail"
                    )
                    logger.info(f"🎬 Generating B-roll with ComfyUI/LTX-Video: '{keyword}'")
                    _ltx_result = await asyncio.wait_for(
                        comfyui_integration.process_with_comfyui(
                            task_id=f"{task_id}_broll_{safe}",
                            video_path=None,
                            operation="broll_generate",
                            prompt=prompt,
                            duration=3.0,
                            width=608,
                            height=1088,
                        ),
                        timeout=_broll_timeout,
                    )
                    if _ltx_result and Path(_ltx_result).exists():
                        try:
                            shutil.copy2(_ltx_result, cached_video)
                        except Exception as _copy_e:
                            logger.debug(f"[BRoll] No pude cachear LTX en {cached_video}: {_copy_e}")
                        logger.info(f"[BRoll] ✓ ComfyUI/LTX B-roll generated for '{keyword}': {_ltx_result}")
                        return Path(_ltx_result)
                except asyncio.TimeoutError:
                    logger.warning(f"[BRoll] ComfyUI/LTX timeout after {_broll_timeout}s, trying next")
                except Exception as _ltx_e:
                    logger.warning(f"⚠️ ComfyUI/LTX B-roll failed, falling back to stock footage: {_ltx_e}")
                finally:
                    # Release lock
                    try:
                        _r2 = aioredis.Redis(host=_cfg.redis_host, port=_cfg.redis_port, password=_cfg.redis_password or None, decode_responses=True)
                        await _r2.delete(COMFYUI_LOCK_KEY)
                        await _r2.aclose()
                    except Exception:
                        pass

        # ── 1. Stock video APIs: Pexels + Coverr + Pixabay con rotación ──────
        # Alternate primary source per keyword call to avoid visual monotony.
        global _BROLL_SOURCE_ROTATION
        _BROLL_SOURCE_ROTATION += 1
        _primary_source = _BROLL_SOURCE_ROTATION % 3  # 0=Pexels, 1=Coverr, 2=Pixabay

        # Launch all searches in parallel
        pexels_task  = asyncio.create_task(self._search_pexels(keyword))
        coverr_task  = asyncio.create_task(self._search_coverr(keyword))
        pixabay_task = asyncio.create_task(self._search_pixabay(keyword))

        results = await asyncio.gather(pexels_task, coverr_task, pixabay_task,
                                       return_exceptions=True)
        # Map results to sources
        _source_results = {
            "pexels":  results[0] if isinstance(results[0], str) else None,
            "coverr":  results[1] if isinstance(results[1], str) else None,
            "pixabay": results[2] if isinstance(results[2], str) else None,
        }
        _source_order = ["pexels", "coverr", "pixabay"]
        # Rotate: put primary source first
        _source_order = _source_order[_primary_source:] + _source_order[:_primary_source]

        video_urls = []
        _used_source = None
        for _src in _source_order:
            _url = _source_results.get(_src)
            if _url:
                video_urls.append(_url)
                if _used_source is None:
                    _used_source = _src

        logger.info(
            "[BRoll] Source rotation: primary=%s, used=%s, order=%s",
            _source_order[0], _used_source or "none", _source_order,
        )

        for url in video_urls:
            if url in used_urls:
                logger.info(f"[BRoll] Skipping duplicate URL: {url[:60]}...")
                continue
            # Cross-task Redis blacklist check: skip if used in any previous task
            if await self._redis_url_is_used(url):
                logger.info(f"[BRoll] Skipping Redis-blacklisted URL: {url[:60]}...")
                continue
            result = await self._download(url, cached_video)
            if result:
                used_urls.add(url)
                logger.info(f"[BRoll] API → downloaded video for '{keyword}': {result.name}")
                return result

        # ── 2. Fallback: Pexels Photos API (static image) ─────────────────────
        photo = await self._search_pexels_photos_and_download(keyword, safe)
        if photo:
            logger.info(f"[BRoll] API → downloaded photo for '{keyword}': {photo.name}")
            return photo

        # ── 3. Last resort: local cache (APIs down / no keys) ─────────────────
        if self._is_cache_fresh(cached_video):
            logger.info(f"[BRoll] Cache fallback (video): {cached_video}")
            return cached_video
        if self._is_cache_fresh(cached_photo):
            logger.info(f"[BRoll] Cache fallback (photo): {cached_photo}")
            return cached_photo

        logger.warning(f"[BRoll] No asset found for keyword '{keyword}' (all providers exhausted)")
        return None

    async def _search_pexels_photos_and_download(self, keyword: str, safe_name: str) -> Optional[Path]:
        """Search Pexels Photos API using round-robin key pool.
        Downloads first portrait image found, or None if all keys fail.
        """
        if not _PEXELS_KEYS:
            logger.warning("[BRoll] No Pexels API keys configured for photos")
            return None
        for attempt in range(len(_PEXELS_KEYS)):
            key = _get_next_pexels_key()
            key_index = (_PEXELS_KEY_INDEX - 1) % len(_PEXELS_KEYS)
            try:
                async with httpx.AsyncClient(timeout=BROLL_HTTP_TIMEOUT) as client:
                    resp = await client.get(
                        "https://api.pexels.com/v1/search",
                        headers={"Authorization": key},
                        params={"query": keyword, "per_page": 3, "orientation": "portrait"},
                    )
                    if resp.status_code in (429, 401):
                        logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} (photos) returned {resp.status_code} — skipping")
                        continue
                    resp.raise_for_status()
                    photos = resp.json().get("photos", [])
                    if not photos:
                        continue
                    src = photos[0].get("src", {})
                    photo_url = src.get("portrait") or src.get("large2x") or src.get("large")
                    if not photo_url:
                        continue
                    dest = self.broll_dir / f"{safe_name}.jpg"
                    img_resp = await client.get(photo_url, follow_redirects=True, timeout=_BROLL_DOWNLOAD_TIMEOUT)
                    img_resp.raise_for_status()
                    dest.write_bytes(img_resp.content)
                    logger.info(f"[BROLL_PROVIDER] pexels_key_{key_index} (photos) hit for '{keyword}': {dest.name}")
                    return dest
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 401):
                    logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} (photos) returned {e.response.status_code} — skipping")
                    continue
                logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} (photos) error: {e}")
            except Exception as e:
                logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} (photos) error: {e}")
        logger.warning(f"[BRoll] All Pexels keys exhausted for photo '{keyword}'")
        return None

    @staticmethod
    def _score_pexels_candidate(
        video: dict,
        query: str,
        transcript_context: str = "",
        target_duration: float = 6.0,
    ) -> float:
        """Score a single Pexels video candidate on multiple criteria.

        Returns a score 0.0–1.0. Higher = better match.

        Scoring criteria:
        1. Keyword specificity bonus (0–0.3): how many query words appear in
           the video's user/description tags.
        2. Insurance-native tag bonus (0–0.2): if the query contains insurance
           keywords, boost videos whose tags match insurance-native concepts.
        3. Duration fit (0–0.2): prefer clips close to target_duration.
           Penalize clips > 30s for short windows.
        4. Portrait orientation (0–0.15): prefer h > w (9:16 for Shorts/Reels).
        5. Resolution quality (0–0.15): prefer 1080p over 720p over lower.
        """
        score = 0.0

        # ── 1. Keyword specificity bonus (0–0.3) ──
        query_words = set(query.lower().split())
        # Build tag text from video metadata
        tag_text = (
            (video.get("user") or {}).get("name", "") + " "
            + (video.get("description") or "") + " "
            + (video.get("url") or "")
        ).lower()
        tag_words = set(tag_text.split())
        common = query_words & tag_words
        if query_words:
            specificity = len(common) / len(query_words)
            score += min(0.3, specificity * 0.3)

        # ── 2. Insurance-native tag bonus (0–0.2) ──
        _INSURANCE_TAGS = {
            "insurance", "policy", "claim", "coverage", "premium",
            "protection", "family", "savings", "advisor", "consultation",
            "document", "signing", "contract", "office", "medical",
            "health", "car", "accident", "home", "agent", "broker",
            "financial", "retirement", "planning", "beneficiary",
        }
        insurance_hits = tag_words & _INSURANCE_TAGS
        if insurance_hits:
            score += min(0.2, len(insurance_hits) * 0.04)

        # ── 3. Duration fit (0–0.2) ──
        dur = float(video.get("duration", 0) or 0)
        if dur > 0:
            if dur > 30.0:
                # Penalize clips > 30s for short windows
                score -= 0.15
            else:
                # Prefer clips close to target_duration
                dur_diff = abs(dur - target_duration)
                if dur_diff <= 2.0:
                    score += 0.2
                elif dur_diff <= 5.0:
                    score += 0.1
                else:
                    score += 0.05

        # ── 4. Portrait orientation (0–0.15) ──
        # Check all video_files for portrait orientation
        video_files = video.get("video_files", [])
        has_portrait = any(
            vf.get("height", 0) > vf.get("width", 0)
            for vf in video_files
        )
        if has_portrait:
            score += 0.15

        # ── 5. Resolution quality (0–0.15) ──
        max_height = max(
            (vf.get("height", 0) or 0) for vf in video_files
        ) if video_files else 0
        if max_height >= 1080:
            score += 0.15
        elif max_height >= 720:
            score += 0.10
        elif max_height >= 480:
            score += 0.05

        # ── 6. Narrative strength bonus (0–0.25) ──
        # Boost scenes that show clear subject + clear activity.
        # Penalize generic office shots unless the transcript explicitly calls for them.
        # Prefer action, emotion, and concrete insurance moments.
        _tag_text_lower = tag_text
        _has_action = any(kw in _tag_text_lower for kw in (
            "signing", "shaking", "driving", "talking", "consulting",
            "explaining", "reviewing", "filling", "reading", "calling",
            "paying", "inspecting", "helping", "discussing", "meeting",
            "walking", "sitting", "working", "typing", "writing",
        ))
        _has_emotion = any(kw in _tag_text_lower for kw in (
            "happy", "smiling", "concerned", "worried", "relieved",
            "grateful", "thoughtful", "focused", "caring", "supportive",
        ))
        _has_concrete_subject = any(kw in _tag_text_lower for kw in (
            "person", "people", "man", "woman", "couple", "family",
            "doctor", "patient", "driver", "agent", "advisor", "broker",
            "customer", "client", "elderly", "parent", "child",
        ))
        _is_generic_office = any(kw in _tag_text_lower for kw in (
            "office", "desk", "computer", "laptop", "cubicle",
        )) and not any(kw in _tag_text_lower for kw in (
            "signing", "consulting", "explaining", "meeting", "talking",
            "advisor", "agent", "customer", "client",
        ))

        if _has_action and _has_concrete_subject:
            score += 0.25  # Best: person doing something
        elif _has_action:
            score += 0.15  # Good: action happening
        elif _has_concrete_subject and _has_emotion:
            score += 0.15  # Good: person with emotion
        elif _has_concrete_subject:
            score += 0.10  # OK: person present
        elif _has_emotion:
            score += 0.05  # Weak: emotion without subject

        if _is_generic_office:
            score -= 0.20  # Penalize: generic office with no clear activity

        return max(0.0, min(1.0, score))

    async def _search_pexels(self, query: str, transcript_context: str = "") -> Optional[str]:
        """Search Pexels Videos API using round-robin key pool.
        Scores ALL candidates and returns the best match URL, or None if all keys fail.

        Scoring criteria (see _score_pexels_candidate):
        - Keyword specificity bonus
        - Insurance-native tag bonus
        - Duration fit (penalize clips > 30s for short windows)
        - Portrait orientation preference
        - Resolution quality preference

        Args:
            query: Search keyword for Pexels
            transcript_context: The transcript text spoken at this moment (for logging)
        """
        if not _PEXELS_KEYS:
            logger.warning("[BRoll] No Pexels API keys configured")
            return None

        # Collect all candidates across all API keys
        all_candidates: List[Tuple[float, str, str]] = []  # (score, url, log_label)

        for attempt in range(len(_PEXELS_KEYS)):
            key = _get_next_pexels_key()
            key_index = (_PEXELS_KEY_INDEX - 1) % len(_PEXELS_KEYS)
            try:
                async with httpx.AsyncClient(timeout=BROLL_HTTP_TIMEOUT) as client:
                    resp = await client.get(
                        "https://api.pexels.com/videos/search",
                        headers={"Authorization": key},
                        params={"query": query, "per_page": 5, "orientation": "portrait"},
                    )
                    if resp.status_code in (429, 401):
                        logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} returned {resp.status_code} — skipping")
                        continue
                    resp.raise_for_status()
                    videos = resp.json().get("videos", [])
                    n_results = len(videos)
                    logger.info(
                        "[BROLL] Query='%s' for transcript='%s' → %d results found",
                        query, transcript_context[:60], n_results,
                    )
                    if not videos:
                        logger.info(f"[BROLL_PROVIDER] pexels_key_{key_index} returned empty results for '{query}'")
                        continue

                    # Score each video candidate
                    for vid in videos:
                        score = self._score_pexels_candidate(
                            vid, query, transcript_context,
                            target_duration=6.0,
                        )
                        # Find the best video_file URL for this candidate
                        best_url = None
                        best_label = None
                        for vf in vid.get("video_files", []):
                            w, h = vf.get("width", 0), vf.get("height", 0)
                            if h > w and vf.get("file_type") == "video/mp4":
                                best_url = vf["link"]
                                best_label = f"pexels_key_{key_index}"
                                break
                        if not best_url:
                            files = vid.get("video_files", [])
                            if files:
                                best_url = files[0]["link"]
                                best_label = f"pexels_key_{key_index}_fallback"

                        if best_url:
                            all_candidates.append((score, best_url, best_label or "pexels"))

            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 401):
                    logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} returned {e.response.status_code} — skipping")
                    continue
                logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} error: {e}")
            except Exception as e:
                logger.warning(f"[BROLL_PROVIDER] pexels_key_{key_index} error: {e}")

        if not all_candidates:
            logger.warning(f"[BRoll] All Pexels keys exhausted for '{query}'")
            return None

        # Sort by score descending, return the best
        all_candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_url, best_label = all_candidates[0]

        # ── Minimum score threshold: reject candidates with score < 0.40 ──
        # A score-0.0 candidate has no keyword overlap, wrong orientation,
        # or wrong duration — it would produce unrelated B-roll.
        if best_score < 0.40:
            logger.warning(
                "[BrollGate] PEXELS REJECT query='%s' best_score=%.3f < 0.40 — "
                "no suitable candidate found (evaluated %d)",
                query, best_score, len(all_candidates),
            )
            return None

        logger.info(
            "[BROLL] Best match for '%s': score=%.3f from %s — %s... "
            "(evaluated %d candidates)",
            query, best_score, best_label, best_url[:60], len(all_candidates),
        )
        return best_url

    async def _search_coverr(self, query: str) -> Optional[str]:
        """Search Coverr CC0 video library."""
        # Check config first (allows session-level disable), then env
        key = self.config.coverr_api_key or os.getenv("COVERR_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=BROLL_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    "https://api.coverr.co/videos",
                    params={"keywords": query, "api_key": key, "per_page": 5},
                )
                if resp.status_code == 401:
                    logger.warning("[BRoll] Coverr API key invalid (401) — disabling Coverr for this session")
                    # Disable Coverr by clearing the key in this config instance
                    self.config.coverr_api_key = ""
                    return None
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("hits", []):
                    # Prefer clips with portrait dimensions and duration 3-10s
                    dur = item.get("duration", 0)
                    w   = item.get("width", 0)
                    h   = item.get("height", 0)
                    url = item.get("urls", {}).get("mp4_download") or item.get("url")
                    if url and 3 <= dur <= 12 and h >= 720:
                        logger.info(f"[BRoll] Coverr hit for '{query}': {url[:60]}...")
                        return url
                # Any clip if none match portrait preference
                for item in data.get("hits", []):
                    url = item.get("urls", {}).get("mp4_download") or item.get("url")
                    if url:
                        return url
        except Exception as e:
            logger.debug(f"[BRoll] Coverr search error: {e}")
        return None

    async def _search_pixabay(self, query: str) -> Optional[str]:
        key = self.config.pixabay_api_key or os.getenv("PIXABAY_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=BROLL_HTTP_TIMEOUT) as client:
                resp = await client.get(
                    "https://pixabay.com/api/videos/",
                    params={
                        "key": key,
                        "q": query,
                        "video_type": "film",
                        "orientation": "vertical",
                        "per_page": 3,
                    },
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                if not hits:
                    return None
                videos = hits[0].get("videos", {})
                for size in ("medium", "small", "large"):
                    url = videos.get(size, {}).get("url")
                    if url:
                        logger.info(f"[BROLL_PROVIDER] pixabay hit for '{query}': {url[:60]}...")
                        return url
        except Exception as e:
            logger.warning(f"[BROLL_PROVIDER] pixabay error: {e}")
        return None

    async def _download(self, url: str, dest: Path) -> Optional[Path]:
        try:
            async with httpx.AsyncClient(timeout=_BROLL_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            f.write(chunk)
            logger.info(f"[BRoll] Downloaded: {dest} ({dest.stat().st_size // 1024} KB)")
            return dest
        except Exception as e:
            logger.error(f"[BRoll] Download failed {url[:60]}: {e}")
            dest.unlink(missing_ok=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 3. SILENCE DETECTION
    # ──────────────────────────────────────────────────────────────────────────

    def detect_silences(
        self,
        audio_path: str,
        min_duration: float = _MIN_SILENCE_SEC,
    ) -> List[Tuple[float, float]]:
        """Return list of (start, end) silence gaps >= *min_duration* seconds."""
        try:
            import librosa
            import numpy as np

            y, sr = librosa.load(audio_path, sr=16000, mono=True)
            rms = librosa.feature.rms(y=y, frame_length=512, hop_length=256)[0]
            times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=256)

            threshold = float(np.percentile(rms, 15))  # bottom 15% = silence
            silences: List[Tuple[float, float]] = []
            in_silence = False
            silence_start = 0.0

            for i, (t, energy) in enumerate(zip(times, rms)):
                if energy < threshold and not in_silence:
                    in_silence = True
                    silence_start = float(t)
                elif energy >= threshold and in_silence:
                    in_silence = False
                    duration = float(t) - silence_start
                    if duration >= min_duration:
                        silences.append((silence_start, float(t)))

            logger.info(f"[BRoll] Detected {len(silences)} silence gaps >= {min_duration}s")
            return silences
        except Exception as e:
            logger.warning(f"[BRoll] Silence detection failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # 4. FFMPEG OVERLAY INSERTION
    # ──────────────────────────────────────────────────────────────────────────

    async def insert_broll(
        self,
        video_path: str,
        output_path: str,
        broll_path: str,
        timestamp: float,
        overlay_duration: float = _BROLL_DURATION,
        fade: float = _FADE_DURATION,
        lut_vf: str = "",
    ) -> bool:
        """
        Overlay *broll_path* on *video_path* at *timestamp* for *overlay_duration* seconds.
        Delegates to broll_compositor.compose_overlay for format-adaptive scaling.
        If *lut_vf* is provided, applies the same LUT grade to the B-roll before overlay.

        FIX 3A: Validates broll asset duration >= BROLL_MIN_DURATION_S before inserting.
        FIX 3C: Runs ffprobe post-insertion to validate output file integrity.

        MINIMUM DURATION ENFORCEMENT: overlay_duration is clamped to >= BROLL_MIN_OVERLAY_DURATION_S.
        Ideal range is 2.5–5.0s per insertion.

        Returns True on success.
        """
        try:
            # ── Clamp overlay_duration to minimum BROLL_MIN_OVERLAY_DURATION_S ──
            if overlay_duration < BROLL_MIN_OVERLAY_DURATION_S:
                logger.warning(
                    "[BRoll] Clamping overlay_duration from %.2fs to %.2fs (min=%.1fs) — %s",
                    overlay_duration, BROLL_MIN_OVERLAY_DURATION_S, BROLL_MIN_OVERLAY_DURATION_S, broll_path,
                )
                overlay_duration = BROLL_MIN_OVERLAY_DURATION_S

            # ── Guard: skip overlay if final duration <= 0 ──────────────────────
            if overlay_duration <= 0:
                logger.warning(
                    "[BRoll] Skipping broll overlay (duration <= 0): %.2fs — %s",
                    overlay_duration, broll_path,
                )
                return False

            # ── FIX 3A: Duration validation ────────────────────────────────────
            _broll_dur = probe_duration(broll_path)
            if _broll_dur < _BROLL_MIN_DURATION_S:
                logger.warning(
                    "[BRoll] Skipping broll asset (too short): %s — "
                    "duration=%.2fs < min=%.2fs",
                    broll_path, _broll_dur, _BROLL_MIN_DURATION_S,
                )
                return False

            ok = compose_overlay(
                main_path=video_path,
                broll_path=broll_path,
                output_path=output_path,
                timestamp=timestamp,
                duration=overlay_duration,
                fade=fade,
                lut_vf=lut_vf,
            )
            if ok:
                logger.info(f"[BRoll] ✓ Overlay inserted at t={timestamp:.1f}s → {output_path}")
                # ── FIX 3C: Post-insertion ffprobe validation ──────────────────
                try:
                    _post_dur = probe_duration(output_path)
                    if _post_dur < 0.5:
                        logger.error(
                            "[BRoll] Post-insertion validation FAILED: "
                            "output duration=%.2fs (too short) — %s",
                            _post_dur, output_path,
                        )
                        return False
                    logger.debug(
                        "[BRoll] Post-insertion validation OK: "
                        "output duration=%.2fs — %s",
                        _post_dur, output_path,
                    )
                except Exception as _probe_e:
                    logger.warning(
                        "[BRoll] Post-insertion ffprobe check skipped: %s",
                        _probe_e,
                    )
            else:
                logger.error(f"[BRoll] compose_overlay returned False for {video_path}")
            return ok
        except Exception as e:
            logger.error(f"[BRoll] insert_broll exception: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # ANTI-REPETITION PERSISTENCE (Redis ZSET — persists across tasks & restarts)
    # ──────────────────────────────────────────────────────────────────────────

    _BROLL_BLACKLIST_KEY = "broll:used_urls"
    _BROLL_BLACKLIST_MAX = 200
    _BROLL_BLACKLIST_TRIM = 50  # remove oldest 50 when over max

    async def _redis_add_url(self, url: str) -> None:
        """Add *url* to the global Redis B-roll blacklist ZSET with current timestamp."""
        try:
            from ...utils.redis_pool import get_redis_client
            r = await get_redis_client()
            now = __import__("time").time()
            await r.zadd(self._BROLL_BLACKLIST_KEY, {url: now})
            # Check size cap — if over max, remove oldest N
            _card = await r.zcard(self._BROLL_BLACKLIST_KEY)
            if _card > self._BROLL_BLACKLIST_MAX:
                _remove_count = min(self._BROLL_BLACKLIST_TRIM, _card - self._BROLL_BLACKLIST_MAX)
                # Remove the oldest entries (lowest scores)
                _members = await r.zrange(self._BROLL_BLACKLIST_KEY, 0, _remove_count - 1)
                if _members:
                    await r.zrem(self._BROLL_BLACKLIST_KEY, *_members)
                    logger.info(
                        "[BRoll] Redis blacklist cap hit (%d > %d) — removed %d oldest URLs",
                        _card, self._BROLL_BLACKLIST_MAX, len(_members),
                    )
        except Exception as _e:
            logger.debug("[BRoll] Redis blacklist add failed: %s", _e)

    async def _redis_url_is_used(self, url: str) -> bool:
        """Return True if *url* is already in the global Redis B-roll blacklist."""
        try:
            from ...utils.redis_pool import get_redis_client
            r = await get_redis_client()
            _score = await r.zscore(self._BROLL_BLACKLIST_KEY, url)
            return _score is not None
        except Exception as _e:
            logger.debug("[BRoll] Redis blacklist check failed: %s", _e)
            return False

    async def _load_used_urls(self, task_id: str) -> set:
        """Load persisted used_urls set for *task_id* from Redis ZSET.
        
        Loads all URLs from the global Redis blacklist that were previously
        used in any task, so they are never selected again.
        """
        try:
            from ...utils.redis_pool import get_redis_client
            r = await get_redis_client()
            _members = await r.zrange(self._BROLL_BLACKLIST_KEY, 0, -1)
            if _members:
                logger.info("[BRoll] Loaded %d globally blacklisted URLs for task '%s'", len(_members), task_id)
                return set(m.decode() if isinstance(m, bytes) else m for m in _members)
        except Exception as _e:
            logger.debug("[BRoll] Redis blacklist load failed: %s", _e)
        return set()

    async def _save_used_urls(self, task_id: str, used_urls: set):
        """Persist used_urls set for *task_id* to Redis ZSET.
        
        Each URL in *used_urls* is added to the global Redis blacklist so it
        is never selected again in any future task.
        """
        for _url in used_urls:
            await self._redis_add_url(_url)
        if used_urls:
            logger.info("[BRoll] Synced %d URLs to Redis blacklist for task '%s'", len(used_urls), task_id)

    # ── Generic / low-information concepts that should never trigger B-roll ──
    _GENERIC_CONCEPTS: set = {
        "success", "achievement", "motivation", "inspiration", "dream", "goal",
        "future", "life", "journey", "path", "way", "change", "growth",
        "power", "strength", "energy", "focus", "mindset", "vision",
        "opportunity", "potential", "purpose", "passion", "excellence",
        "greatness", "freedom", "happiness", "peace", "love", "hope",
        "faith", "trust", "believe", "confidence", "courage", "determination",
        "persistence", "commitment", "dedication", "discipline", "wisdom",
        "knowledge", "learning", "experience", "adventure", "discovery",
        "people", "person", "man", "woman", "child", "family", "friend",
        "community", "world", "nature", "beauty", "art", "music", "creative",
        "idea", "solution", "result", "benefit", "value", "quality",
        "service", "support", "care", "help", "guide", "plan", "strategy",
        "step", "tip", "trick", "secret", "truth", "reality", "simple",
        "easy", "fast", "best", "top", "ultimate", "essential", "important",
        "key", "main", "major", "big", "great", "amazing", "incredible",
        "unbelievable", "extraordinary", "remarkable", "outstanding",
        "professional", "expert", "specialist", "leader", "pioneer",
        "innovation", "technology", "digital", "online", "modern",
        "abstract", "background", "texture", "pattern", "design",
        "sunrise", "sunset", "mountain", "ocean", "beach", "sky",
        "city", "urban", "nature", "landscape", "scenery",
    }

    @staticmethod
    def _is_generic_concept(keyword: str) -> bool:
        """Return True if *keyword* is a generic/low-information concept unsuitable for B-roll."""
        _kw = keyword.lower().strip()
        if _kw in BrollService._GENERIC_CONCEPTS:
            return True
        # Check multi-word keywords: if ALL words are generic, reject
        _words = _kw.split()
        if len(_words) > 1:
            _generic_count = sum(1 for w in _words if w in BrollService._GENERIC_CONCEPTS)
            if _generic_count == len(_words):
                return True
        return False

    @staticmethod
    def _score_broll_candidate(
        segment_text: str,
        visual_keywords: List[str],
        asset_tags: str,
    ) -> float:
        """
        Score how well a B-roll asset matches the segment content.
        
        Two paths:
        A) Embeddings (if sentence-transformers available): cosine similarity
           between segment text and asset tags/description.
        B) Keyword fallback: count matching keywords between segment/visual_keywords
           and asset tags.
        
        Returns score 0.0-1.0. Threshold for acceptance: >= 0.50 (embeddings)
        or >= 0.35 (keyword fallback).
        
        HARDENED: Also penalises generic/low-information concepts so they
        score below threshold and get filtered out.
        """
        _use_embeddings = os.getenv("BROLL_USE_EMBEDDINGS", "true").lower() == "true"
        
        # ── Path A: Embeddings ──
        if _use_embeddings:
            try:
                from ...video_processing.narrative_cut_engine import get_sentence_model
                _model, _util = get_sentence_model()
                _seg_emb = _model.encode(segment_text[:512])
                _tag_emb = _model.encode(asset_tags[:512])
                _score = float(_util.cos_sim(_seg_emb, _tag_emb).item())
                # Clamp to [0, 1]
                _score = max(0.0, min(1.0, _score))
                # ── HARDENED: Penalise generic concepts ──
                if BrollService._is_generic_concept(asset_tags):
                    _score *= 0.5
                    logger.debug("[BRoll] Generic concept penalty applied to '%s': score=%.2f", asset_tags[:40], _score)
                return _score
            except (ImportError, Exception) as _emb_e:
                logger.debug("[BRoll] Embedding scoring unavailable: %s — falling back to keywords", _emb_e)
        
        # ── Path B: Keyword fallback ──
        _seg_lower = segment_text.lower()
        _tags_lower = asset_tags.lower()
        _score = 0.0
        
        # Check visual_keywords against asset tags (higher weight)
        for kw in visual_keywords:
            if kw.lower() in _tags_lower:
                _score += 0.4
        
        # Check segment text words against asset tags
        _seg_words = set(_seg_lower.split())
        _tag_words = set(_tags_lower.split())
        _common = _seg_words & _tag_words
        _score += len(_common) * 0.1
        
        # ── HARDENED: Penalise generic concepts ──
        if BrollService._is_generic_concept(asset_tags):
            _score *= 0.5
            logger.debug("[BRoll] Generic concept penalty applied to '%s': score=%.2f", asset_tags[:40], _score)
        
        return min(1.0, _score)

    @staticmethod
    def _snap_to_narrative_boundary(
        ts: float,
        entry_points: List[float],
        exit_points: List[float],
        clip_duration: float,
        max_shift: float = 1.5,
    ) -> Optional[float]:
        """Snap a B-roll timestamp to the nearest narrative entry point.

        Rules:
        - Prefer entry at sentence start or post-pause (≥ 0.4s gap).
        - Do not shift by more than *max_shift* seconds.
        - Do not snap to an entry point that is inside the hook zone (< 2.0s).
        - Do not snap to an entry point that is inside the CTA zone (last 2s).
        - If no suitable entry point is found within max_shift, return None
          (caller should use the original timestamp).

        Args:
            ts: Original B-roll timestamp.
            entry_points: List of narrative entry points (sentence starts, post-pause).
            exit_points: List of narrative exit points (sentence ends).
            clip_duration: Total clip duration in seconds.
            max_shift: Maximum allowed shift in seconds.

        Returns:
            Snapped timestamp, or None if no suitable entry point found.
        """
        if not entry_points:
            return None

        _hook_end = 2.0
        _cta_start = max(0.0, (clip_duration or 0) - 2.0)

        # Find the nearest entry point within max_shift
        best_entry = None
        best_dist = float('inf')
        for ep in entry_points:
            dist = abs(ep - ts)
            if dist <= max_shift and dist < best_dist:
                # Skip entry points in hook or CTA zone
                if ep < _hook_end or (_cta_start > 0 and ep >= _cta_start):
                    continue
                best_entry = ep
                best_dist = dist

        if best_entry is not None:
            logger.debug(
                "[BRoll] Narrative snap: t=%.1fs → t=%.1fs (shift=%.2fs, entry point)",
                ts, best_entry, best_entry - ts,
            )
            return best_entry

        return None

    @staticmethod
    def _detect_micro_moment_cues(
        words_with_timestamps: List[Dict],
        clip_duration: float,
        max_cues: int = 4,
    ) -> List[Dict]:
        """
        Detect micro-moments in the transcript that are strong B-roll candidates.
        
        Scans word-level timestamps for:
        - Named entities (capitalized words that are not sentence-starts)
        - Numbers (digits or number words)
        - Product names (unusual capitalized compounds)
        - Claims (words like "because", "the reason", "that's why", "actually")
        - Surprise markers (words like "increíble", "sorprendente", "wow", "nunca", "siempre")
        
        Returns list of cue dicts with:
        - start_time: float (centered on the micro-moment)
        - duration_s: float (default 6.0)
        - concept: str
        - keywords: List[str]
        - reason: str
        """
        if not words_with_timestamps:
            return []
        
        # Patterns to detect
        _SURPRISE_WORDS = {
            "increíble", "sorprendente", "impresionante", "brutal", "alucinante",
            "wow", "guau", "nunca", "siempre", "jamás", "nadie", "todos",
            "shocking", "surprising", "amazing", "unbelievable", "crazy",
            "insane", "incredible", "mind-blowing", "whoa",
        }
        _CLAIM_MARKERS = {
            "because", "porque", "the reason", "la razón", "that's why",
            "por eso", "es por eso", "actually", "en realidad",
            "the truth is", "la verdad es", "the secret", "el secreto",
            "here's why", "te digo por qué", "nadie te dice",
        }
        _NUMBER_PATTERN = re.compile(r"\d+")
        
        cues = []
        seen_times = set()
        
        for i, w in enumerate(words_with_timestamps):
            text = (w.get("word") or w.get("text") or "").strip()
            start = float(w.get("start", 0))
            end = float(w.get("end", 0))
            
            if not text or start < 0.5:  # skip hook zone
                continue
            
            # Round timestamp to avoid duplicates
            ts_rounded = round(start, 1)
            if ts_rounded in seen_times:
                continue
            
            text_lower = text.lower().strip(".,!?;:'\"")
            reason = None
            concept = None
            keywords = []
            
            # 1. Numbers
            if _NUMBER_PATTERN.search(text):
                reason = f"speaker mentions number '{text}' at t={start:.1f}s"
                concept = f"number {text}"
                keywords = [f"number {text}", "statistics", "data visualization"]
            
            # 2. Surprise markers
            if not reason and text_lower in _SURPRISE_WORDS:
                reason = f"surprise marker '{text}' at t={start:.1f}s"
                concept = f"surprise reaction"
                keywords = ["surprise reaction", "shock expression", "amazement"]
            
            # 3. Named entities (capitalized, not at sentence start)
            if not reason and text[0].isupper() and i > 0:
                prev_text = (words_with_timestamps[i-1].get("word") or "").strip()
                prev_end = words_with_timestamps[i-1].get("end", 0)
                # Check if it's not a sentence start (previous word ends with period)
                if prev_text and not prev_text.endswith("."):
                    reason = f"named entity '{text}' at t={start:.1f}s"
                    concept = text
                    keywords = [text.lower(), f"{text} concept"]
            
            # 4. Claims
            if not reason:
                # Check 1-2 word claim markers
                if text_lower in _CLAIM_MARKERS:
                    reason = f"claim marker '{text}' at t={start:.1f}s"
                    concept = "key claim"
                    keywords = ["key point", "important claim", "revelation"]
                elif i + 1 < len(words_with_timestamps):
                    two_words = text_lower + " " + (words_with_timestamps[i+1].get("word") or "").lower().strip(".,!?;:'\"")
                    if two_words in _CLAIM_MARKERS:
                        reason = f"claim marker '{two_words}' at t={start:.1f}s"
                        concept = "key claim"
                        keywords = ["key point", "important claim", "revelation"]
            
            if reason:
                seen_times.add(ts_rounded)
                cues.append({
                    "start_time": start,
                    "duration_s": 6.0,
                    "concept": concept or "visual moment",
                    "keywords": keywords or ["visual moment"],
                    "reason": reason,
                })
                if len(cues) >= max_cues:
                    break
        
        if cues:
            logger.info(
                "[BRoll] Micro-moment detection: %d cues found: %s",
                len(cues), [c["reason"] for c in cues],
            )
        return cues

    @staticmethod
    def _align_to_beats(
        cues: List[Dict],
        beat_timestamps: Optional[List[float]] = None,
        emphasis_words: Optional[List[Dict]] = None,
        clip_duration: float = 0.0,
    ) -> List[Dict]:
        """
        Align B-roll cues to audio beats and emphasis words.
        
        When an emphasis word or hook is detected:
        - Schedule a short SFX hit at the emphasis word timestamp
        - Start the B-roll within 0.2s after the SFX hit
        - Prefer aligning to the nearest beat if beat data exists
        - Do not add SFX if it would overlap with speech clarity
        
        Returns cues with adjusted timestamps and optional SFX metadata.
        """
        if not cues:
            return []
        
        _SFX_OFFSET = 0.2  # B-roll starts 0.2s after SFX hit
        _BEAT_WINDOW = 0.15  # snap to nearest beat within 150ms
        
        # Build set of emphasis word timestamps
        _emphasis_ts = set()
        if emphasis_words:
            for ew in emphasis_words:
                ts = float(ew.get("start", 0))
                if ts > 0.5:  # skip hook zone
                    _emphasis_ts.add(ts)
        
        result = []
        for cue in cues:
            ts = cue.get("timestamp", 0)
            adjusted_ts = ts
            
            # 1. Check if this cue aligns with an emphasis word
            _nearest_emphasis = None
            for ets in _emphasis_ts:
                if abs(ts - ets) < 1.0:  # within 1s of emphasis word
                    _nearest_emphasis = ets
                    break
            
            if _nearest_emphasis is not None:
                # Schedule SFX at emphasis word, B-roll 0.2s after
                adjusted_ts = _nearest_emphasis + _SFX_OFFSET
                cue["sfx_hit"] = _nearest_emphasis
                cue["sfx_type"] = "emphasis"
                logger.info(
                    "[BRoll] Beat alignment: cue at t=%.1fs → emphasis at t=%.1fs + %.1fs offset",
                    ts, _nearest_emphasis, _SFX_OFFSET,
                )
            
            # 2. Snap to nearest beat if beat data exists
            if beat_timestamps and _nearest_emphasis is None:
                for bt in beat_timestamps:
                    if abs(adjusted_ts - bt) < _BEAT_WINDOW:
                        adjusted_ts = bt
                        logger.info(
                            "[BRoll] Beat snap: cue at t=%.1fs → beat at t=%.1fs",
                            ts, bt,
                        )
                        break
            
            # 3. Ensure we don't overlap with speech clarity
            # (skip if adjusted timestamp is within 0.3s of another cue)
            _overlap = False
            for existing in result:
                if abs(adjusted_ts - existing.get("timestamp", 0)) < 0.3:
                    _overlap = True
                    break
            if _overlap:
                logger.info(
                    "[BRoll] Skipped beat alignment for cue at t=%.1fs (overlap with existing)",
                    ts,
                )
                adjusted_ts = ts  # revert to original
            
            cue["timestamp"] = round(adjusted_ts, 2)
            result.append(cue)
        
        return result

    @staticmethod
    def _assign_shot_progression(
        cues: List[Dict],
    ) -> List[Dict]:
        """
        Assign shot types and motion hints to B-roll cues for visual momentum.
        
        Rules:
        - Prefer shot progression: wide → medium → closeup
        - Avoid repeating the same shot type twice in a row
        - Assign motion hints based on shot type
        - If the asset is static or weak, skip it (return empty list)
        
        Shot types: "wide", "medium", "closeup"
        Motion hints: "zoom_in", "slow_pan", "crop_reframe", "ken_burns", "none"
        """
        if not cues:
            return []
        
        _SHOT_CYCLE = ["wide", "medium", "closeup"]
        _MOTION_MAP = {
            "wide": "slow_pan",
            "medium": "ken_burns",
            "closeup": "zoom_in",
        }
        
        result = []
        last_shot = None
        
        for i, cue in enumerate(cues):
            # Determine shot type: cycle through wide → medium → closeup
            # but skip if it would repeat the last shot
            shot_idx = i % len(_SHOT_CYCLE)
            shot_type = _SHOT_CYCLE[shot_idx]
            
            # Avoid repeating the same shot type
            if shot_type == last_shot:
                # Try next in cycle
                shot_idx = (shot_idx + 1) % len(_SHOT_CYCLE)
                shot_type = _SHOT_CYCLE[shot_idx]
            
            # Assign motion hint based on shot type
            motion_hint = _MOTION_MAP.get(shot_type, "ken_burns")
            
            # For the first cue, prefer wide establishing shot
            if i == 0:
                shot_type = "wide"
                motion_hint = "slow_pan"
            
            # For the last cue, prefer closeup for impact
            if i == len(cues) - 1 and len(cues) > 1:
                shot_type = "closeup"
                motion_hint = "zoom_in"
            
            last_shot = shot_type
            
            cue["shot_type"] = shot_type
            cue["motion_hint"] = motion_hint
            result.append(cue)
        
        logger.info(
            "[BRoll] Shot progression: %s",
            [(c.get("timestamp", 0), c.get("shot_type"), c.get("motion_hint")) for c in result],
        )
        return result

    @staticmethod
    def _classify_broll_modes(
        pairs: List[Tuple[float, str, float]],
        silence_gaps: List[Tuple[float, float]],
        clip_duration: float = 0.0,
    ) -> List[Dict]:
        """
        Classify each B-roll cue into OVERLAY_MODE or MONTAGE_MODE.
        
        OVERLAY_MODE:
        - Use during continuous speech (no silence gap nearby).
        - Duration 5 to 8 seconds.
        - Must have semantic relevance.
        
        MONTAGE_MODE:
        - Use only inside silence gaps longer than 0.6s.
        - Duration 2 to 3 seconds.
        - Use only if the clip already has at least one OVERLAY_MODE cue.
        
        Returns list of dicts with: timestamp, asset_path, duration, mode.
        """
        if not pairs:
            return []
        
        _MIN_SILENCE_FOR_MONTAGE = 0.6
        _OVERLAY_MIN_DUR = 5.0
        _OVERLAY_MAX_DUR = 8.0
        _MONTAGE_MIN_DUR = 3.0
        _MONTAGE_MAX_DUR = 4.0
        
        # Step 1: Classify each pair
        overlay_cues = []
        montage_cues = []
        
        for ts, asset, dur in pairs:
            # Check if this timestamp falls within a silence gap
            in_silence = False
            for s_start, s_end in silence_gaps:
                if s_start <= ts <= s_end:
                    in_silence = True
                    break
            
            if in_silence:
                # MONTAGE_MODE candidate
                montage_dur = max(_MONTAGE_MIN_DUR, min(_MONTAGE_MAX_DUR, dur))
                montage_cues.append({
                    "timestamp": ts,
                    "asset_path": asset,
                    "duration": montage_dur,
                    "mode": "MONTAGE",
                })
            else:
                # OVERLAY_MODE candidate
                overlay_dur = max(_OVERLAY_MIN_DUR, min(_OVERLAY_MAX_DUR, dur))
                overlay_cues.append({
                    "timestamp": ts,
                    "asset_path": asset,
                    "duration": overlay_dur,
                    "mode": "OVERLAY",
                })
        
        # Step 2: MONTAGE_MODE requires at least one OVERLAY_MODE cue
        if not overlay_cues:
            logger.info("[BRoll] No OVERLAY cues — discarding %d MONTAGE cues", len(montage_cues))
            montage_cues = []
        
        # Step 3: Merge and sort by timestamp
        all_cues = overlay_cues + montage_cues
        all_cues.sort(key=lambda c: c["timestamp"])
        
        # Log mode distribution
        n_overlay = sum(1 for c in all_cues if c["mode"] == "OVERLAY")
        n_montage = sum(1 for c in all_cues if c["mode"] == "MONTAGE")
        logger.info(
            "[BRoll] Mode classification: %d OVERLAY + %d MONTAGE = %d total cues",
            n_overlay, n_montage, len(all_cues),
        )
        
        return all_cues

    @staticmethod
    def _sanitize_broll_timeline(
        pairs: List[Tuple[float, str, float]],
        clip_duration: float = 0.0,
        semantic_opportunities: int = 0,
    ) -> List[Tuple[float, str, float]]:
        """
        HARDENED: Sanitize B-roll timeline with strict spacing and rhythm rules.
        
        Rules applied in order:
        1. HOOK ZONE (0-3.5s): Drop any B-roll in the hook zone entirely.
           Do NOT shift — shifting creates awkward early overlays.
        2. CTA ZONE (last 2s): Drop any B-roll in the CTA zone entirely.
        3. NO OVERLAPS: At most one B-roll active at any time.
        4. SEMANTIC DEDUP: Skip repeated visual ideas (Jaccard > 0.30).
        5. DISCOURSE WINDOW GROUPING: Merge cues that fall within the same
           speaking segment (~10s window). Keep only the best-positioned cue
           per discourse window to avoid micro-switching between unrelated
           concepts.
        6. UNRELATED CONCEPT COOLDOWN: If two consecutive cues have unrelated
           concepts (Jaccard < 0.15) within the same discourse window, drop
           the second one to prevent jarring context switches.
        7. MINIMUM SPACING: Enforce gap based on clip length and speaking rate.
           If two cues are too close, keep only the better-positioned one.
        8. RHYTHM: Max 4 per 60s, max 40% coverage. Prefer distinct ideas
           over extra density. Keep pacing natural for clip length.
        9. EARLY/LATE ZONES: At most one B-roll in first 5s, at most one
           in last 4s.
        
        Every dropped or moved cue is logged with the exact rule that was applied.
        
        semantic_opportunities: number of distinct visual moments detected
                                (from micro-moment detection). Used to cap
                                the final count.
        
        Returns sanitized list of (timestamp, asset_path, duration).
        """
        if not pairs:
            return []
        
        _HOOK_END = 3.5       # seconds — keep hook zone completely clean
        _CTA_GUARD = 2.0      # seconds — keep last N seconds clean for CTA
        _MIN_DUR = BROLL_MIN_OVERLAY_DURATION_S
        _MAX_PER_MIN = 4
        _MAX_COVERAGE = 0.40  # max 40% of clip covered by B-roll
        # ── HARD RULES (enforced before all other rules) ──────────────────────
        _MIN_CUE_DURATION = 3.0       # Rule A: reject cues shorter than 3s
        _SEMANTIC_THRESHOLD = 0.35    # Rule B: reject cues below semantic score
        _CONCEPT_COOLDOWN = 8.0       # Rule D: block same concept within 8s
        _MAX_PER_5S_WINDOW = 1        # Rule E: max 1 cue per 5s window
        
        # Sort by timestamp
        sorted_pairs = sorted(pairs, key=lambda x: x[0])
        
        # ── HARD RULE A: Minimum cue duration ────────────────────────────────
        # Reject any cue shorter than _MIN_CUE_DURATION. A 3s minimum ensures
        # the viewer has time to register the visual before it disappears.
        _dur_filtered = []
        _dur_removed = 0
        for ts, asset, dur in sorted_pairs:
            if dur < _MIN_CUE_DURATION:
                _dur_removed += 1
                logger.warning(
                    "[BrollGate] HARD RULE A: DROPPED ts=%.1fs dur=%.1fs asset=%s "
                    "(below min cue duration %.1fs)",
                    ts, dur, Path(asset).name, _MIN_CUE_DURATION,
                )
            else:
                _dur_filtered.append((ts, asset, dur))
        sorted_pairs = _dur_filtered
        
        # ── HARD RULE B: Semantic threshold ──────────────────────────────────
        # Reject cues whose asset name has no semantic overlap with the
        # segment text. Uses Jaccard similarity on word tokens between the
        # asset filename and the segment text. Threshold 0.65 ensures only
        # strongly related visuals pass.
        # If no cues pass, emit nothing — do NOT force a filler.
        _sem_filtered = []
        _sem_removed = 0
        _seg_words = set()
        if hasattr(self, '_segment_text') and self._segment_text:
            _seg_words = set(self._segment_text.lower().split())
        for ts, asset, dur in sorted_pairs:
            _asset_name = Path(asset).stem.lower().replace("_", " ").replace("-", " ")
            _asset_words = set(_asset_name.split())
            if _seg_words and _asset_words:
                _intersection = _seg_words & _asset_words
                _union = _seg_words | _asset_words
                _jaccard = len(_intersection) / len(_union) if _union else 0.0
                if _jaccard < _SEMANTIC_THRESHOLD:
                    _sem_removed += 1
                    logger.warning(
                        "[BrollGate] HARD RULE B: DROPPED ts=%.1fs asset=%s "
                        "(jaccard=%.2f < threshold=%.2f) — no strong semantic support",
                        ts, Path(asset).name, _jaccard, _SEMANTIC_THRESHOLD,
                    )
                    continue
            _sem_filtered.append((ts, asset, dur))
        sorted_pairs = _sem_filtered
        
        # ── HARD RULE C: Speaking segment grouping ──────────────────────────
        # Group cues by sentence/phrase boundary. One cue per sentence maximum.
        # Uses a 10s discourse window as a proxy for sentence boundaries.
        # Within each window, keep only the best-positioned cue (closest to
        # the window midpoint).
        _DISCOURSE_WINDOW_S = 10.0
        _discourse_grouped: List[Tuple[float, str, float]] = []
        _discourse_removed = 0
        _current_window_start = -_DISCOURSE_WINDOW_S
        _window_candidates: List[Tuple[float, str, float]] = []
        for ts, asset, dur in sorted_pairs:
            if ts - _current_window_start < _DISCOURSE_WINDOW_S:
                _window_candidates.append((ts, asset, dur))
            else:
                if _window_candidates:
                    _window_mid = _current_window_start + _DISCOURSE_WINDOW_S / 2.0
                    _window_candidates.sort(key=lambda x: abs(x[0] - _window_mid))
                    _discourse_grouped.append(_window_candidates[0])
                    _discourse_removed += len(_window_candidates) - 1
                    if len(_window_candidates) > 1:
                        logger.warning(
                            "[BrollGate] HARD RULE C: merged %d cues in window [%.1fs, %.1fs) "
                            "→ kept best at t=%.1fs",
                            len(_window_candidates), _current_window_start,
                            _current_window_start + _DISCOURSE_WINDOW_S,
                            _window_candidates[0][0],
                        )
                _current_window_start = ts
                _window_candidates = [(ts, asset, dur)]
        if _window_candidates:
            _window_mid = _current_window_start + _DISCOURSE_WINDOW_S / 2.0
            _window_candidates.sort(key=lambda x: abs(x[0] - _window_mid))
            _discourse_grouped.append(_window_candidates[0])
            _discourse_removed += len(_window_candidates) - 1
            if len(_window_candidates) > 1:
                logger.warning(
                    "[BrollGate] HARD RULE C: merged %d cues in window [%.1fs, %.1fs) "
                    "→ kept best at t=%.1fs",
                    len(_window_candidates), _current_window_start,
                    _current_window_start + _DISCOURSE_WINDOW_S,
                    _window_candidates[0][0],
                )
        sorted_pairs = _discourse_grouped
        
        # ── HARD RULE D: Concept cooldown ────────────────────────────────────
        # Block the same concept or source URL from appearing again within
        # _CONCEPT_COOLDOWN seconds. Uses asset filename stem as concept proxy.
        _cooldown_filtered: List[Tuple[float, str, float]] = []
        _cooldown_removed = 0
        _last_concept = ""
        _last_concept_ts = -_CONCEPT_COOLDOWN
        for ts, asset, dur in sorted_pairs:
            _concept = Path(asset).stem.lower().replace("_", " ").replace("-", " ")
            if _concept == _last_concept and ts - _last_concept_ts < _CONCEPT_COOLDOWN:
                _cooldown_removed += 1
                logger.warning(
                    "[BrollGate] HARD RULE D: DROPPED ts=%.1fs concept='%s' "
                    "(same concept repeated within %.1fs cooldown)",
                    ts, _concept[:40], _CONCEPT_COOLDOWN,
                )
                continue
            _cooldown_filtered.append((ts, asset, dur))
            _last_concept = _concept
            _last_concept_ts = ts
        sorted_pairs = _cooldown_filtered
        
        # ── HARD RULE E: Max 1 cue per 5-second window ──────────────────────
        # No more than 1 B-roll change per 5-second window. This prevents
        # rapid visual switching that disorients the viewer.
        _window_filtered: List[Tuple[float, str, float]] = []
        _window_removed = 0
        _last_window_ts = -5.0
        for ts, asset, dur in sorted_pairs:
            if ts - _last_window_ts < 5.0:
                _window_removed += 1
                logger.warning(
                    "[BrollGate] HARD RULE E: DROPPED ts=%.1fs asset=%s "
                    "(only %.1fs since last cue, max 1 per 5s)",
                    ts, Path(asset).name, ts - _last_window_ts,
                )
                continue
            _window_filtered.append((ts, asset, dur))
            _last_window_ts = ts
        sorted_pairs = _window_filtered
        
        # ── HARD RULE F: No filler fallback ─────────────────────────────────
        # If no cues pass all the above rules, emit nothing. Do NOT force
        # a filler cue. The caller will render the clip without B-roll.
        if not sorted_pairs:
            logger.warning(
                "[BrollGate] HARD RULE F: ALL %d cues rejected by hard rules "
                "(dur=%d sem=%d discourse=%d cooldown=%d window=%d) — "
                "emitting 0 B-roll (no filler fallback)",
                len(pairs), _dur_removed, _sem_removed,
                _discourse_removed, _cooldown_removed, _window_removed,
            )
            return []
        
        # ── Step 1: Hook zone protection (HARDENED) ──
        # Drop any B-roll that starts in [0, _HOOK_END). Do NOT shift —
        # shifting creates awkward early overlays that compete with the hook.
        hook_removed = 0
        hook_shifted = 0
        clean: List[Tuple[float, str, float]] = []
        for ts, asset, dur in sorted_pairs:
            if ts < _HOOK_END:
                hook_removed += 1
                logger.info(
                    "[BRoll/Spacing] RULE 1 (Hook Zone): dropped B-roll at t=%.1fs "
                    "(dur=%.1fs, asset=%s) — hook zone [0, %.1fs) must stay clean",
                    ts, dur, Path(asset).name, _HOOK_END,
                )
            else:
                clean.append((ts, asset, dur))
        
        # ── Step 1b: CTA zone protection (NEW) ──
        # Drop any B-roll that starts in the last _CTA_GUARD seconds.
        _cta_start = max(0.0, (clip_duration or float('inf')) - _CTA_GUARD)
        cta_removed = 0
        no_cta: List[Tuple[float, str, float]] = []
        for ts, asset, dur in clean:
            if clip_duration > 0 and ts >= _cta_start:
                cta_removed += 1
                logger.info(
                    "[BRoll/Spacing] RULE 2 (CTA Zone): dropped B-roll at t=%.1fs "
                    "(dur=%.1fs, asset=%s) — last %.1fs reserved for CTA",
                    ts, dur, Path(asset).name, _CTA_GUARD,
                )
            else:
                no_cta.append((ts, asset, dur))
        
        # ── Step 2: No overlaps ──
        no_overlap: List[Tuple[float, str, float]] = []
        overlap_removed = 0
        overlap_shifted = 0
        for ts, asset, dur in no_cta:
            if not no_overlap:
                no_overlap.append((ts, asset, dur))
                continue
            _prev_end = no_overlap[-1][0] + no_overlap[-1][2]
            if ts < _prev_end:
                # Shift to start after previous ends
                new_ts = _prev_end + 0.15
                # Check if shifted version is still valid
                if new_ts + dur <= (clip_duration or new_ts + dur + 1) and dur >= _MIN_DUR:
                    no_overlap.append((new_ts, asset, dur))
                    overlap_shifted += 1
                    logger.info(
                        "[BRoll/Spacing] RULE 3 (Overlap): shifted B-roll from t=%.1fs → t=%.1fs "
                        "(asset=%s) — previous ends at t=%.1fs",
                        ts, new_ts, Path(asset).name, _prev_end,
                    )
                else:
                    overlap_removed += 1
                    logger.info(
                        "[BRoll/Spacing] RULE 3 (Overlap): dropped B-roll at t=%.1fs "
                        "(dur=%.1fs, asset=%s) — cannot shift without exceeding clip",
                        ts, dur, Path(asset).name,
                    )
            else:
                no_overlap.append((ts, asset, dur))
        
        # ── Step 2.5: Semantic dedup — skip repeated visual ideas ──
        _deduped: List[Tuple[float, str, float]] = []
        _seen_concepts: List[str] = []
        _dedup_skipped = 0
        for ts, asset, dur in no_overlap:
            _asset_name = Path(asset).stem.lower().replace("_", " ").replace("-", " ")
            _asset_words = set(_asset_name.split())
            _is_duplicate = False
            for _prev in _seen_concepts:
                _prev_words = set(_prev.split())
                _intersection = _asset_words & _prev_words
                _union = _asset_words | _prev_words
                if _union and len(_intersection) / len(_union) > 0.3:
                    _is_duplicate = True
                    _dedup_skipped += 1
                    logger.info(
                        "[BRoll/Spacing] RULE 4 (Semantic Dedup): skipped '%s' "
                        "(similar to '%s') at t=%.1fs",
                        _asset_name[:40], _prev[:40], ts,
                    )
                    break
            if not _is_duplicate:
                _deduped.append((ts, asset, dur))
                _seen_concepts.append(_asset_name)
        
        # ── Step 2.6: Discourse window grouping (NEW) ──
        # Group cues that fall within the same speaking segment (~10s window).
        # Keep only the best-positioned cue per discourse window to avoid
        # micro-switching between unrelated concepts within a single thought.
        _DISCOURSE_WINDOW_S = 10.0  # seconds — typical speaking segment length
        _discourse_grouped: List[Tuple[float, str, float]] = []
        _discourse_removed = 0
        _current_window_start = -_DISCOURSE_WINDOW_S
        _window_candidates: List[Tuple[float, str, float]] = []
        
        for ts, asset, dur in _deduped:
            if ts - _current_window_start < _DISCOURSE_WINDOW_S:
                # Same discourse window — collect candidate
                _window_candidates.append((ts, asset, dur))
            else:
                # New discourse window — resolve previous window
                if _window_candidates:
                    # Keep the best-positioned cue in this window (closest to window midpoint)
                    _window_mid = _current_window_start + _DISCOURSE_WINDOW_S / 2.0
                    _window_candidates.sort(
                        key=lambda x: abs(x[0] - _window_mid)
                    )
                    _discourse_grouped.append(_window_candidates[0])
                    _discourse_removed += len(_window_candidates) - 1
                    if len(_window_candidates) > 1:
                        logger.info(
                            "[BRoll/Spacing] RULE 5 (Discourse Window): "
                            "grouped %d cues in window [%.1fs, %.1fs) → "
                            "kept best at t=%.1fs (asset=%s)",
                            len(_window_candidates),
                            _current_window_start,
                            _current_window_start + _DISCOURSE_WINDOW_S,
                            _window_candidates[0][0],
                            Path(_window_candidates[0][1]).name,
                        )
                # Start new window
                _current_window_start = ts
                _window_candidates = [(ts, asset, dur)]
        
        # Resolve last window
        if _window_candidates:
            _window_mid = _current_window_start + _DISCOURSE_WINDOW_S / 2.0
            _window_candidates.sort(key=lambda x: abs(x[0] - _window_mid))
            _discourse_grouped.append(_window_candidates[0])
            _discourse_removed += len(_window_candidates) - 1
            if len(_window_candidates) > 1:
                logger.info(
                    "[BRoll/Spacing] RULE 5 (Discourse Window): "
                    "grouped %d cues in window [%.1fs, %.1fs) → "
                    "kept best at t=%.1fs (asset=%s)",
                    len(_window_candidates),
                    _current_window_start,
                    _current_window_start + _DISCOURSE_WINDOW_S,
                    _window_candidates[0][0],
                    Path(_window_candidates[0][1]).name,
                )
        
        # ── Step 2.7: Continuity score between adjacent B-rolls ──
        # Compute a continuity score (0.0–1.0) for each adjacent pair.
        # If the score is below threshold, drop the second cue to avoid
        # a jarring transition.
        #
        # Continuity criteria:
        # - Same source (Pexels/Coverr/Pixabay): +0.2
        # - Same visual category (human/object/abstract/env): +0.2
        # - Jaccard similarity ≥ 0.15 on asset name tokens: +0.15
        # - Same duration (±1s): +0.1
        # - Same resolution (±200px): +0.1
        # - Same framing (wide/medium/closeup): +0.15
        # - Same camera motion (static/pan/zoom): +0.1
        _CONTINUITY_THRESHOLD = 0.35  # below this = jarring transition
        _continuity_result: List[Tuple[float, str, float]] = []
        _continuity_removed = 0
        _last_asset_path = ""
        _last_source = ""
        _last_kind = ""
        _last_dur = 0.0
        _last_res = 0
        _last_framing = ""
        _last_motion = ""

        for ts, asset, dur in _discourse_grouped:
            _asset_str = str(asset)
            _asset_name = Path(asset).stem.lower().replace("_", " ").replace("-", " ")
            _asset_words = set(_asset_name.split())

            # Derive source from path
            _source = "pexels" if "pexels" in _asset_str.lower() else \
                      "coverr" if "coverr" in _asset_str.lower() else \
                      "pixabay" if "pixabay" in _asset_str.lower() else "other"

            # Derive kind from filename
            _kind = BrollService._derive_kind(asset)

            # Probe resolution and derive framing/motion from metadata
            _meta = BrollService._probe_asset_tech(asset)
            _res = max(_meta.get("width", 0), _meta.get("height", 0))

            # Derive framing from asset name: wide/medium/closeup
            _framing = "medium"  # default
            if any(kw in _asset_name for kw in ("wide", "landscape", "panorama", "establishing", "full body", "full shot")):
                _framing = "wide"
            elif any(kw in _asset_name for kw in ("closeup", "close-up", "close up", "detail", "macro", "face", "portrait")):
                _framing = "closeup"

            # Derive camera motion from asset name
            _motion = "static"  # default
            if any(kw in _asset_name for kw in ("pan", "panning", "slow pan")):
                _motion = "pan"
            elif any(kw in _asset_name for kw in ("zoom", "zoom in", "zoom out", "dolly")):
                _motion = "zoom"
            elif any(kw in _asset_name for kw in ("track", "tracking", "follow", "camera move")):
                _motion = "track"

            if _last_asset_path:
                # Compute continuity score
                _score = 0.0

                # Same source bonus
                if _source == _last_source:
                    _score += 0.2

                # Same kind bonus
                if _kind == _last_kind:
                    _score += 0.2

                # Jaccard similarity on asset name tokens
                _prev_words = set(Path(_last_asset_path).stem.lower().replace("_", " ").replace("-", " ").split())
                _intersection = _asset_words & _prev_words
                _union = _asset_words | _prev_words
                _jaccard = len(_intersection) / len(_union) if _union else 0.0
                if _jaccard >= 0.15:
                    _score += 0.15

                # Same duration bonus
                if abs(dur - _last_dur) <= 1.0:
                    _score += 0.1

                # Same resolution bonus
                if _res > 0 and _last_res > 0 and abs(_res - _last_res) <= 200:
                    _score += 0.1

                # Same framing bonus (avoids abrupt scale changes)
                if _framing == _last_framing:
                    _score += 0.15
                elif (_framing == "wide" and _last_framing == "closeup") or \
                     (_framing == "closeup" and _last_framing == "wide"):
                    _score -= 0.1  # Penalize extreme framing jumps

                # Same camera motion bonus
                if _motion == _last_motion:
                    _score += 0.1
                elif _motion == "static" and _last_motion == "zoom":
                    _score -= 0.05  # Slight penalty for static→zoom

                if _score < _CONTINUITY_THRESHOLD:
                    _continuity_removed += 1
                    logger.info(
                        "[BRoll/Continuity] RULE 7: dropped '%s' at t=%.1fs "
                        "(continuity score=%.2f < threshold=%.2f) — "
                        "source=%s→%s kind=%s→%s jaccard=%.2f "
                        "framing=%s→%s motion=%s→%s dur=%.1f→%.1f",
                        _asset_name[:40], ts,
                        _score, _CONTINUITY_THRESHOLD,
                        _last_source, _source, _last_kind, _kind,
                        _jaccard,
                        _last_framing, _framing, _last_motion, _motion,
                        _last_dur, dur,
                    )
                    continue

            _continuity_result.append((ts, asset, dur))
            _last_asset_path = _asset_str
            _last_source = _source
            _last_kind = _kind
            _last_dur = dur
            _last_res = _res
            _last_framing = _framing
            _last_motion = _motion
        
        # ── Step 3: Rhythm — intentional, not mechanical (HARDENED) ──
        # Compute speaking rate from semantic_opportunities.
        _speaking_rate = semantic_opportunities / max(clip_duration, 1.0) if clip_duration > 0 else 0.0
        
        # Compute max_allowed based on clip length and speaking rate
        _base_max = max(1, int(clip_duration / 60.0 * _MAX_PER_MIN)) if clip_duration > 0 else len(_deduped)
        if _speaking_rate > 0.3:
            _max_allowed = min(_base_max, max(1, int(clip_duration / 60.0 * 4)))
        elif _speaking_rate > 0.15:
            _max_allowed = min(_base_max, max(1, int(clip_duration / 60.0 * 3)))
        else:
            _max_allowed = min(_base_max, max(1, int(clip_duration / 60.0 * 2)))
        
        # Compute minimum gap based on clip length and speaking rate (HARDENED)
        # Short clips (< 30s) need tighter gaps to fit any b-roll at all.
        # Long clips (> 60s) need wider gaps to avoid visual clutter.
        if clip_duration < 30.0:
            _min_gap = 6.0 if _speaking_rate > 0.3 else (10.0 if _speaking_rate > 0.15 else 14.0)
        elif clip_duration < 60.0:
            _min_gap = 8.0 if _speaking_rate > 0.3 else (12.0 if _speaking_rate > 0.15 else 16.0)
        else:
            _min_gap = 10.0 if _speaking_rate > 0.3 else (14.0 if _speaking_rate > 0.15 else 20.0)
        
        # Zone guards: avoid placing B-roll too early or too late
        _EARLY_ZONE_END = 5.0   # first 5s: only if it reinforces the hook
        _LATE_ZONE_START = max(0.0, (clip_duration or 0) - 4.0)  # last 4s: only if supports closing
        
        _max_coverage_s = clip_duration * _MAX_COVERAGE if clip_duration > 0 else float('inf')
        
        rhythm_result: List[Tuple[float, str, float]] = []
        _coverage = 0.0
        _last_ts = -_min_gap
        _has_early_broll = False
        _has_late_broll = False
        
        # Track dropped cues for "keep the better one" logic
        _dropped_for_gap: List[Tuple[float, str, float, float]] = []  # (ts, asset, dur, gap_to_prev)
        
        for ts, asset, dur in _cooldown_result:
            # Early zone check: only allow if it reinforces the hook
            if ts < _EARLY_ZONE_END:
                if _has_early_broll:
                    logger.info(
                        "[BRoll/Spacing] RULE 7 (Early Zone): dropped B-roll at t=%.1fs "
                        "(asset=%s) — already have one in early zone [0, %.1fs)",
                        ts, Path(asset).name, _EARLY_ZONE_END,
                    )
                    continue
                _has_early_broll = True
            
            # Late zone check: only allow if it supports the closing point
            if ts >= _LATE_ZONE_START:
                if _has_late_broll:
                    logger.info(
                        "[BRoll/Spacing] RULE 7 (Late Zone): dropped B-roll at t=%.1fs "
                        "(asset=%s) — already have one in late zone [%.1fs, end)",
                        ts, Path(asset).name, _LATE_ZONE_START,
                    )
                    continue
                _has_late_broll = True
            
            # If only one strong visual moment exists, keep it to one B-roll
            if semantic_opportunities <= 1 and len(rhythm_result) >= 1:
                logger.info(
                    "[BRoll/Spacing] RULE 6 (Single Moment): keeping only 1 B-roll "
                    "(opportunities=%d) — dropped cue at t=%.1fs",
                    semantic_opportunities, ts,
                )
                break
            
            if len(rhythm_result) >= _max_allowed:
                logger.info(
                    "[BRoll/Spacing] RULE 6 (Max Allowed): hit max %d B-rolls — "
                    "dropped cue at t=%.1fs (asset=%s)",
                    _max_allowed, ts, Path(asset).name,
                )
                break
            
            if _coverage + dur > _max_coverage_s:
                logger.info(
                    "[BRoll/Spacing] RULE 6 (Coverage): coverage %.1fs + %.1fs > max %.1fs — "
                    "dropped cue at t=%.1fs (asset=%s)",
                    _coverage, dur, _max_coverage_s, ts, Path(asset).name,
                )
                break
            
            # ── HARDENED: Minimum gap enforcement with "keep the better one" logic ──
            _gap = ts - _last_ts
            if _gap < _min_gap:
                # Two cues are too close. Keep the better-positioned one.
                # "Better" means: prefer the one that is more centered in the clip,
                # or if one is in a zone guard, prefer the other.
                if rhythm_result:
                    _prev_ts, _prev_asset, _prev_dur = rhythm_result[-1]
                    _clip_mid = clip_duration / 2.0 if clip_duration > 0 else 0.0
                    
                    # Score each cue by distance from clip midpoint (lower = better)
                    _prev_score = abs(_prev_ts - _clip_mid)
                    _curr_score = abs(ts - _clip_mid)
                    
                    # Also penalize cues that are in the early or late zone
                    if _prev_ts < _EARLY_ZONE_END:
                        _prev_score += 10.0
                    if ts < _EARLY_ZONE_END:
                        _curr_score += 10.0
                    if _prev_ts >= _LATE_ZONE_START:
                        _prev_score += 5.0
                    if ts >= _LATE_ZONE_START:
                        _curr_score += 5.0
                    
                    if _curr_score < _prev_score:
                        # Current cue is better positioned — replace the previous one
                        _dropped = rhythm_result.pop()
                        _dropped_for_gap.append((_dropped[0], _dropped[1], _dropped[2], _gap))
                        _coverage -= _dropped[2]
                        rhythm_result.append((ts, asset, dur))
                        _coverage += dur
                        _last_ts = ts
                        logger.info(
                            "[BRoll/Spacing] RULE 5 (Min Gap): replaced cue at t=%.1fs "
                            "(asset=%s) with better-positioned cue at t=%.1fs "
                            "(asset=%s) — gap=%.1fs < min=%.1fs, "
                            "prev_score=%.1f curr_score=%.1f",
                            _dropped[0], Path(_dropped[1]).name,
                            ts, Path(asset).name,
                            _gap, _min_gap,
                            _prev_score, _curr_score,
                        )
                    else:
                        # Previous cue is better positioned — drop the current one
                        _dropped_for_gap.append((ts, asset, dur, _gap))
                        logger.info(
                            "[BRoll/Spacing] RULE 5 (Min Gap): dropped cue at t=%.1fs "
                            "(asset=%s) — gap=%.1fs < min=%.1fs, "
                            "keeping better-positioned cue at t=%.1fs (score=%.1f vs %.1f)",
                            ts, Path(asset).name,
                            _gap, _min_gap,
                            _prev_ts, _prev_score, _curr_score,
                        )
                else:
                    # No previous cue in result yet — skip this one
                    _dropped_for_gap.append((ts, asset, dur, _gap))
                    logger.info(
                        "[BRoll/Spacing] RULE 5 (Min Gap): dropped cue at t=%.1fs "
                        "(asset=%s) — gap=%.1fs < min=%.1fs (no previous to compare)",
                        ts, Path(asset).name, _gap, _min_gap,
                    )
                continue
            
            rhythm_result.append((ts, asset, dur))
            _coverage += dur
            _last_ts = ts
        
        # ── QA logging (HARDENED) ──
        _total_dur = clip_duration or 1.0
        _cov_pct = (_coverage / _total_dur) * 100
        _n_dropped_total = (
            hook_removed + cta_removed + overlap_removed + _dedup_skipped
            + _discourse_removed + _cooldown_removed + len(_dropped_for_gap)
        )
        logger.info(
            "[BRoll] Timeline QA: %d B-rolls placed, coverage=%.0f%%, "
            "dropped=%d (hook=%d cta=%d overlap=%d dedup=%d "
            "discourse=%d cooldown=%d gap=%d) "
            "shifted=%d (overlap=%d)",
            len(rhythm_result), _cov_pct,
            _n_dropped_total,
            hook_removed, cta_removed, overlap_removed, _dedup_skipped,
            _discourse_removed, _cooldown_removed, len(_dropped_for_gap),
            overlap_shifted, overlap_shifted,
        )
        if _cov_pct > 60:
            logger.warning(
                "[BRoll] Timeline QA: coverage %.0f%% exceeds 60%% — "
                "consider reducing B-roll density",
                _cov_pct,
            )
        if overlap_removed > 2:
            logger.warning(
                "[BRoll] Timeline QA: %d overlaps removed — "
                "timestamps may need tuning",
                overlap_removed,
            )
        if _n_dropped_total > 0:
            logger.info(
                "[BRoll] Spacing summary: %d cues dropped by rule "
                "(hook=%d, cta=%d, overlap=%d, dedup=%d, "
                "discourse=%d, cooldown=%d, gap=%d), "
                "%d placed",
                _n_dropped_total,
                hook_removed, cta_removed, overlap_removed, _dedup_skipped,
                _discourse_removed, _cooldown_removed, len(_dropped_for_gap),
                len(rhythm_result),
            )
        
        return rhythm_result

    @staticmethod
    def _probe_asset_tech(asset_path: Path) -> Dict[str, Any]:
        """
        Probe a B-roll asset file for technical metadata using ffprobe.
        Returns dict with: width, height, fps, duration, has_letterbox.
        On error returns empty dict (asset passes through, no hard reject).
        """
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height,r_frame_rate,duration",
                 "-of", "json", str(asset_path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return {}
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if not streams:
                return {}
            s = streams[0]
            w = s.get("width", 0) or 0
            h = s.get("height", 0) or 0
            # Parse frame rate
            fps_str = s.get("r_frame_rate", "0/1")
            fps = 0.0
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / max(float(den), 1)
            dur = float(s.get("duration", 0) or 0)
            # Detect letterbox: if aspect ratio is very different from 16:9 or 9:16
            has_letterbox = False
            if w > 0 and h > 0:
                ar = w / h
                # Accept 16:9 (1.78), 9:16 (0.56), 4:3 (1.33), 3:4 (0.75), 1:1 (1.0)
                if not (0.5 <= ar <= 2.0):
                    has_letterbox = True
            return {"width": w, "height": h, "fps": round(fps, 1), "duration": round(dur, 2), "has_letterbox": has_letterbox}
        except Exception as e:
            logger.debug("[BRoll] ffprobe failed for %s: %s", asset_path.name, e)
            return {}

    @staticmethod
    def _derive_kind(asset_path: Path) -> str:
        """Derive shot kind from asset filename/tags: human, object, abstract, env."""
        name = asset_path.stem.lower().replace("_", " ").replace("-", " ")
        # Human keywords
        if any(kw in name for kw in ("person", "people", "woman", "man", "child", "family",
                                      "crowd", "audience", "face", "portrait", "interview",
                                      "speaker", "talking", "presentation", "team", "group",
                                      "hand", "hands", "businessman", "businesswoman")):
            return "human"
        # Environment / nature
        if any(kw in name for kw in ("nature", "landscape", "mountain", "ocean", "sea",
                                      "beach", "forest", "sky", "city", "urban", "street",
                                      "building", "office", "room", "interior", "environment")):
            return "env"
        # Abstract / graphics
        if any(kw in name for kw in ("chart", "graph", "diagram", "data", "abstract",
                                      "animation", "motion", "background", "pattern",
                                      "technology", "digital", "code", "screen")):
            return "abstract"
        return "object"

    @staticmethod
    def _filter_assets_by_quality(assets: List[Path]) -> List[Path]:
        """
        Filter B-roll assets by minimum technical quality.
        Drops assets with:
        - Resolution < 720px on the long side (too low for 1080p output)
        - Aspect ratio outside [0.5, 2.0] (letterboxed / extreme)
        - Duration < 1.0s (too short to be useful)
        Logs how many were dropped and why.
        """
        if not assets:
            return []
        _MIN_LONG_SIDE = 720
        _MIN_DUR = BROLL_MIN_OVERLAY_DURATION_S
        kept: List[Path] = []
        dropped_res = 0
        dropped_ar = 0
        dropped_dur = 0
        for a in assets:
            meta = BrollService._probe_asset_tech(a)
            if not meta:
                # Can't probe — keep it (don't reject on probe failure)
                kept.append(a)
                continue
            w = meta.get("width", 0)
            h = meta.get("height", 0)
            long_side = max(w, h)
            if 0 < long_side < _MIN_LONG_SIDE:
                dropped_res += 1
                logger.debug("[BRoll] Quality drop: %s (res=%dx%d < %dpx)", a.name, w, h, _MIN_LONG_SIDE)
                continue
            if meta.get("has_letterbox", False):
                dropped_ar += 1
                logger.debug("[BRoll] Quality drop: %s (letterboxed)", a.name)
                continue
            dur = meta.get("duration", 0)
            if 0 < dur < _MIN_DUR:
                dropped_dur += 1
                logger.debug("[BRoll] Quality drop: %s (dur=%.1fs < %.1fs)", a.name, dur, _MIN_DUR)
                continue
            kept.append(a)
        if dropped_res or dropped_ar or dropped_dur:
            logger.info(
                "[BRoll] Quality filter: %d→%d assets (res=%d ar=%d dur=%d)",
                len(assets), len(kept), dropped_res, dropped_ar, dropped_dur,
            )
        return kept

    @staticmethod
    def _should_use_generative(
        viral_score: float = 0.0,
        clip_duration: float = 0.0,
        content_category: str = "",
        generative_count: int = 0,
        max_generative: int = 2,
    ) -> bool:
        """
        Decide whether to use generative (ComfyUI/LTX) B-roll for this clip.
        
        Rules:
        - Only if BROLL_MODE is hybrid or generative.
        - Only if clip duration > 10s (generative takes time to produce).
        - Only if viral_score >= 60 (high-value clips justify the cost).
        - Only if we haven't exceeded max_generative per clip.
        - Skip for content categories where stock is fine (e.g. generic talking).
        """
        _mode = os.getenv("BROLL_MODE", "hybrid").lower()
        if _mode == "stock_only":
            return False
        if generative_count >= max_generative:
            return False
        if clip_duration < 10.0:
            return False
        if viral_score < 60:
            return False
        # For high-energy or visually rich categories, prefer stock
        _cat = content_category.lower()
        if any(kw in _cat for kw in ("generic", "education", "tutorial")):
            return False
        return True

    @staticmethod
    def _select_strongest_closing(
        segment_text: str,
        words_with_timestamps: Optional[List[Dict]] = None,
        clip_duration: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Identify the strongest closing line in the last 25% of a clip.

        Scores each sentence in the closing section by:
        - Memorability: call-to-action words, emotional impact, summary markers
        - Specificity: numbers, concrete takeaways
        - Brevity: shorter sentences score higher (punchier ending)
        - CTA presence: boost for call-to-action phrases

        Returns a dict with:
        - text: the closing sentence
        - score: 0.0–1.0
        - start_time: timestamp in seconds
        - reason: why this was selected

        Returns None if no strong closing found (clip should use the last sentence).
        """
        if not segment_text or clip_duration <= 0:
            return None

        import re as _re

        # Split into sentences
        _sentences = _re.split(r'(?<=[.!?])\s+', segment_text.strip())
        _sentences = [s for s in _sentences if s]

        if not _sentences:
            return None

        # Score each sentence
        _scored: List[Tuple[float, str, int]] = []
        _CTA_WORDS = {
            "subscribe", "suscríbete", "follow", "sígueme", "comparte",
            "share", "like", "dale like", "comenta", "comment",
            "register", "regístrate", "sign up", "apúntate",
            "join", "únete", "download", "descarga", "click",
            "link", "enlace", "bio", "más información", "more info",
            "call", "llama", "contact", "contacta", "visita", "visit",
        }
        _SUMMARY_MARKERS = {
            "in conclusion", "en conclusión", "to summarize", "resumiendo",
            "the bottom line", "en resumen", "in short", "en pocas palabras",
            "finally", "finalmente", "lastly", "por último",
            "remember", "recuerda", "don't forget", "no olvides",
            "the key takeaway", "la clave", "the most important",
            "lo más importante", "at the end of the day", "al final",
        }
        _EMOTIONAL_CLOSERS = {
            "life-changing", "transformador", "game changer",
            "never be the same", "nunca será igual", "forever",
            "para siempre", "the best decision", "la mejor decisión",
            "you deserve", "te mereces", "your future", "tu futuro",
            "peace of mind", "tranquilidad", "security", "seguridad",
        }

        for i, sent in enumerate(_sentences):
            _lower = sent.lower()
            _score = 0.0

            # Boost CTA words
            _cta_hits = sum(1 for w in _CTA_WORDS if w in _lower)
            _score += min(0.4, _cta_hits * 0.15)

            # Boost summary markers
            _summary_hits = sum(1 for m in _SUMMARY_MARKERS if m in _lower)
            _score += min(0.3, _summary_hits * 0.1)

            # Boost emotional closers
            _emo_hits = sum(1 for w in _EMOTIONAL_CLOSERS if w in _lower)
            _score += min(0.3, _emo_hits * 0.1)

            # Boost numbers
            if _re.search(r'\d+', sent):
                _score += 0.15

            # Boost brevity (shorter = punchier ending)
            _word_count = len(sent.split())
            if _word_count <= 8:
                _score += 0.15
            elif _word_count <= 15:
                _score += 0.05

            # Boost exclamation marks (strong delivery)
            _exclams = sent.count("!")
            _score += min(0.15, _exclams * 0.08)

            # Position bonus: later sentences score higher (closing section)
            _position_ratio = i / max(len(_sentences) - 1, 1)
            _score += _position_ratio * 0.1

            _scored.append((_score, sent, i))

        # Sort by score descending
        _scored.sort(key=lambda x: x[0], reverse=True)

        if not _scored:
            return None

        _best_score, _best_text, _best_idx = _scored[0]

        # Find timestamp for this sentence
        _start_time = 0.0
        if words_with_timestamps:
            _sent_words = _best_text.split()
            for w in words_with_timestamps:
                _w_text = (w.get("word") or "").lower().strip(".,!?;:'\"")
                if _sent_words and _w_text == _sent_words[0].lower().strip(".,!?;:'\""):
                    _start_time = float(w.get("start", 0))
                    break

        # Determine reason
        _reasons = []
        if any(c in _best_text for c in "!?"):
            _reasons.append("strong delivery")
        if _re.search(r'\d+', _best_text):
            _reasons.append("contains numbers")
        if len(_best_text.split()) <= 8:
            _reasons.append("short and punchy")
        if any(w in _best_text.lower() for w in _CTA_WORDS):
            _reasons.append("call to action")

        logger.info(
            "[BRoll/Closing] Strongest closing: score=%.2f text='%s' at t=%.1fs — %s",
            _best_score, _best_text[:60], _start_time,
            ", ".join(_reasons) if _reasons else "default",
        )

        return {
            "text": _best_text,
            "score": _best_score,
            "start_time": _start_time,
            "reason": ", ".join(_reasons) if _reasons else "default",
        }

    @staticmethod
    def _compute_caption_animation(
        words_with_timestamps: List[Dict],
        clip_duration: float = 0.0,
    ) -> Dict[str, Any]:
        """Compute subtitle animation parameters for hook and closing moments.

        Returns a dict with:
        - intro_animation: animation type for the first caption line
        - intro_duration: how long the intro animation takes
        - closing_animation: animation type for the last caption line
        - closing_duration: how long the closing animation takes
        - standard_animation: animation type for all other lines

        Rules:
        - First caption (hook): "fade_in" with 0.3s duration — subtle, professional
        - Last caption (closing): "fade_in" with 0.4s duration — slightly more deliberate
        - All other captions: "none" (stable, readable)
        - Never use "bounce" or "pop" (too flashy for insurance content)
        - If clip < 10s, skip special animations (too short to notice)
        """
        if not words_with_timestamps or clip_duration <= 0:
            return {
                "intro_animation": "none",
                "intro_duration": 0.0,
                "closing_animation": "none",
                "closing_duration": 0.0,
                "standard_animation": "none",
            }

        # Short clips: no special animations
        if clip_duration < 10.0:
            return {
                "intro_animation": "none",
                "intro_duration": 0.0,
                "closing_animation": "none",
                "closing_duration": 0.0,
                "standard_animation": "none",
            }

        return {
            "intro_animation": "fade_in",
            "intro_duration": 0.3,
            "closing_animation": "fade_in",
            "closing_duration": 0.4,
            "standard_animation": "none",
        }

    @staticmethod
    def _compute_subtitle_rhythm(
        words_with_timestamps: List[Dict],
        max_words_per_line: int = 4,
        min_duration_per_line: float = 1.0,
        max_duration_per_line: float = 3.5,
    ) -> List[Dict]:
        """Compute typographic rhythm for subtitles.

        Groups words into lines with intentional pacing that reflects
        the spoken rhythm. Rules:

        1. Line breaks at natural pauses (gap ≥ 0.3s between words)
        2. Max 4 words per line (readability)
        3. Min 1.0s per line (avoids flashing)
        4. Max 3.5s per line (avoids stagnation)
        5. Keep emphasis words together (don't isolate them)
        6. Prefer 2-3 word lines for fast speech, 3-4 for slow speech

        Returns list of line dicts with:
        - words: list of word dicts
        - start: line start time
        - end: line end time
        - text: joined text
        - word_count: number of words
        """
        if not words_with_timestamps:
            return []

        _lines: List[Dict] = []
        _current_line: List[Dict] = []
        _line_start = 0.0

        for i, w in enumerate(words_with_timestamps):
            _word = {
                "word": w.get("word", ""),
                "start": w.get("start", 0),
                "end": w.get("end", 0),
                "is_emphasis": w.get("is_emphasis", False),
            }

            if not _current_line:
                # Start new line
                _current_line = [_word]
                _line_start = _word["start"]
                continue

            _prev_end = _current_line[-1]["end"]
            _gap = _word["start"] - _prev_end
            _line_dur = _word["end"] - _line_start

            # Break line if:
            # 1. Natural pause (gap ≥ 0.3s)
            # 2. Max words reached (4)
            # 3. Max duration reached (3.5s)
            # 4. Emphasis word would be isolated (keep with previous)
            _should_break = False

            if _gap >= 0.3:
                _should_break = True  # Natural pause
            elif len(_current_line) >= max_words_per_line:
                _should_break = True  # Max words
            elif _line_dur >= max_duration_per_line:
                _should_break = True  # Max duration

            # Don't break if it would isolate an emphasis word
            if _should_break and _word.get("is_emphasis") and len(_current_line) < 2:
                _should_break = False  # Keep emphasis word with previous

            if _should_break:
                # Finalize current line
                _lines.append({
                    "words": _current_line,
                    "start": _line_start,
                    "end": _current_line[-1]["end"],
                    "text": " ".join(w["word"] for w in _current_line),
                    "word_count": len(_current_line),
                })
                # Start new line
                _current_line = [_word]
                _line_start = _word["start"]
            else:
                _current_line.append(_word)

        # Finalize last line
        if _current_line:
            _lines.append({
                "words": _current_line,
                "start": _line_start,
                "end": _current_line[-1]["end"],
                "text": " ".join(w["word"] for w in _current_line),
                "word_count": len(_current_line),
            })

        # Enforce minimum duration per line
        for _line in _lines:
            _dur = _line["end"] - _line["start"]
            if _dur < min_duration_per_line:
                _line["end"] = _line["start"] + min_duration_per_line

        logger.info(
            "[SubtitleRhythm] %d lines from %d words (avg %.1f words/line)",
            len(_lines), len(words_with_timestamps),
            len(words_with_timestamps) / max(len(_lines), 1),
        )
        return _lines

    @staticmethod
    def _compute_caption_emphasis(
        words_with_timestamps: List[Dict],
        segment_text: str = "",
    ) -> List[Dict]:
        """Compute emphasis flags for caption words.

        Marks words that should be visually emphasized in captions:
        - Hook words: first 3 words of the clip (strong opening)
        - Claim words: "secret", "never", "the reason", "because", etc.
        - CTA words: "subscribe", "follow", "share", "register", etc.
        - Emotional words: "increíble", "shocking", "amazing", etc.
        - Numbers: any digits
        - Named entities: capitalized words not at sentence start

        Returns the same list with an added `is_emphasis` boolean field.
        Only ~15% of words are emphasized to avoid over-animating.
        """
        if not words_with_timestamps:
            return []

        _CLAIM_WORDS = {
            "secret", "secreto", "never", "nunca", "always", "siempre",
            "everyone", "todos", "nadie", "nobody", "the reason",
            "la razón", "because", "porque", "that's why", "por eso",
            "actually", "en realidad", "the truth", "la verdad",
            "nadie te dice", "what if", "y si", "imagina", "imagine",
            "the key", "la clave", "the secret", "el secreto",
            "the best", "el mejor", "the worst", "el peor",
        }
        _CTA_WORDS = {
            "subscribe", "suscríbete", "follow", "sígueme", "comparte",
            "share", "like", "dale like", "comenta", "comment",
            "register", "regístrate", "sign up", "apúntate",
            "join", "únete", "download", "descarga", "click",
            "link", "enlace", "bio", "call", "llama", "contact",
            "visita", "visit", "more info", "más información",
        }
        _EMOTIONAL_WORDS = {
            "increíble", "incredible", "sorprendente", "shocking",
            "brutal", "alucinante", "impresionante", "unbelievable",
            "crazy", "insane", "mind-blowing", "wow", "guau",
            "terrible", "horrible", "fantástico", "fantastic",
            "espectacular", "spectacular", "genial", "great",
            "life-changing", "transformador", "game changer",
            "never be the same", "nunca será igual", "forever",
            "para siempre", "the best decision", "la mejor decisión",
            "you deserve", "te mereces", "peace of mind", "tranquilidad",
        }

        import re as _re

        _result = []
        _emphasis_count = 0
        _total_words = len(words_with_timestamps)
        _MAX_EMPHASIS_PCT = 0.15  # max 15% of words emphasized

        for i, w in enumerate(words_with_timestamps):
            _word = (w.get("word") or "").strip()
            _lower = _word.lower().strip(".,!?;:'\"")
            _is_emphasis = False

            # Hook words: first 3 words
            if i < 3:
                _is_emphasis = True

            # Claim words
            if not _is_emphasis and _lower in _CLAIM_WORDS:
                _is_emphasis = True

            # CTA words
            if not _is_emphasis and _lower in _CTA_WORDS:
                _is_emphasis = True

            # Emotional words
            if not _is_emphasis and _lower in _EMOTIONAL_WORDS:
                _is_emphasis = True

            # Numbers
            if not _is_emphasis and _re.search(r'\d', _word):
                _is_emphasis = True

            # Named entities (capitalized, not at sentence start)
            if not _is_emphasis and _word and _word[0].isupper() and i > 0:
                _prev = (words_with_timestamps[i-1].get("word") or "").strip()
                if _prev and not _prev.endswith("."):
                    _is_emphasis = True

            # Cap at MAX_EMPHASIS_PCT
            if _is_emphasis and _emphasis_count / max(_total_words, 1) >= _MAX_EMPHASIS_PCT:
                _is_emphasis = False

            if _is_emphasis:
                _emphasis_count += 1

            _result.append({
                "word": _word,
                "start": w.get("start", 0),
                "end": w.get("end", 0),
                "confidence": w.get("confidence", 0.9),
                "is_emphasis": _is_emphasis,
            })

        logger.info(
            "[CaptionEmphasis] %d/%d words emphasized (%.0f%%)",
            _emphasis_count, _total_words,
            _emphasis_count / max(_total_words, 1) * 100,
        )
        return _result

    @staticmethod
    def _compute_hook_sound_cues(
        hook_text: str,
        hook_score: float = 0.0,
        hook_start_time: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Compute subtle sound cues to strengthen the opening hook.

        Returns a list of sound cue dicts with:
        - timestamp: when to play the cue
        - type: SFX type from SoundDesignService
        - intensity: 0.0–1.0 (subtle for insurance content)
        - reason: why this cue was selected

        Rules:
        - Always add a subtle riser 0.3s before the hook starts (build anticipation)
        - If hook contains exclamation/question: add soft impact at hook start
        - If hook contains numbers: add subtle emphasis chime
        - If hook contains claim markers ("secret", "never"): add soft reveal tone
        - Never exceed 2 cues in the first 3 seconds (keep it clean)
        - All cues at intensity ≤ 0.5 (insurance-appropriate, not aggressive)
        """
        if not hook_text:
            return []

        _cues: List[Dict[str, Any]] = []
        _lower = hook_text.lower()

        # Riser before hook (builds anticipation without being aggressive)
        _riser_ts = max(0.0, hook_start_time - 0.3)
        _cues.append({
            "timestamp": _riser_ts,
            "type": "riser_pre_reveal",
            "intensity": 0.35,
            "reason": "pre-hook anticipation",
        })

        # Soft impact at hook start if emotional
        if "!" in hook_text or "?" in hook_text:
            _cues.append({
                "timestamp": hook_start_time + 0.1,
                "type": "emphasis_word",
                "intensity": 0.40,
                "reason": "hook exclamation/question emphasis",
            })

        # Subtle chime for numbers
        import re as _re
        if _re.search(r'\d+', hook_text):
            _cues.append({
                "timestamp": hook_start_time + 0.15,
                "type": "notification",
                "intensity": 0.30,
                "reason": "hook contains numbers",
            })

        # Soft reveal tone for claim markers
        _CLAIM_MARKERS = {"secret", "secreto", "never", "nunca", "the reason",
                          "la razón", "because", "porque", "actually", "en realidad",
                          "the truth", "la verdad", "nadie te dice", "what if"}
        if any(m in _lower for m in _CLAIM_MARKERS):
            _cues.append({
                "timestamp": hook_start_time + 0.2,
                "type": "insight_reveal",
                "intensity": 0.45,
                "reason": "hook claim marker emphasis",
            })

        # Cap at 2 cues in first 3s
        _cues = [c for c in _cues if c["timestamp"] < 3.0][:2]

        logger.info(
            "[BRoll/HookSound] %d hook sound cues: %s",
            len(_cues), [(c["type"], c["timestamp"]) for c in _cues],
        )
        return _cues

    @staticmethod
    def _select_strongest_hook(
        segment_text: str,
        words_with_timestamps: Optional[List[Dict]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Identify the strongest hook candidate in the first 10 seconds of a clip.

        Scores each sentence in the first 10s by:
        - Emotional impact: exclamation marks, question marks, surprise words
        - Specificity: numbers, named entities, concrete nouns
        - Brevity: shorter sentences score higher (punchier)
        - Novelty: claim markers ("secret", "never", "the reason") boost score

        Returns a dict with:
        - text: the hook sentence
        - score: 0.0–1.0
        - start_time: timestamp in seconds
        - reason: why this was selected

        Returns None if no strong hook found (clip should use the first sentence).
        """
        if not segment_text:
            return None

        import re as _re

        # Split into sentences
        _sentences = _re.split(r'(?<=[.!?])\s+', segment_text.strip())
        _sentences = [s for s in _sentences if s]

        if not _sentences:
            return None

        # Score each sentence
        _scored: List[Tuple[float, str, int]] = []  # (score, text, index)
        _EMOTIONAL_WORDS = {
            "increíble", "incredible", "sorprendente", "shocking",
            "brutal", "alucinante", "impresionante", "unbelievable",
            "crazy", "insane", "mind-blowing", "wow", "guau",
            "terrible", "horrible", "fantástico", "fantastic",
            "espectacular", "spectacular", "genial", "great",
        }
        _CLAIM_WORDS = {
            "secret", "secreto", "never", "nunca", "always", "siempre",
            "everyone", "todos", "nadie", "nobody", "the reason",
            "la razón", "because", "porque", "that's why", "por eso",
            "actually", "en realidad", "the truth", "la verdad",
            "nadie te dice", "what if", "y si", "imagina", "imagine",
        }
        _SOFT_INTROS = {
            "hola", "hello", "hi", "buenos días", "buenas tardes",
            "bienvenido", "welcome", "qué tal", "how are you",
            "hoy vamos", "today we", "en este video", "in this video",
            "el día de hoy", "el dia de hoy",
        }

        for i, sent in enumerate(_sentences):
            _lower = sent.lower()
            _score = 0.0

            # Penalize soft intros
            if any(si in _lower for si in _SOFT_INTROS):
                _score -= 0.5

            # Boost emotional words
            _emo_hits = sum(1 for w in _EMOTIONAL_WORDS if w in _lower)
            _score += min(0.4, _emo_hits * 0.15)

            # Boost claim markers
            _claim_hits = sum(1 for w in _CLAIM_WORDS if w in _lower)
            _score += min(0.3, _claim_hits * 0.1)

            # Boost numbers
            if _re.search(r'\d+', sent):
                _score += 0.2

            # Boost exclamation and question marks
            _exclams = sent.count("!") + sent.count("?")
            _score += min(0.2, _exclams * 0.1)

            # Boost brevity (shorter = punchier)
            _word_count = len(sent.split())
            if _word_count <= 8:
                _score += 0.15
            elif _word_count <= 15:
                _score += 0.05

            # Boost named entities (capitalized words not at start)
            _words = sent.split()
            _named_entities = sum(1 for w in _words[1:] if w and w[0].isupper())
            _score += min(0.15, _named_entities * 0.05)

            _scored.append((_score, sent, i))

        # Sort by score descending
        _scored.sort(key=lambda x: x[0], reverse=True)

        if not _scored:
            return None

        _best_score, _best_text, _best_idx = _scored[0]

        # Find timestamp for this sentence
        _start_time = 0.0
        if words_with_timestamps:
            _sent_words = _best_text.split()
            for w in words_with_timestamps:
                _w_text = (w.get("word") or "").lower().strip(".,!?;:'\"")
                if _sent_words and _w_text == _sent_words[0].lower().strip(".,!?;:'\""):
                    _start_time = float(w.get("start", 0))
                    break

        # Determine reason
        _reasons = []
        if _best_score >= 0.5:
            _reasons.append("strong emotional impact")
        if any(c in _best_text for c in "!?"):
            _reasons.append("exclamation/question")
        if _re.search(r'\d+', _best_text):
            _reasons.append("contains numbers")
        if len(_best_text.split()) <= 8:
            _reasons.append("short and punchy")

        logger.info(
            "[BRoll/Hook] Strongest hook: score=%.2f text='%s' at t=%.1fs — %s",
            _best_score, _best_text[:60], _start_time,
            ", ".join(_reasons) if _reasons else "default",
        )

        return {
            "text": _best_text,
            "score": _best_score,
            "start_time": _start_time,
            "reason": ", ".join(_reasons) if _reasons else "default",
        }

    @staticmethod
    def _classify_tone(segment_text: str, words_with_timestamps: Optional[List[Dict]] = None) -> str:
        """Classify the emotional tone of a transcript segment.

        Returns one of: "calm_explanatory", "neutral", "active_hook", "urgent_claim"

        Detection rules:
        - calm_explanatory: long sentences, few exclamations, technical/educational language
        - active_hook: short sentences, exclamation marks, question marks, surprise markers
        - urgent_claim: numbers, claims ("because", "the reason"), imperative verbs
        - neutral: everything else

        Used by _resolve_broll_style() to select tone-appropriate visual profiles.
        """
        _text = (segment_text or "").lower()
        _exclams = _text.count("!") + _text.count("?")
        _words = _text.split()
        _n_words = len(_words)
        _avg_word_len = len(_text.replace(" ", "")) / max(_n_words, 1) if _n_words > 0 else 5.0

        # Urgent claim: numbers + claim markers
        _has_numbers = bool(re.search(r'\d+', _text))
        _claim_markers = {"because", "porque", "reason", "razón", "that's why",
                          "por eso", "actually", "en realidad", "the truth",
                          "la verdad", "secret", "secreto", "never", "nunca",
                          "always", "siempre", "everyone", "todos"}
        _claim_hits = sum(1 for m in _claim_markers if m in _text)

        # Active hook: short avg word length + exclamations
        if _exclams >= 2 and _avg_word_len < 4.5:
            return "active_hook"
        if _has_numbers and _claim_hits >= 2:
            return "urgent_claim"
        if _exclams >= 1 and _has_numbers:
            return "active_hook"

        # Calm explanatory: long words, few exclamations, educational markers
        _edu_markers = {"explain", "explicar", "understand", "entender",
                        "meaning", "significa", "means", "quiere decir",
                        "basically", "básicamente", "essentially", "esencialmente",
                        "in other words", "es decir", "for example", "por ejemplo"}
        _edu_hits = sum(1 for m in _edu_markers if m in _text)
        if _avg_word_len > 5.5 and _exclams == 0:
            return "calm_explanatory"
        if _edu_hits >= 2 and _exclams == 0:
            return "calm_explanatory"

        return "neutral"

    @staticmethod
    def _resolve_broll_style(category: str = "", topic: str = "", tone: str = "neutral") -> str:
        """Map content category/topic + tone to a B-roll style profile name."""
        _cat = (category or topic or "").lower()

        # Tone-aware style selection
        if tone == "calm_explanatory":
            # Calm visuals: prefer env/abstract, low density
            if any(kw in _cat for kw in ("insurance", "finance", "invest", "money")):
                return "insurance_explainer"
            return "generic"
        if tone == "active_hook":
            # Active visuals: prefer human, higher density
            if any(kw in _cat for kw in ("insurance", "finance", "invest", "money")):
                return "insurance_testimonial"
            return "coaching"
        if tone == "urgent_claim":
            # Urgent visuals: prefer object/action, tight framing
            if any(kw in _cat for kw in ("insurance", "finance", "invest", "money")):
                return "insurance_claim"
            return "finance"

        # Default: category-based selection
        if any(kw in _cat for kw in ("finance", "invest", "money", "business", "insurance")):
            return "finance"
        if any(kw in _cat for kw in ("podcast", "interview", "conversation")):
            return "podcast"
        if any(kw in _cat for kw in ("coach", "motivation", "mindset", "training", "seminar")):
            return "coaching"
        return "generic"

    @staticmethod
    def _apply_grading_normalization(
        assets: List[Path],
        color_temperature: str = "neutral",
        lut_vf: str = "",
    ) -> List[Path]:
        """Apply subtle grading normalization to B-roll assets for visual consistency.

        Uses FFmpeg eq filter to normalize brightness, contrast, and saturation
        based on the task's color_temperature preference. This prevents abrupt
        color shifts between B-roll assets from different sources.

        Grading rules:
        - warm: +0.05 saturation, +0.03 brightness, slight red shift
        - neutral: no change (default)
        - cool: -0.03 saturation, +0.02 contrast, slight blue shift

        If lut_vf is provided (from EditingPipeline), it is applied instead of
        the generic eq filter for a more precise grade match.

        Returns list of graded asset paths (same list if grading fails).
        """
        if not assets or color_temperature == "neutral":
            return assets

        _graded: List[Path] = []
        for _a in assets:
            try:
                _graded_path = _a.with_name(f"grd_{_a.name}")
                if lut_vf:
                    # Use the same LUT filter as the main clip
                    _vf = lut_vf
                else:
                    # Build eq filter from color_temperature
                    if color_temperature == "warm":
                        _vf = "eq=saturation=1.05:brightness=0.03:contrast=1.02"
                    elif color_temperature == "cool":
                        _vf = "eq=saturation=0.97:brightness=-0.01:contrast=1.03"
                    else:
                        _vf = ""

                if _vf:
                    _cmd = [
                        "ffmpeg", "-y", "-i", str(_a),
                        "-vf", _vf,
                        "-c:a", "copy",
                        str(_graded_path),
                    ]
                    _res = subprocess.run(_cmd, capture_output=True, timeout=30)
                    if _res.returncode == 0 and _graded_path.exists():
                        _graded.append(_graded_path)
                        logger.debug(
                            "[BRoll] Grading normalization applied to %s (temp=%s)",
                            _a.name, color_temperature,
                        )
                        continue
                _graded.append(_a)
            except Exception as _g_e:
                logger.debug("[BRoll] Grading normalization failed for %s: %s", _a.name, _g_e)
                _graded.append(_a)

        if len(_graded) != len(assets):
            logger.warning(
                "[BRoll] Grading normalization: %d/%d assets graded",
                len(_graded), len(assets),
            )
        return _graded

    @staticmethod
    def _compute_export_score(
        clip_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compute a numerical export score for a clip using hard criteria.

        Scores 6 dimensions (0–10 each), weighted into a final score (0–100).
        Blocks export if any dimension scores below its minimum threshold.

        Dimensions and weights:
        1. Hook strength (20%) — score 0–10, min 5.0
        2. Pacing consistency (15%) — score 0–10, min 4.0
        3. Subtitle readability (15%) — score 0–10, min 5.0
        4. Audio balance (20%) — score 0–10, min 5.0
        5. Visual quality (15%) — score 0–10, min 4.0
        6. Ending quality (15%) — score 0–10, min 5.0

        Returns dict with:
        - dimensions: list of per-dimension scores
        - final_score: 0–100 weighted score
        - export_decision: "export" | "blocked"
        - block_reasons: list of reasons if blocked
        """
        _dimensions: List[Dict[str, Any]] = []
        _block_reasons: List[str] = []

        # 1. Hook strength (20%)
        _hook_score = min(10.0, max(0.0, float(clip_data.get("hook_score", 0) or 0)))
        _hook_type = clip_data.get("hook_type", "") or ""
        _dimensions.append({
            "name": "Hook Strength",
            "score": _hook_score,
            "weight": 0.20,
            "min": 5.0,
            "detail": f"Hook score {_hook_score:.1f}/10, type={_hook_type}",
        })
        if _hook_score < 5.0:
            _block_reasons.append(f"Hook too weak ({_hook_score:.1f}/10)")

        # 2. Pacing consistency (15%)
        _broll_count = clip_data.get("broll_count", 0) or 0
        _duration = clip_data.get("duration", 0) or 0
        if _duration > 0:
            _broll_per_min = _broll_count / (_duration / 60.0)
            if 1 <= _broll_per_min <= 6:
                _pacing_score = 10.0
            elif _broll_per_min < 1:
                _pacing_score = max(0.0, _broll_per_min * 10.0)
            else:
                _pacing_score = max(0.0, 10.0 - (_broll_per_min - 6.0) * 2.0)
        else:
            _pacing_score = 5.0
        _dimensions.append({
            "name": "Pacing Consistency",
            "score": _pacing_score,
            "weight": 0.15,
            "min": 4.0,
            "detail": f"{_broll_count} B-rolls in {_duration:.0f}s ({_broll_per_min:.1f}/min)" if _duration > 0 else "No duration data",
        })
        if _pacing_score < 4.0:
            _block_reasons.append(f"Pacing outside range ({_pacing_score:.1f}/10)")

        # 3. Subtitle readability (15%)
        _has_captions = bool(clip_data.get("words"))
        _caption_system = clip_data.get("caption_system_used", "none")
        if _has_captions and _caption_system != "none":
            _sub_score = 10.0
        elif _has_captions:
            _sub_score = 6.0
        else:
            _sub_score = 0.0
        _dimensions.append({
            "name": "Subtitle Readability",
            "score": _sub_score,
            "weight": 0.15,
            "min": 5.0,
            "detail": f"Captions={'Y' if _has_captions else 'N'}, system={_caption_system}",
        })
        if _sub_score < 5.0:
            _block_reasons.append(f"No captions ({_sub_score:.1f}/10)")

        # 4. Audio balance (20%)
        _audio_features = clip_data.get("audio_features", {}) or {}
        _loudnorm_applied = _audio_features.get("loudnorm_applied", False)
        _audio_energy = _audio_features.get("energy", 0.5)
        _audio_score = 0.0
        if _loudnorm_applied:
            _audio_score += 5.0
        if _audio_energy >= 0.3:
            _audio_score += 5.0
        elif _audio_energy >= 0.2:
            _audio_score += 3.0
        else:
            _audio_score += 1.0
        _dimensions.append({
            "name": "Audio Balance",
            "score": _audio_score,
            "weight": 0.20,
            "min": 5.0,
            "detail": f"Loudnorm={'Y' if _loudnorm_applied else 'N'}, energy={_audio_energy:.2f}",
        })
        if _audio_score < 5.0:
            _block_reasons.append(f"Audio balance issues ({_audio_score:.1f}/10)")

        # 5. Visual quality (15%)
        _broll_assets = clip_data.get("broll_assets", []) or []
        _broll_count_actual = len(_broll_assets)
        _visual_score = min(10.0, _broll_count_actual * 3.0) if _broll_count_actual > 0 else 5.0
        _dimensions.append({
            "name": "Visual Quality",
            "score": _visual_score,
            "weight": 0.15,
            "min": 4.0,
            "detail": f"{_broll_count_actual} B-roll assets",
        })
        if _visual_score < 4.0:
            _block_reasons.append(f"Low visual quality ({_visual_score:.1f}/10)")

        # 6. Ending quality (15%)
        _virality = min(10.0, max(0.0, float(clip_data.get("virality_score", 0) or 0)))
        _dimensions.append({
            "name": "Ending Quality",
            "score": _virality,
            "weight": 0.15,
            "min": 5.0,
            "detail": f"Virality score {_virality:.1f}/10",
        })
        if _virality < 5.0:
            _block_reasons.append(f"Low virality ({_virality:.1f}/10)")

        # Compute final weighted score
        _final_score = sum(d["score"] * d["weight"] * 10 for d in _dimensions)
        _final_score = max(0.0, min(100.0, _final_score))

        _export_decision = "blocked" if _block_reasons else "export"

        logger.info(
            "[ExportScore] Final=%d/100 Decision=%s Dimensions=%s",
            _final_score, _export_decision,
            {d["name"]: f"{d['score']:.1f}/10" for d in _dimensions},
        )
        if _block_reasons:
            logger.warning("[ExportScore] Blocked: %s", "; ".join(_block_reasons))

        return {
            "dimensions": _dimensions,
            "final_score": round(_final_score, 1),
            "export_decision": _export_decision,
            "block_reasons": _block_reasons,
        }

    @staticmethod
    def _run_pre_export_audit(
        clip_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run a strict quality audit on a generated clip before export.

        Checks 6 areas:
        1. Hook strength — first 3s must have strong hook (score ≥ 5.0)
        2. Pacing consistency — B-roll spacing must be within expected range
        3. Subtitle readability — captions present, emphasis ≤ 15%
        4. Audio balance — ducking applied, no clipping
        5. B-roll relevance — assets scored above threshold
        6. Ending quality — closing line scored above threshold

        Returns dict with:
        - pass: bool (True only if ALL checks pass)
        - checks: list of check results
        - summary: human-readable summary
        - hard_failures: list of failed checks (any = do not export)
        """
        _checks: List[Dict[str, Any]] = []
        _hard_failures: List[str] = []

        # 1. Hook strength
        _hook_score = clip_data.get("hook_score", 0) or 0
        _hook_type = clip_data.get("hook_type", "") or ""
        if _hook_score >= 5.0:
            _checks.append({
                "name": "Hook Strength",
                "pass": True,
                "detail": f"Hook score {_hook_score}/10, type={_hook_type}",
            })
        else:
            _checks.append({
                "name": "Hook Strength",
                "pass": False,
                "detail": f"Hook score {_hook_score}/10 < 5.0 minimum",
            })
            _hard_failures.append("Hook too weak")

        # 2. Pacing consistency
        _broll_count = clip_data.get("broll_count", 0) or 0
        _duration = clip_data.get("duration", 0) or 0
        if _duration > 0:
            _broll_per_min = _broll_count / (_duration / 60.0)
            if 1 <= _broll_per_min <= 6:
                _checks.append({
                    "name": "Pacing Consistency",
                    "pass": True,
                    "detail": f"{_broll_count} B-rolls in {_duration:.0f}s ({_broll_per_min:.1f}/min)",
                })
            else:
                _checks.append({
                    "name": "Pacing Consistency",
                    "pass": False,
                    "detail": f"{_broll_count} B-rolls in {_duration:.0f}s ({_broll_per_min:.1f}/min) — outside 1-6/min range",
                })
                _hard_failures.append("Pacing outside expected range")

        # 3. Subtitle readability
        _has_captions = bool(clip_data.get("words"))
        _caption_system = clip_data.get("caption_system_used", "none")
        if _has_captions and _caption_system != "none":
            _checks.append({
                "name": "Subtitle Readability",
                "pass": True,
                "detail": f"Captions present ({_caption_system})",
            })
        else:
            _checks.append({
                "name": "Subtitle Readability",
                "pass": False,
                "detail": f"Captions missing (system={_caption_system})",
            })
            _hard_failures.append("No captions")

        # 4. Audio balance
        _audio_features = clip_data.get("audio_features", {}) or {}
        _loudnorm_applied = _audio_features.get("loudnorm_applied", False)
        _audio_energy = _audio_features.get("energy", 0.5)
        if _loudnorm_applied and _audio_energy >= 0.3:
            _checks.append({
                "name": "Audio Balance",
                "pass": True,
                "detail": f"Loudnorm applied, energy={_audio_energy:.2f}",
            })
        else:
            _checks.append({
                "name": "Audio Balance",
                "pass": False,
                "detail": f"Loudnorm={'Y' if _loudnorm_applied else 'N'}, energy={_audio_energy:.2f}",
            })
            _hard_failures.append("Audio balance issues")

        # 5. B-roll relevance
        _broll_assets = clip_data.get("broll_assets", []) or []
        _broll_count_actual = len(_broll_assets)
        if _broll_count_actual > 0 or _broll_count == 0:
            _checks.append({
                "name": "B-Roll Relevance",
                "pass": True,
                "detail": f"{_broll_count_actual} assets selected",
            })
        else:
            _checks.append({
                "name": "B-Roll Relevance",
                "pass": False,
                "detail": "No B-roll assets selected",
            })

        # 6. Ending quality
        _virality = clip_data.get("virality_score", 0) or 0
        if _virality >= 5.0:
            _checks.append({
                "name": "Ending Quality",
                "pass": True,
                "detail": f"Virality score {_virality}/10",
            })
        else:
            _checks.append({
                "name": "Ending Quality",
                "pass": False,
                "detail": f"Virality score {_virality}/10 < 5.0",
            })
            _hard_failures.append("Low virality score")

        _all_pass = len(_hard_failures) == 0
        _summary = (
            f"{'✅ PASS' if _all_pass else '❌ FAIL'}: "
            f"{sum(1 for c in _checks if c['pass'])}/{len(_checks)} checks passed"
        )
        if _hard_failures:
            _summary += f" — hard failures: {', '.join(_hard_failures)}"

        logger.info(
            "[PreExportAudit] %s — %s",
            _summary,
            {c["name"]: "PASS" if c["pass"] else "FAIL" for c in _checks},
        )
        return {
            "pass": _all_pass,
            "checks": _checks,
            "summary": _summary,
            "hard_failures": _hard_failures,
        }

    @staticmethod
    def _get_clip_type_visual_rules(clip_type: str) -> Dict[str, Any]:
        """Get visual polish rules for a specific clip type.

        Maps clip types to visual parameters:
        - educational: lighter, cleaner motion — low motion, soft transitions, neutral color
        - testimonial: minimal motion, more trust — low motion, warm color, soft transitions
        - claim/risk: slightly more emphasis — medium motion, cool color, standard transitions
        - cta: stronger closing presence — medium motion, warm color, standard transitions

        Returns dict with: motion_level, transition_style, color_temperature,
        zoom_intensity, caption_animation, overlay_duration, min_gap.
        """
        _rules = {
            "educational": {
                "motion_level": "low",
                "transition_style": "soft",
                "color_temperature": "neutral",
                "zoom_intensity": 1.02,
                "caption_animation": "none",
                "overlay_duration": 3.5,
                "min_gap": 10.0,
                "description": "Lighter, cleaner motion for educational content",
            },
            "testimonial": {
                "motion_level": "low",
                "transition_style": "soft",
                "color_temperature": "warm",
                "zoom_intensity": 1.02,
                "caption_animation": "none",
                "overlay_duration": 4.0,
                "min_gap": 12.0,
                "description": "Minimal motion, more trust for testimonials",
            },
            "claim": {
                "motion_level": "medium",
                "transition_style": "standard",
                "color_temperature": "cool",
                "zoom_intensity": 1.04,
                "caption_animation": "karaoke",
                "overlay_duration": 3.5,
                "min_gap": 8.0,
                "description": "Slightly more emphasis for claims and risk content",
            },
            "cta": {
                "motion_level": "medium",
                "transition_style": "standard",
                "color_temperature": "warm",
                "zoom_intensity": 1.04,
                "caption_animation": "karaoke",
                "overlay_duration": 3.0,
                "min_gap": 6.0,
                "description": "Stronger closing presence for CTAs",
            },
        }
        return _rules.get(clip_type, _rules["educational"])

    @staticmethod
    def _compute_key_moment_zooms(
        segment_text: str,
        words_with_timestamps: Optional[List[Dict]] = None,
        clip_duration: float = 0.0,
    ) -> List[Dict[str, Any]]:
        """Compute subtle zoom/punch-in timestamps for key moments.

        Zooms only on important lines to reinforce the message:
        - Hook words: first 3 words of the clip
        - Claim markers: "secret", "never", "the reason", "because"
        - Emotional words: "increíble", "shocking", "life-changing"
        - Numbers: statistics and data points
        - CTA words: "subscribe", "follow", "call", "visit"

        Rules:
        - Max 3 zooms per clip (restrained)
        - No zooms in the first 1.5s (let hook breathe)
        - No zooms in the last 1.5s (CTA zone)
        - No two zooms within 4s of each other
        - Zoom factor: 1.04x (subtle, not distracting)
        - Zoom duration: 0.3s (smooth, not jarring)
        - Never zoom during subtitle display (avoid overlap)

        Returns list of zoom dicts with:
        - timestamp: when to start the zoom
        - factor: zoom scale (1.04)
        - duration: zoom animation duration (0.3s)
        - reason: why this moment was selected
        """
        if not segment_text or clip_duration <= 0:
            return []

        import re as _re

        _zooms: List[Dict[str, Any]] = []
        _HOOK_END = 1.5
        _CTA_START = max(0.0, clip_duration - 1.5)
        _MIN_ZOOM_GAP = 4.0
        _MAX_ZOOMS = 3
        _ZOOM_FACTOR = 1.04
        _ZOOM_DURATION = 0.3

        _CLAIM_WORDS = {
            "secret", "secreto", "never", "nunca", "always", "siempre",
            "everyone", "todos", "nadie", "nobody", "the reason",
            "la razón", "because", "porque", "that's why", "por eso",
            "actually", "en realidad", "the truth", "la verdad",
            "the key", "la clave", "the best", "el mejor",
        }
        _EMOTIONAL_WORDS = {
            "increíble", "incredible", "sorprendente", "shocking",
            "brutal", "alucinante", "life-changing", "transformador",
            "game changer", "never be the same", "peace of mind",
            "tranquilidad", "security", "seguridad",
        }
        _CTA_WORDS = {
            "subscribe", "suscríbete", "follow", "sígueme",
            "call", "llama", "visit", "visita", "register", "regístrate",
        }

        if words_with_timestamps:
            for w in words_with_timestamps:
                if len(_zooms) >= _MAX_ZOOMS:
                    break

                _word = (w.get("word") or "").strip()
                _ts = float(w.get("start", 0))
                _lower = _word.lower().strip(".,!?;:'\"")

                # Skip hook and CTA zones
                if _ts < _HOOK_END or _ts >= _CTA_START:
                    continue

                # Check gap from last zoom
                if _zooms and _ts - _zooms[-1]["timestamp"] < _MIN_ZOOM_GAP:
                    continue

                _reason = None

                # Claim markers
                if _lower in _CLAIM_WORDS:
                    _reason = f"claim marker: {_word}"

                # Emotional words
                if not _reason and _lower in _EMOTIONAL_WORDS:
                    _reason = f"emotional word: {_word}"

                # Numbers
                if not _reason and _re.search(r'\d', _word):
                    _reason = f"number: {_word}"

                # CTA words
                if not _reason and _lower in _CTA_WORDS:
                    _reason = f"CTA: {_word}"

                if _reason:
                    _zooms.append({
                        "timestamp": _ts,
                        "factor": _ZOOM_FACTOR,
                        "duration": _ZOOM_DURATION,
                        "reason": _reason,
                    })

        logger.info(
            "[BRoll/Zoom] %d key moment zooms: %s",
            len(_zooms), [(z["timestamp"], z["reason"]) for z in _zooms],
        )
        return _zooms

    @staticmethod
    def _compute_attention_resets(
        clip_duration: float,
        words_with_timestamps: Optional[List[Dict]] = None,
    ) -> List[float]:
        """Compute timestamps for subtle attention resets during a clip.

        Attention resets are small visual or rhythmic shifts that refresh
        the viewer's attention when it would otherwise dip. They are NOT
        B-roll overlays — they are subtle contrast changes applied via
        the EditingPipeline (e.g., brief saturation pulse, micro-zoom).

        Reset triggers (in priority order):
        1. Sentence boundaries (every 3rd sentence): natural narrative reset
        2. Topic changes: when the speaker shifts to a new idea
        3. Every 15s of continuous speech: prevents attention fatigue

        Rules:
        - Max 3 resets per clip (sparing use)
        - No resets in the first 3s (hook zone)
        - No resets in the last 2s (CTA zone)
        - No two resets within 5s of each other
        - Resets are subtle: 0.15s saturation pulse or 1.02x micro-zoom

        Returns list of timestamps in seconds.
        """
        if clip_duration <= 0:
            return []

        _resets: List[float] = []
        _hook_end = 3.0
        _cta_start = max(0.0, clip_duration - 2.0)
        _MIN_RESET_GAP = 5.0
        _MAX_RESETS = 3

        # 1. Sentence boundary resets (every 3rd sentence)
        if words_with_timestamps:
            _sentence_ends: List[float] = []
            for w in words_with_timestamps:
                _word = (w.get("word") or "").strip()
                _end = float(w.get("end", 0))
                if _word and _word[-1] in ".!?" and _end > _hook_end and _end < _cta_start:
                    _sentence_ends.append(_end)

            # Take every 3rd sentence end
            for i in range(2, len(_sentence_ends), 3):
                _ts = _sentence_ends[i]
                if all(abs(_ts - r) >= _MIN_RESET_GAP for r in _resets):
                    _resets.append(_ts)
                    if len(_resets) >= _MAX_RESETS:
                        break

        # 2. Every 15s of continuous speech (if fewer than 3 resets from sentences)
        if len(_resets) < _MAX_RESETS:
            for _t in range(int(_hook_end) + 15, int(_cta_start), 15):
                if len(_resets) >= _MAX_RESETS:
                    break
                if all(abs(_t - r) >= _MIN_RESET_GAP for r in _resets):
                    _resets.append(float(_t))

        logger.info(
            "[BRoll] Attention resets: %d at %s",
            len(_resets), [f"{t:.1f}s" for t in _resets],
        )
        return _resets

    @staticmethod
    def _apply_section_pacing(
        pairs: List[Tuple[float, str, float]],
        clip_duration: float,
    ) -> List[Tuple[float, str, float]]:
        """Adjust B-roll pacing by clip section: hook, explanation, closing.

        Section boundaries:
        - Hook: 0s to 25% of clip (fast, direct — minimal B-roll, let hook breathe)
        - Explanation: 25% to 75% of clip (balanced — main B-roll density)
        - Closing: 75% to 100% of clip (deliberate — slower, wider gaps)

        Pacing rules per section:
        - Hook (0–25%): max 1 B-roll, min gap 12s, overlay duration 2.5s
          (fast and direct — let the hook land without visual competition)
        - Explanation (25–75%): max 2 B-rolls, min gap 8s, overlay duration 3.5s
          (balanced and clear — standard pacing for information delivery)
        - Closing (75–100%): max 1 B-roll, min gap 14s, overlay duration 4.0s
          (slightly more deliberate — wider gaps for reflection)

        Returns filtered list of (timestamp, asset, duration) tuples.
        """
        if not pairs or clip_duration <= 0:
            return pairs

        _hook_end = clip_duration * 0.25
        _explanation_end = clip_duration * 0.75

        _section_pacing = {
            "hook": {"max": 1, "min_gap": 12.0, "overlay_dur": 2.5},
            "explanation": {"max": 2, "min_gap": 8.0, "overlay_dur": 3.5},
            "closing": {"max": 1, "min_gap": 14.0, "overlay_dur": 4.0},
        }

        _result: List[Tuple[float, str, float]] = []
        _hook_count = 0
        _explanation_count = 0
        _closing_count = 0
        _last_ts = {s: -p["min_gap"] for s, p in _section_pacing.items()}

        for ts, asset, dur in pairs:
            if ts < _hook_end:
                _section = "hook"
                _count_ref = _hook_count
            elif ts < _explanation_end:
                _section = "explanation"
                _count_ref = _explanation_count
            else:
                _section = "closing"
                _count_ref = _closing_count

            _pacing = _section_pacing[_section]

            # Check count limit
            if _count_ref >= _pacing["max"]:
                logger.debug(
                    "[BRoll/SectionPacing] Skipped cue at t=%.1fs (%s section) — "
                    "max %d reached",
                    ts, _section, _pacing["max"],
                )
                continue

            # Check gap
            if ts - _last_ts[_section] < _pacing["min_gap"]:
                logger.debug(
                    "[BRoll/SectionPacing] Skipped cue at t=%.1fs (%s section) — "
                    "gap %.1fs < min %.1fs",
                    ts, _section, ts - _last_ts[_section], _pacing["min_gap"],
                )
                continue

            # Apply section-specific overlay duration
            _adjusted_dur = min(dur, _pacing["overlay_dur"])
            _result.append((ts, asset, _adjusted_dur))
            _last_ts[_section] = ts

            if _section == "hook":
                _hook_count += 1
            elif _section == "explanation":
                _explanation_count += 1
            else:
                _closing_count += 1

        logger.info(
            "[BRoll/SectionPacing] Hook=%d Explanation=%d Closing=%d — total=%d",
            _hook_count, _explanation_count, _closing_count, len(_result),
        )
        return _result

    @staticmethod
    def _apply_pacing_rules(
        pairs: List[Tuple[float, str, float]],
        style: str,
        clip_duration: float,
    ) -> List[Tuple[float, str, float]]:
        """Apply pacing rules based on the visual style profile.

        Maps each style profile to specific pacing parameters:
        - overlay_duration: how long each B-roll plays
        - min_gap: minimum spacing between B-rolls
        - max_count: maximum B-rolls per clip

        Style-to-pacing mapping:
        - insurance_testimonial: calm, human-centric → longer shots, wider gaps
        - insurance_claim: practical, process → medium shots, standard gaps
        - insurance_explainer: educational, clean → structured, moderate
        - insurance_advisor: professional, trust → calm, wider gaps
        - insurance_corporate: restrained, clean → shorter shots, tighter gaps
        - generic: flexible → standard pacing
        """
        _profile = BROLL_STYLE_PROFILES.get(style, BROLL_STYLE_PROFILES["generic"])

        # Pacing parameters per style
        _PACING: Dict[str, Dict[str, float]] = {
            "insurance_testimonial": {
                "overlay_duration": 4.0,  # longer shots for emotional resonance
                "min_gap": 10.0,          # wider gaps for calm pacing
                "max_per_min": 3,         # fewer B-rolls per minute
            },
            "insurance_claim": {
                "overlay_duration": 3.5,  # medium shots for process clarity
                "min_gap": 8.0,           # standard gaps
                "max_per_min": 4,
            },
            "insurance_explainer": {
                "overlay_duration": 3.5,  # clean, structured
                "min_gap": 8.0,           # moderate gaps
                "max_per_min": 4,
            },
            "insurance_advisor": {
                "overlay_duration": 4.0,  # calm, trust-building
                "min_gap": 10.0,          # wider gaps
                "max_per_min": 3,
            },
            "insurance_corporate": {
                "overlay_duration": 3.0,  # shorter, tighter
                "min_gap": 6.0,           # tighter gaps
                "max_per_min": 5,
            },
            "generic": {
                "overlay_duration": 3.5,
                "min_gap": 8.0,
                "max_per_min": 4,
            },
        }

        _pacing = _PACING.get(style, _PACING["generic"])
        _max_count = max(1, int(clip_duration / 60.0 * _pacing["max_per_min"])) if clip_duration > 0 else len(pairs)

        # Apply pacing: filter by min_gap and max_count
        _result: List[Tuple[float, str, float]] = []
        _last_end = -_pacing["min_gap"]
        for ts, asset, dur in pairs:
            if len(_result) >= _max_count:
                break
            if ts - _last_end >= _pacing["min_gap"]:
                # Use style-specific overlay duration
                _adjusted_dur = min(dur, _pacing["overlay_duration"])
                _result.append((ts, asset, _adjusted_dur))
                _last_end = ts + _adjusted_dur

        logger.info(
            "[BRoll] Pacing for style '%s': overlay=%.1fs gap=%.1fs max=%d → %d cues",
            style, _pacing["overlay_duration"], _pacing["min_gap"],
            _max_count, len(_result),
        )
        return _result

    @staticmethod
    def _apply_style_preferences(
        assets: List[Path],
        style: str,
        clip_duration: float,
    ) -> List[Path]:
        """
        Re-rank and filter assets according to the B-roll style profile.
        
        - Boosts assets whose filename/tags contain preferred_tags for the style.
        - Caps count at style's max_per_min.
        - Returns filtered list.
        """
        _profile = BROLL_STYLE_PROFILES.get(style, BROLL_STYLE_PROFILES["generic"])
        _preferred = _profile["preferred_tags"]
        _max = max(1, int(clip_duration / 60.0 * _profile["max_per_min"])) if clip_duration > 0 else len(assets)
        
        # Score each asset by how many preferred tags appear in its filename
        _scored: List[Tuple[float, Path]] = []
        for _a in assets:
            _name = _a.stem.lower().replace("_", " ")
            _match_count = sum(1 for t in _preferred if t in _name)
            _scored.append((_match_count, _a))
        
        # Sort by match count descending, then take top N
        _scored.sort(key=lambda x: x[0], reverse=True)
        _result = [a for _, a in _scored[:max(1, _max)]]
        
        if len(_result) < len(assets):
            logger.info(
                "[BRoll] Style '%s' filtered %d → %d assets (max_per_min=%d)",
                style, len(assets), len(_result), _profile["max_per_min"],
            )
        return _result

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ──────────────────────────────────────────────────────────────────────────

    async def process_clip(
        self,
        video_path: str,
        output_path: str,
        segment_text: str,
        audio_path: Optional[str] = None,
        clip_duration: float = 0.0,
        max_overlays: int = 3,
        overlay_duration_s: float = _BROLL_DURATION,
        words_with_timestamps: Optional[List[Dict]] = None,
        precomputed_keywords: Optional[List[str]] = None,
        broll_fade_s: float = 0.25,
        lut_vf: str = "",
        broll_style: str = "",  # NEW: style profile name
        task_id: Optional[str] = None,  # FIX 4: task_id for anti-repetition across clips
        seen_concepts: Optional[set] = None,  # RULE 4: concept-level tracking across clips
        pre_clip_concepts: Optional[set] = None,  # RULE 4: snapshot of seen_concepts before this clip started
    ) -> str:
        """
        Full B-roll pipeline for a single clip.

        1. Extract keywords (or use precomputed_keywords from AI brain)
        2. Fetch the best matching stock video per keyword
        3. Insert B-roll overlays at spoken-word timestamps or scene boundaries

        Returns *output_path* on success, *video_path* (original) on failure.
        """
        try:
            # ── Dynamic B-roll budget based on clip duration, speech density, and energy ──
            # Compute speech density: ratio of words to clip duration
            _words = words_with_timestamps or []
            _n_words = len(_words)
            _speech_density = _n_words / max(clip_duration, 1.0) if clip_duration > 0 else 0.0

            # Estimate energy from audio features or speech patterns
            # High energy = many short words, exclamation marks, question marks
            # Low energy = long pauses, calm explanatory text
            _text = segment_text or ""
            _exclamation_count = _text.count("!") + _text.count("?")
            _avg_word_len = len(_text.replace(" ", "")) / max(_n_words, 1) if _n_words > 0 else 5.0
            _energy_score = 0.5  # default neutral
            if _exclamation_count >= 3:
                _energy_score = 0.9  # high energy: lots of exclamation/questions
            elif _exclamation_count >= 1:
                _energy_score = 0.7  # medium-high
            if _avg_word_len < 4.0:
                _energy_score = min(1.0, _energy_score + 0.2)  # short words = fast speech
            elif _avg_word_len > 6.0:
                _energy_score = max(0.2, _energy_score - 0.2)  # long words = calm/technical

            # Energy-aware budget:
            # - Calm sections (energy < 0.4): max 1 B-roll, wide spacing
            # - Neutral sections (0.4–0.7): max 2 B-rolls, standard spacing
            # - High-energy sections (> 0.7): max 3 B-rolls, tighter spacing
            _budget = 2  # default
            if _energy_score < 0.4:
                _budget = 1  # calm: breathing room
                _min_gap_override = 12.0  # wide spacing
            elif _energy_score < 0.7:
                _budget = 2  # neutral: standard
                _min_gap_override = 8.0
            else:
                _budget = 3  # high energy: allow more
                _min_gap_override = 6.0

            # Also consider clip duration: longer clips can fit more
            if clip_duration >= 45.0 and _energy_score >= 0.7:
                _budget = min(4, _budget + 1)
            elif clip_duration >= 60.0 and _energy_score >= 0.4:
                _budget = min(4, _budget + 1)

            # Override max_overlays with dynamic budget (but never exceed caller's limit)
            max_overlays = min(max_overlays, _budget)

            logger.info(
                "[BRoll] Dynamic budget: clip=%.1fs words=%d density=%.2f "
                "energy=%.2f (exclams=%d avg_word_len=%.1f) → max_overlays=%d min_gap=%.1fs",
                clip_duration, _n_words, _speech_density,
                _energy_score, _exclamation_count, _avg_word_len,
                max_overlays, _min_gap_override,
            )

            # ── HARD PLANNING-STAGE GATE: reject any b-roll cue under 2.5s ──────
            # This is Gate 3 — enforced at the planning/selection stage before
            # keyword extraction, so short cues never reach the renderer.
            if overlay_duration_s < BROLL_MIN_OVERLAY_DURATION_S:
                logger.info(
                    "[BRoll/DurationGate] clip=%.1fs rejecting short b-roll cue: "
                    "planned=%.1fs → clamped to %.1fs (source=process_clip parameter)",
                    clip_duration, overlay_duration_s, BROLL_MIN_OVERLAY_DURATION_S,
                )
                overlay_duration_s = BROLL_MIN_OVERLAY_DURATION_S

            # Step 1 — keywords: use AI brain's choices if available, else NLP extraction
            if precomputed_keywords:
                keywords = list(precomputed_keywords)
                logger.info(f"[BRoll] Using AI keywords: {keywords}")
                # ── Insurance filter for AI brain keywords ──────────────────────
                # The AI brain (clip_intelligence BRAIN kw field) can produce generic
                # motivational keywords like "success achievement", "sunrise mountains"
                # for insurance content. Apply the same insurance filter here.
                _insurance_enriched = self._insurance_enriched_keywords(segment_text)
                if _insurance_enriched:
                    keywords = self._filter_insurance_keywords(keywords, True)
                    logger.info(f"[BRoll] Insurance-filtered AI keywords: {keywords}")
                # ────────────────────────────────────────────────────────────────
            else:
                keywords = await self.extract_keywords(segment_text)

                # Enhanced B-roll: análisis de contexto visual para keywords más precisos
                try:
                    from .enhanced_broll_service import EnhancedBrollService
                    _ebs = EnhancedBrollService()
                    _opportunities = await _ebs.analyze_broll_opportunities(
                        transcript=segment_text,
                        video_path=Path(video_path),
                        clip_duration=clip_duration,
                    )
                    if _opportunities:
                        _enhanced_kws = [
                            kw for opp in _opportunities[:2]
                            for kw in opp.suggested_keywords[:2]
                            if kw not in keywords
                        ]
                        keywords = _enhanced_kws + keywords
                        logger.info(f"[BRoll] Enhanced context keywords: {_enhanced_kws}")
                except Exception as _ebs_e:
                    logger.debug(f"[BRoll] Enhanced B-roll analysis skipped: {_ebs_e}")

                # YOLO augmentation: detect objects actually visible in the clip
                try:
                    from ...video_processing.object_detection import detect_objects_in_video
                    yolo_kws = await detect_objects_in_video(video_path, max_frames=4)
                    if yolo_kws:
                        for kw in reversed(yolo_kws[:2]):
                            if kw not in keywords:
                                keywords.insert(0, kw)
                        logger.info(f"[BRoll] YOLO augmented keywords: {keywords}")
                except Exception as _yolo_e:
                    logger.debug(f"[BRoll] YOLO augmentation skipped: {_yolo_e}")

            # Semantic B-roll: Pexels + sentence-transformers para un asset semántico extra
            try:
                from .semantic_broll_service import create_semantic_broll_service
                _sbs = create_semantic_broll_service()
                _sem_result = await _sbs.find_broll_for_segment(
                    transcript_segment=segment_text,
                    segment_duration=clip_duration or 4.5,
                )
                if _sem_result and _sem_result.get("keywords"):
                    _sem_kws = [k for k in _sem_result["keywords"] if k not in keywords]
                    if _sem_kws:
                        keywords = _sem_kws[:2] + keywords
                        logger.info(f"[BRoll] Semantic keywords added: {_sem_kws[:2]}")
            except Exception as _sbs_e:
                logger.debug(f"[BRoll] Semantic B-roll skipped: {_sbs_e}")

            if not keywords:
                return video_path

            # Step 2 — fetch one asset per keyword (up to max_overlays distinct clips)
            # Anti-repetition: track used URLs across all keywords in this clip,
            # persisted per task_id via JSON file so repeats are avoided across
            # multiple clips of the same task (even after restarts).
            broll_assets: List[Path] = []
            # FIX 4: Use passed task_id if available, fall back to video_path stem
            _task_id = task_id or (Path(video_path).stem if video_path else f"broll_{int(asyncio.get_event_loop().time())}")
            _used_urls: set = await self._load_used_urls(_task_id)
            
            # ── RULE 4: Diversity filter — prevent repeated b-roll concepts ──
            # Uses semantic similarity (Jaccard on word tokens) to detect repeats.
            # Exact keyword repeats are penalised more strongly than semantic ones.
            # Logs whether repetition was blocked within-task (same clip) or cross-clip.
            if seen_concepts is not None:
                _before_concept_filter = len(keywords)
                _filtered_keywords: List[str] = []
                _exact_removed = 0
                _semantic_removed = 0
                for kw in keywords:
                    _kw_lower = kw.lower().strip()
                    # ── Exact repeat: always blocked (strongest penalty) ──
                    if _kw_lower in seen_concepts:
                        _exact_removed += 1
                        logger.info(
                            "[BRoll] RULE 4: Blocked exact repeat '%s' (cross-clip)" if pre_clip_concepts is not None and _kw_lower in pre_clip_concepts else
                            "[BRoll] RULE 4: Blocked exact repeat '%s' (within-task)",
                            kw,
                        )
                        continue
                    # ── Semantic similarity check: Jaccard on word tokens ──
                    _kw_words = set(_kw_lower.split())
                    _is_semantic_dup = False
                    for _seen in seen_concepts:
                        _seen_words = set(_seen.split())
                        _intersection = _kw_words & _seen_words
                        _union = _kw_words | _seen_words
                        if _union:
                            _jaccard = len(_intersection) / len(_union)
                            # Exact match already caught above; semantic threshold = 0.35
                            if _jaccard >= 0.35:
                                _is_semantic_dup = True
                                _semantic_removed += 1
                                logger.info(
                                    "[BRoll] RULE 4: Blocked semantic repeat '%s' (Jaccard=%.2f with '%s')",
                                    kw, _jaccard, _seen,
                                )
                                break
                    if not _is_semantic_dup:
                        _filtered_keywords.append(kw)
                keywords = _filtered_keywords
                _total_removed = _exact_removed + _semantic_removed
                if _total_removed > 0:
                    logger.info(
                        "[BRoll] RULE 4: Filtered %d concepts (%d exact + %d semantic) — remaining: %s",
                        _total_removed, _exact_removed, _semantic_removed, keywords,
                    )
            
            for kw in keywords[:max(3, max_overlays)]:
                asset = await self.fetch_broll_asset(kw, video_path=video_path, task_id=_task_id, used_urls=_used_urls)
                if asset and asset not in broll_assets:
                    broll_assets.append(asset)
                    _used_urls.add(str(asset))
                    # Track this concept as seen for future clips
                    if seen_concepts is not None:
                        seen_concepts.add(kw.lower().strip())
            # Persist updated used_urls for this task
            await self._save_used_urls(_task_id, _used_urls)

            # Step 2b — semantic scoring: score each asset against segment_text.
            # Uses sentence-transformers embeddings when available for deep semantic
            # matching, otherwise falls back to keyword overlap between the asset's
            # filename/tags and the segment text. This ensures every asset is scored
            # for relevance — no asset passes through unscored.
            # 
            # The scoring uses the segment text directly (not visual_keywords) so it
            # always works even when the visual keyword detector is unavailable.
            # Assets with score below threshold are rejected; the rest are ranked.
            _scored_assets: List[Tuple[float, Path]] = []
            for _asset in broll_assets:
                _tags = _asset.stem.replace("_", " ")
                _score = self._score_broll_candidate(segment_text, keywords, _tags)
                _scored_assets.append((_score, _asset))
            _scored_assets.sort(key=lambda x: x[0], reverse=True)
            _threshold = 0.35
            _before = len(broll_assets)
            broll_assets = [a for s, a in _scored_assets if s >= _threshold]
            if len(broll_assets) < _before:
                for s, a in _scored_assets:
                    if s < _threshold:
                        logger.warning(
                            "[BrollGate] SEMANTIC REJECT score=%.2f threshold=%.2f asset=%s",
                            s, _threshold, a.name,
                        )
                logger.info(
                    "[BRoll] Semantic scoring filtered %d/%d assets (threshold=%.2f)",
                    _before - len(broll_assets), _before, _threshold,
                )
            if not broll_assets:
                logger.info("[BRoll] All assets filtered out by semantic scoring — entering fallback chain")
                _fallback_reason = "semantic_scoring"
                _fallback_assets_empty = True
            else:
                _fallback_assets_empty = False

            # Step 2c — quality filter: drop low-res, letterboxed, too-short assets
            if not _fallback_assets_empty:
                _before_q = len(broll_assets)
                broll_assets = self._filter_assets_by_quality(broll_assets)
                if not broll_assets:
                    logger.info("[BRoll] All assets filtered out by quality check — entering fallback chain")
                    _fallback_reason = "quality_filter"
                    _fallback_assets_empty = True
                else:
                    _fallback_assets_empty = False
            else:
                _before_q = 0

            # Step 2d — kind derivation and QA logging
            _kinds: Dict[str, int] = {}
            for _a in broll_assets:
                _k = self._derive_kind(_a)
                _kinds[_k] = _kinds.get(_k, 0) + 1
            logger.info(
                "[BRoll] Kind distribution: %s (after quality filter: %d→%d)",
                _kinds, _before_q, len(broll_assets),
            )

            # Step 2e — apply style preferences (re-rank by preferred tags + kind)
            _style = broll_style or self._resolve_broll_style(
                category="",
                topic="",
            )
            _before_st = len(broll_assets)
            broll_assets = self._apply_style_preferences(broll_assets, _style, clip_duration)
            if len(broll_assets) < _before_st:
                logger.info("[BRoll] Style '%s' filtered %d→%d assets", _style, _before_st, len(broll_assets))
            if not broll_assets:
                logger.info("[BRoll] All assets filtered by style preferences — entering fallback chain")
                _fallback_reason = "style_preferences"
                _fallback_assets_empty = True
            else:
                _fallback_assets_empty = False

            # ──────────────────────────────────────────────────────────────────────
            # FALLBACK CHAIN: when all stock assets are rejected, try progressively
            # safer visual modes instead of silently returning 0 b-roll.
            #
            # Chain order:
            #   1. GPU T2V generation (if available)
            #   2. ComfyUI LTX-Video generation (if enabled)
            #   3. Insurance-specific overlay (for insurance/finance content)
            #   4. Text callout overlay (generic fallback)
            #   5. Subtle zoom/reframe (last resort before no stock)
            #   6. No stock footage (only as absolute last resort)
            #
            # Each step logs the exact fallback selection path.
            # ──────────────────────────────────────────────────────────────────────
            if _fallback_assets_empty:
                logger.warning(
                    "[BRoll/Fallback] ⚠️ All %d stock assets rejected (%s) — "
                    "entering structured fallback chain for clip=%.1fs",
                    _before, _fallback_reason, clip_duration,
                )

            # ── Step 1: GPU T2V generation ──
            if _fallback_assets_empty:
                try:
                    from .t2v_broll_service import T2VBrollService
                    if T2VBrollService.is_available():
                        _t2v = T2VBrollService()
                        _t2v_prompt = ", ".join(keywords[:2]) if keywords else segment_text[:50]
                        _t2v_out = self.broll_dir / f"t2v_{'_'.join(keywords[:1])}.mp4"
                        _t2v_res = await _t2v.generate(
                            prompt=_t2v_prompt,
                            duration=_BROLL_DURATION,
                            output_path=str(_t2v_out),
                        )
                        if _t2v_res and _t2v_out.exists():
                            broll_assets.append(_t2v_out)
                            logger.info(
                                "[BRoll/Fallback] ✓ Step 1 (T2V): generated B-Roll for: %s",
                                _t2v_prompt[:40],
                            )
                            _fallback_assets_empty = False
                except Exception as _t2v_e:
                    logger.debug("[BRoll/Fallback] Step 1 (T2V) skipped: %s", _t2v_e)

            # ── Step 2: ComfyUI LTX-Video generation ──
            if _fallback_assets_empty and COMFYUI_ENABLED:
                try:
                    _gen_prompt = ", ".join(keywords[:2]) if keywords else segment_text[:50]
                    _task_ns = f"brollgen_{'_'.join(keywords[:1]) or 'fallback'}"
                    _gen_result = await comfyui_integration.process_with_comfyui(
                        task_id=_task_ns,
                        video_path=None,
                        operation="broll_generate",
                        prompt=f"cinematic B-roll footage of {_gen_prompt}, smooth motion, 9:16 vertical",
                        duration=_BROLL_DURATION,
                        width=608,
                        height=1088,
                    )
                    if _gen_result and Path(_gen_result).exists():
                        _gen_out = self.broll_dir / f"gen_{'_'.join(keywords[:1]) or 'fallback'}.mp4"
                        try:
                            shutil.copy2(_gen_result, _gen_out)
                        except Exception:
                            _gen_out = Path(_gen_result)
                        broll_assets.append(_gen_out)
                        logger.info(
                            "[BRoll/Fallback] ✓ Step 2 (LTX-Video): generated B-Roll for: %s",
                            _gen_prompt[:40],
                        )
                        _fallback_assets_empty = False
                except Exception as _gen_e:
                    logger.debug("[BRoll/Fallback] Step 2 (LTX-Video) skipped: %s", _gen_e)

            # ── Step 3: Insurance-specific overlay (for insurance/finance content) ──
            if _fallback_assets_empty:
                _is_insurance_content = any(
                    kw in segment_text.lower() for kw in [
                        "seguro", "insurance", "póliza", "poliza", "cobertura",
                        "indemnización", "indemnizacion", "siniestro", "prima",
                        "aseguradora", "financiero", "inversión", "inversion",
                        "ahorro", "jubilación", "jubilacion", "pensión", "pension",
                        "hipoteca", "préstamo", "prestamo", "invertir",
                    ]
                )
                if _is_insurance_content:
                    logger.info(
                        "[BRoll/Fallback] Step 3: insurance content detected — "
                        "trying domain-specific overlay"
                    )
                    try:
                        from .contextual_overlay_engine import ContextualOverlayEngine
                        _overlay_engine = ContextualOverlayEngine()
                        # Pick insurance-relevant overlay text from keywords or transcript
                        _insurance_text = None
                        if keywords:
                            for kw in keywords:
                                _kw_lower = kw.lower()
                                if any(ins_kw in _kw_lower for ins_kw in [
                                    "insurance", "seguro", "financial", "finance",
                                    "money", "protection", "family", "home",
                                    "car", "health", "medical", "policy",
                                    "claim", "investment", "retirement", "saving",
                                ]):
                                    _insurance_text = kw
                                    break
                        if not _insurance_text:
                            # Extract first insurance-related phrase from transcript
                            _ins_phrases = [
                                "seguro de vida", "seguro de coche", "seguro del hogar",
                                "protección familiar", "ahorro", "inversión",
                                "plan de pensiones", "hipoteca", "préstamo",
                            ]
                            for phrase in _ins_phrases:
                                if phrase in segment_text.lower():
                                    _insurance_text = phrase
                                    break
                        if not _insurance_text:
                            _insurance_text = keywords[0] if keywords else "protección familiar"
                        _overlay_types = ["callout", "graphical_label", "animated_keyword"]
                        _overlay_type = _overlay_types[hash(str(_insurance_text)) % len(_overlay_types)]
                        _overlay_result = await _overlay_engine.apply_overlay(
                            video_path=video_path,
                            output_path=output_path,
                            text=_insurance_text,
                            overlay_type=_overlay_type,
                            timestamp=clip_duration * 0.3 if clip_duration > 0 else 3.0,
                            duration=min(4.0, clip_duration * 0.3) if clip_duration > 0 else 3.0,
                        )
                        if _overlay_result:
                            logger.info(
                                "[BRoll/Fallback] ✓ Step 3 (insurance overlay): "
                                "type=%s text='%s'",
                                _overlay_type, _insurance_text,
                            )
                            return output_path
                    except Exception as _ins_e:
                        logger.debug("[BRoll/Fallback] Step 3 (insurance overlay) failed: %s", _ins_e)

            # ── Step 4: Text callout overlay (generic fallback) ──
            if _fallback_assets_empty:
                logger.info(
                    "[BRoll/Fallback] Step 4: trying text callout overlay — "
                    "keywords=%s",
                    keywords[:3] if keywords else "(none)",
                )
                try:
                    from .contextual_overlay_engine import ContextualOverlayEngine
                    _overlay_engine = ContextualOverlayEngine()
                    _callout_text = keywords[0] if keywords else segment_text[:30]
                    _overlay_result = await _overlay_engine.apply_overlay(
                        video_path=video_path,
                        output_path=output_path,
                        text=_callout_text,
                        overlay_type="callout",
                        timestamp=clip_duration * 0.3 if clip_duration > 0 else 3.0,
                        duration=min(4.0, clip_duration * 0.3) if clip_duration > 0 else 3.0,
                    )
                    if _overlay_result:
                        logger.info(
                            "[BRoll/Fallback] ✓ Step 4 (text callout): text='%s'",
                            _callout_text,
                        )
                        return output_path
                except Exception as _callout_e:
                    logger.debug("[BRoll/Fallback] Step 4 (text callout) failed: %s", _callout_e)

            # ── Step 5: Subtle zoom/reframe (last resort before no stock) ──
            if _fallback_assets_empty:
                logger.info(
                    "[BRoll/Fallback] Step 5: trying subtle zoom/reframe — "
                    "no stock assets available"
                )
                try:
                    from ...video_processing.cut_zoom_service import apply_cut_zooms
                    _zoom_out = output_path.replace(".mp4", "_zoom.mp4")
                    _zoom_ok = await apply_cut_zooms(
                        video_path=video_path,
                        output_path=_zoom_out,
                        cut_points=[clip_duration * 0.3, clip_duration * 0.6] if clip_duration > 0 else [],
                        zoom_factor=1.04,
                        zoom_duration=0.4,
                        intensity=0.3,
                    )
                    if _zoom_ok and Path(_zoom_out).exists():
                        # Copy zoom result to output_path
                        shutil.copy2(_zoom_out, output_path)
                        Path(_zoom_out).unlink(missing_ok=True)
                        logger.info(
                            "[BRoll/Fallback] ✓ Step 5 (zoom/reframe): "
                            "applied subtle zoom at 30%% and 60%% of clip"
                        )
                        return output_path
                except Exception as _zoom_e:
                    logger.debug("[BRoll/Fallback] Step 5 (zoom/reframe) failed: %s", _zoom_e)

            # ── Step 6: No stock footage (absolute last resort) ──
            if _fallback_assets_empty:
                logger.warning(
                    "[BRoll/Fallback] ⚠️ Step 6: ALL fallback steps exhausted — "
                    "returning clip with 0 b-roll (no stock footage available). "
                    "Fallback path: semantic_scoring/quality/style → T2V → LTX → "
                    "insurance_overlay → text_callout → zoom_reframe → no_stock"
                )
                return video_path

            # Step 3 — find timestamps: use narrative-aware boundary detection
            n_wanted = min(len(broll_assets), max_overlays)
            insert_timestamps: List[float] = []

            # Build narrative entry/exit points from word timestamps
            # Entry points: sentence starts and post-pause positions (≥ 0.4s gap)
            # Exit points: sentence ends and pre-pause positions
            _entry_points: List[float] = []
            _exit_points: List[float] = []
            if words_with_timestamps:
                _prev_end = 0.0
                for i, w in enumerate(words_with_timestamps):
                    _ws = float(w.get("start", 0))
                    _we = float(w.get("end", _ws + 0.3))
                    _word = (w.get("word") or "").strip()
                    _gap = _ws - _prev_end
                    # Detect sentence start: word starts with capital letter
                    # or follows a period/question mark/exclamation
                    _is_sentence_start = (
                        _word and _word[0].isupper()
                        and i > 0
                        and _gap > 0.15  # small gap after period
                    )
                    # Detect post-pause entry: gap ≥ 0.4s (natural breathing point)
                    _is_post_pause = _gap >= 0.4
                    if _is_sentence_start or _is_post_pause:
                        _entry_points.append(_ws)
                    # Detect sentence end: word ends with period/question/exclamation
                    if _word and _word[-1] in ".!?":
                        _exit_points.append(_we)
                    _prev_end = _we

            # Use micro-moment detection to find the best timestamps
            _micro_cues = self._detect_micro_moment_cues(
                words_with_timestamps or [], clip_duration, max_cues=n_wanted,
            )
            if _micro_cues:
                for _cue in _micro_cues:
                    ts = _cue["start_time"]
                    # Don't place B-roll in the first 0.8s (protect hook)
                    # Skip filler phrases, intros, transitions
                    _reason = _cue.get("reason", "").lower()
                    _is_strong = any(kw in _reason for kw in [
                        "number", "surprise", "named entity", "claim",
                        "mentions", "speaker says",
                    ])
                    if ts >= 0.8 and _is_strong and all(abs(ts - t) > 2.5 for t in insert_timestamps):
                        # Snap to nearest narrative entry point (sentence start or post-pause)
                        _snapped = self._snap_to_narrative_boundary(
                            ts, _entry_points, _exit_points, clip_duration,
                        )
                        if _snapped is not None:
                            insert_timestamps.append(_snapped)
                            logger.info(
                                "[BRoll] Narrative-aligned cue at t=%.1fs (original=%.1fs): %s",
                                _snapped, ts, _cue.get("reason", ""),
                            )
                        else:
                            insert_timestamps.append(ts)
                            logger.info(
                                "[BRoll] Micro-moment cue at t=%.1fs (no narrative snap): %s",
                                ts, _cue.get("reason", ""),
                            )
            
            # Fallback: keyword→spoken timestamp matching
            if not insert_timestamps and words_with_timestamps:
                for kw in keywords[:n_wanted]:
                    kw_lower = kw.lower().strip()
                    for w in words_with_timestamps:
                        w_text = (w.get("word") or w.get("text") or "").lower().strip(".,!?-'\"")
                        if kw_lower == w_text or kw_lower in w_text or w_text in kw_lower:
                            ts = float(w.get("start", 0))
                            if ts >= 0.8 and all(abs(ts - t) > 2.5 for t in insert_timestamps):
                                # Snap to nearest narrative entry point
                                _snapped = self._snap_to_narrative_boundary(
                                    ts, _entry_points, _exit_points, clip_duration,
                                )
                                insert_timestamps.append(_snapped if _snapped is not None else ts)
                            break
                logger.info("[BRoll] Keyword→spoken timestamps: %s",
                            [f"{t:.1f}s" for t in insert_timestamps])

            # Fill remaining slots with scene-detected timestamps
            if len(insert_timestamps) < n_wanted:
                scene_ts = get_insert_timestamps(
                    video_path=video_path,
                    max_n=n_wanted - len(insert_timestamps),
                    clip_duration=clip_duration or None,
                )
                for ts in scene_ts:
                    if all(abs(ts - t) > 2.5 for t in insert_timestamps):
                        # Snap to nearest narrative entry point
                        _snapped = self._snap_to_narrative_boundary(
                            ts, _entry_points, _exit_points, clip_duration,
                        )
                        insert_timestamps.append(_snapped if _snapped is not None else ts)

            insert_timestamps.sort()

            # Protect hook (0–2s) and CTA (last 2s): never overlay B-roll there.
            _hook_guard = 2.0
            _cta_guard  = max(0.0, (clip_duration or 0) - 2.0)
            if _cta_guard > _hook_guard:
                insert_timestamps = [
                    t for t in insert_timestamps
                    if _hook_guard <= t <= _cta_guard
                ]
            if not insert_timestamps and broll_assets:
                # Fallback: midpoint is always safe
                _mid = (clip_duration or 10.0) / 2.0
                insert_timestamps = [_mid]

            # Step 3.5 — BrollEffectsEngine: apply cinematic effect (ken burns / pan) per asset
            _enhanced_assets: List[Path] = []
            try:
                from .broll_effects_engine import get_smart_broll_effect, build_broll_effect_filter
                import subprocess as _sp
                for _ba in broll_assets:
                    try:
                        _effect = get_smart_broll_effect(
                            is_image=_ba.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"),
                        )
                        _efx_filter = build_broll_effect_filter(
                            effect_type=_effect,
                            width=1080, height=1920,
                            duration=overlay_duration_s,
                        )
                        _efx_out = _ba.with_name(f"efx_{_ba.name}")
                        _efx_cmd = [
                            "ffmpeg", "-y", "-i", str(_ba),
                            "-vf", _efx_filter,
                            "-t", str(overlay_duration_s),
                            *gpu_utils.ffmpeg_codec_flags("high"), "-an",
                            str(_efx_out),
                        ]
                        _efx_res = _sp.run(_efx_cmd, capture_output=True, timeout=30)
                        if _efx_res.returncode == 0 and _efx_out.exists():
                            _enhanced_assets.append(_efx_out)
                            logger.info(f"[BRoll] ✓ Effect {_effect.value} applied to {_ba.name}")
                        else:
                            _enhanced_assets.append(_ba)
                    except Exception:
                        _enhanced_assets.append(_ba)
                broll_assets = _enhanced_assets
            except Exception as _bee_e:
                logger.debug(f"[BRoll] Effects engine skipped: {_bee_e}")

            # Step 4 — sanitize timeline: hook zone, no overlaps, rhythm rules
            # Compute overlay duration safely:
            #   1. end_time = ts + overlay_duration_s (the desired overlay length)
            #   2. duration = end_time - ts
            #   3. Clamp to BROLL_MIN_OVERLAY_DURATION_S
            #   4. If clip_duration is known and duration < minimum, extend only if
            #      the extended overlay still fits inside the clip; otherwise skip.
            _raw_pairs: List[Tuple[float, str, float]] = []
            for ts, asset in zip(insert_timestamps, broll_assets):
                end_time = ts + overlay_duration_s
                dur = end_time - ts
                if dur < BROLL_MIN_OVERLAY_DURATION_S:
                    if clip_duration and clip_duration > 0:
                        # Try to extend to minimum, but only if it fits inside the clip
                        extended_end = ts + BROLL_MIN_OVERLAY_DURATION_S
                        if extended_end <= clip_duration:
                            dur = BROLL_MIN_OVERLAY_DURATION_S
                            logger.debug(
                                "[BRoll] Extended overlay duration to %.1fs (min) at t=%.1fs — %s",
                                dur, ts, asset,
                            )
                        else:
                            logger.warning(
                                "[BRoll] Skipping broll overlay at t=%.1fs: "
                                "cannot fit minimum duration %.1fs inside clip (clip_duration=%.1fs) — %s",
                                ts, BROLL_MIN_OVERLAY_DURATION_S, clip_duration, asset,
                            )
                            continue
                    else:
                        # No clip_duration known — clamp to minimum
                        dur = BROLL_MIN_OVERLAY_DURATION_S
                _raw_pairs.append((ts, str(asset), dur))
            _raw_pairs.sort(key=lambda x: x[0])
            broll_pairs = self._sanitize_broll_timeline(_raw_pairs, clip_duration=clip_duration)

            if len(broll_pairs) == 1:
                ts, asset_path, dur = broll_pairs[0]
                ok = await self.insert_broll(
                    video_path=video_path,
                    fade=broll_fade_s,
                    output_path=output_path,
                    broll_path=asset_path,
                    timestamp=ts,
                    overlay_duration=dur,
                )
            else:
                # ── FIX 3B: Connect transitions_service for smooth transitions ──
                # between consecutive b-roll overlay segments. We build a standalone
                # b-roll montage (assets concatenated with crossfade transitions),
                # then overlay that montage onto the main video at the first
                # timestamp. This gives smooth visual flow between different b-roll
                # assets while keeping the overlay logic simple.
                _broll_montage_path = Path(output_path).with_suffix(".broll_montage.mp4")
                try:
                    from ...services.transitions_service import apply_transition_batch
                    _broll_clips = [Path(asset) for _, asset, _ in broll_pairs]
                    _montage_result = await apply_transition_batch(
                        clips=_broll_clips,
                        transition_type="crossfade",
                        duration=0.2,
                        output_path=_broll_montage_path,
                    )
                    if _montage_result and _montage_result.exists() and _montage_result.stat().st_size > 1000:
                        logger.info(
                            "[BRoll] ✓ B-roll montage with transitions created: %s "
                            "(%d assets, crossfade 0.2s)",
                            _montage_result.name, len(_broll_clips),
                        )
                        # Overlay the montage at the first timestamp
                        _first_ts = broll_pairs[0][0]
                        _total_montage_dur = sum(d for _, _, d in broll_pairs)
                        ok = await self.insert_broll(
                            video_path=video_path,
                            fade=broll_fade_s,
                            output_path=output_path,
                            broll_path=str(_montage_result),
                            timestamp=_first_ts,
                            overlay_duration=_total_montage_dur,
                        )
                    else:
                        logger.warning(
                            "[BRoll] B-roll montage with transitions failed — "
                            "falling back to compose_overlay_multi"
                        )
                        raise RuntimeError("montage failed")
                except Exception as _montage_err:
                    logger.debug(
                        "[BRoll] Transitions montage skipped (%s) — "
                        "using compose_overlay_multi fallback",
                        _montage_err,
                    )
                    from .broll_compositor import compose_overlay_multi
                    ok = await compose_overlay_multi(
                        fade=broll_fade_s,
                        main_path=video_path,
                        broll_pairs=broll_pairs,
                        output_path=output_path,
                    )
                finally:
                    # Cleanup temp montage file
                    try:
                        _broll_montage_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            if ok:
                logger.info(f"[BRoll] ✓ {len(broll_pairs)} overlays applied: {[f't={t:.1f}s' for t,_,_ in broll_pairs]}")
            return output_path if ok else video_path

        except Exception as e:
            logger.error(f"[BRoll] process_clip failed: {e}", exc_info=True)
            return video_path
