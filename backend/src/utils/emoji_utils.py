"""
Emoji overlay utilities for ViraClip.

Uses Twemoji (Twitter's open-source emoji PNG set) via CDN for clean,
color emoji rendering without requiring NotoColorEmoji font.
"""
import logging
import os
import re
from pathlib import Path
from typing import Optional, Tuple, List, Dict
import urllib.request

import numpy as np

logger = logging.getLogger(__name__)

# Local cache dir for downloaded emoji PNGs
_EMOJI_CACHE_DIR = Path("/tmp/viraclip_emoji_cache")

# Twemoji CDN — 72x72 PNG, MIT licensed
_TWEMOJI_BASE = "https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72"

# Map hook_type + theme → up to 2 emojis  (common + universally recognizable)
HOOK_EMOJI_MAP = {
    "question":    ["🤔", "❓"],
    "statement":   ["💡", "‼️"],
    "statistic":   ["📊", "🔢"],
    "story":       ["🎯", "💬"],
    "contrast":    ["⚡", "🔄"],
    "none":        ["🔥"],
}

NICHE_EMOJI_MAP = {
    "finance":      ["💰", "📈"],
    "fitness":      ["💪", "🏋️"],
    "tech":         ["🚀", "💻"],
    "gaming":       ["🎮", "⚔️"],
    "motivational": ["🔥", "💯"],
    "education":    ["📚", "🧠"],
    "comedy":       ["😂", "🤣"],
    "business":     ["📈", "💼"],
    "general":      ["🔥"],
}


def _emoji_to_hex(emoji_char: str) -> Optional[str]:
    """Convert an emoji character to its Twemoji hex filename (lowercased, no ZWJ for basic emoji)."""
    codepoints = [f"{ord(c):x}" for c in emoji_char if ord(c) != 0xFE0F]  # strip variation selector
    # Twemoji uses hyphen-joined codepoints for ZWJ sequences
    return "-".join(codepoints) if codepoints else None


def download_emoji_png(emoji_char: str) -> Optional[Path]:
    """
    Download the Twemoji PNG for an emoji character. Returns local path or None.
    Results are cached in _EMOJI_CACHE_DIR.
    """
    try:
        _EMOJI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        hex_code = _emoji_to_hex(emoji_char)
        if not hex_code:
            return None
        cache_path = _EMOJI_CACHE_DIR / f"{hex_code}.png"
        if cache_path.exists() and cache_path.stat().st_size > 100:
            return cache_path
        url = f"{_TWEMOJI_BASE}/{hex_code}.png"
        logger.debug(f"Downloading emoji {emoji_char} from {url}")
        urllib.request.urlretrieve(url, str(cache_path))
        if cache_path.exists() and cache_path.stat().st_size > 100:
            return cache_path
    except Exception as e:
        logger.debug(f"Emoji download failed for {emoji_char}: {e}")
    return None


def emoji_to_numpy_rgba(emoji_char: str, size: int = 80) -> Optional[np.ndarray]:
    """
    Return a numpy RGBA array (H, W, 4) for the given emoji at `size`×`size` pixels.
    Returns None if the emoji cannot be downloaded/rendered.
    """
    try:
        from PIL import Image
        png_path = download_emoji_png(emoji_char)
        if png_path is None:
            return None
        img = Image.open(str(png_path)).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        return np.array(img)
    except Exception as e:
        logger.debug(f"emoji_to_numpy_rgba failed for {emoji_char}: {e}")
        return None


def make_emoji_clip(emoji_char: str, size: int, duration: float, start: float = 0.0):
    """
    Create a MoviePy ImageClip from an emoji character.

    Returns a positioned clip (top-right corner) or None on failure.
    """
    try:
        from moviepy import ImageClip
        from moviepy.video.fx import FadeIn, FadeOut

        rgba = emoji_to_numpy_rgba(emoji_char, size)
        if rgba is None:
            return None

        clip = (
            ImageClip(rgba, duration=duration)
            .with_start(start)
            .with_effects([FadeIn(0.2), FadeOut(0.2)])
        )
        return clip
    except Exception as e:
        logger.debug(f"make_emoji_clip failed for {emoji_char}: {e}")
        return None


def get_clip_emojis(hook_type: str = "none", niche: str = "general") -> List[str]:
    """
    Return up to 2 relevant emojis for a clip based on its hook type and content niche.
    """
    emojis = []
    # Primary: hook_type-based emoji
    hook_emojis = HOOK_EMOJI_MAP.get(hook_type or "none", HOOK_EMOJI_MAP["none"])
    if hook_emojis:
        emojis.append(hook_emojis[0])

    # Secondary: niche-based emoji (only if different from hook emoji)
    niche_emojis = NICHE_EMOJI_MAP.get(niche or "general", NICHE_EMOJI_MAP["general"])
    if niche_emojis and niche_emojis[0] not in emojis:
        emojis.append(niche_emojis[0])

    return emojis[:2]


# ---------------------------------------------------------------------------
# Keyword → emoji map for caption-level overlays.
# Keys are lowercase Spanish/English keywords that commonly appear in viral clips.
# ---------------------------------------------------------------------------
KEYWORD_EMOJI_MAP: dict[str, str] = {
    # Finance / money
    "dinero": "💰", "money": "💰", "rico": "💰", "millón": "💰", "millones": "🤯",
    "million": "🤯", "billion": "🤯", "invertir": "📈", "investing": "📈",
    "ganancia": "📈", "beneficio": "📈", "ahorra": "🐷", "ahorro": "🐷",
    "gratis": "🎁", "free": "🎁", "precio": "💲", "price": "💲",
    # High-energy / excitement
    "increíble": "🔥", "increible": "🔥", "amazing": "🔥", "viral": "🔥",
    "secreto": "🤫", "secret": "🤫",
    "importante": "‼️", "important": "‼️",
    "nunca": "🚫", "never": "🚫",
    "siempre": "✅", "always": "✅",
    "fácil": "✅", "facil": "✅", "easy": "✅",
    "difícil": "😤", "dificil": "😤", "hard": "😤",
    "rápido": "⚡", "rapido": "⚡", "fast": "⚡", "quick": "⚡",
    "éxito": "🏆", "exito": "🏆", "success": "🏆", "win": "🏆",
    "error": "❌", "mistake": "❌", "wrong": "❌",
    "mejor": "⭐", "best": "⭐", "top": "⭐",
    "peor": "👎", "worst": "👎",
    "nuevo": "✨", "new": "✨",
    "poderoso": "💪", "powerful": "💪", "strong": "💪", "fuerza": "💪",
    "peligroso": "⚠️", "dangerous": "⚠️", "cuidado": "⚠️",
    # Fitness / health
    "ejercicio": "💪", "workout": "💪", "entrenar": "💪",
    "salud": "❤️", "health": "❤️", "healthy": "❤️",
    # Tech / AI
    "inteligencia": "🤖", "artificial": "🤖", "ai": "🤖", "robot": "🤖",
    "tecnología": "💻", "tecnologia": "💻", "technology": "💻",
    # Social proof / scale
    "millones": "🤯", "miles": "😮", "thousands": "😮", "masivo": "🤯",
    # Insurance / protection
    "seguro": "🛡️", "protección": "🛡️", "proteccion": "🛡️", "cobertura": "🛡️",
    "familia": "👨‍👩‍👧", "fallecimiento": "🕊️", "herencia": "🏠",
    # Generic viral
    "atención": "👀", "atencion": "👀", "mira": "👀", "watch": "👀",
    "pregunta": "❓", "question": "❓",
    "respuesta": "💡", "answer": "💡", "solución": "💡", "solucion": "💡",
}


def get_keyword_emoji_for_word_group(words: List[Dict]) -> Optional[str]:
    """
    Check a word group for any keyword that maps to an emoji.
    Returns the first matching emoji, or None.
    """
    for word in words:
        clean = word.get("text", "").lower().strip(".,!?¡¿;:\"'").strip()
        if clean in KEYWORD_EMOJI_MAP:
            return KEYWORD_EMOJI_MAP[clean]
    return None


def create_keyword_emoji_overlays(
    word_groups: List[List[Dict]],
    video_width: int,
    video_height: int,
    caption_position_y: float = 0.75,
    emoji_size: Optional[int] = None,
) -> List:
    """
    Scan caption word groups for viral keywords and create small emoji ImageClips
    that pop in next to the caption for each matched group.

    Returns a list of MoviePy ImageClip objects (may be empty if no keywords found or
    if Twemoji CDN is unreachable).

    Parameters
    ----------
    word_groups : list of word-dict lists (from adaptive_word_groups)
    video_width, video_height : clip dimensions
    caption_position_y : fractional y position of the caption baseline (0-1)
    emoji_size : pixel size of emoji square; defaults to ~8% of video width (min 48px)
    """
    from moviepy import ImageClip
    from moviepy.video.fx import FadeIn, FadeOut

    if emoji_size is None:
        emoji_size = max(48, video_width // 12)

    overlay_clips = []
    seen_emojis: set = set()  # deduplicate: one emoji type per clip max

    for group in word_groups:
        if not group:
            continue
        emoji_char = get_keyword_emoji_for_word_group(group)
        if emoji_char is None or emoji_char in seen_emojis:
            continue

        start_t = group[0]["start"]
        end_t = group[-1]["end"]
        dur = max(0.3, end_t - start_t)

        rgba = emoji_to_numpy_rgba(emoji_char, emoji_size)
        if rgba is None:
            continue

        try:
            clip = (
                ImageClip(rgba, duration=dur)
                .with_start(start_t)
                .with_effects([FadeIn(min(0.15, dur * 0.3)), FadeOut(min(0.15, dur * 0.3))])
            )
            # Position: right edge of frame, vertically aligned with caption
            right_margin = max(8, video_width // 30)
            x_pos = video_width - emoji_size - right_margin
            y_pos = int(caption_position_y * video_height) - emoji_size // 2
            y_pos = max(0, min(video_height - emoji_size, y_pos))
            clip = clip.with_position((x_pos, y_pos))
            overlay_clips.append(clip)
            seen_emojis.add(emoji_char)
            logger.debug(f"📌 Keyword emoji '{emoji_char}' at t={start_t:.2f}s")
        except Exception as e:
            logger.debug(f"Keyword emoji clip failed for '{emoji_char}': {e}")

    return overlay_clips


def strip_emojis_from_text(text: str) -> str:
    """Remove emoji characters from a string (for use in TextClip which can't render them)."""
    # Match all Unicode emoji ranges
    emoji_pattern = re.compile(
        "[\U00010000-\U0010FFFF"  # Emoji in supplementary planes
        "\U0001F300-\U0001F9FF"   # Emoticons & misc symbols
        "\u2600-\u27BF"           # Misc symbols
        "\uFE00-\uFE0F"           # Variation selectors
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()
