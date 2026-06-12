"""
Caption Service — FFmpeg ASS Karaoke Captions
==============================================

Generates Advanced SubStation Alpha (.ass) subtitle files from Whisper
word-level timestamps and burns them into video via FFmpeg's `subtitles` filter.

Styles supported:
  - karaoke   : word-by-word colour flip using \\k centisecond tags (libass)
  - highlight  : opaque coloured box behind each active word (BorderStyle=3)
  - tiktok     : large bold centred caps, drop shadow, per-word pop animation
  - minimal    : small white text, thin black outline
  - neon       : glowing cyan text on dark transparent background

Inspired by:
  - libass native \\k karaoke tags
  - Aegisub karaoke_k.ass examples
  - pyass API for dialogue/style construction
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import tempfile


def _get_ffmpeg_exe() -> str:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .vpi_visual_effects_service import choose_vpi_caption_polish_profile, get_vpi_visual_design_tokens

logger = logging.getLogger(__name__)


def _normalize_caption_words_to_clip_timebase(
    words: List[Dict[str, Any]],
    clip_duration: float,
) -> tuple[List[Dict[str, Any]], bool, str, str]:
    normalized: List[Dict[str, Any]] = []
    starts: List[float] = []
    ends: List[float] = []
    for raw in words or []:
        if not isinstance(raw, dict):
            continue
        try:
            start = float(raw.get("start", 0.0) or 0.0)
            end = float(raw.get("end", start) or start)
        except Exception:
            continue
        normalized.append(dict(raw))
        starts.append(start)
        ends.append(end)
    if not normalized:
        return [], False, "empty", ""
    min_start = min(starts) if starts else 0.0
    max_end = max(ends) if ends else 0.0
    clip_duration = float(clip_duration or 0.0)
    if clip_duration > 0.0 and max_end > clip_duration + 1.0 and min_start >= 1.0:
        offset = min_start
        corrected: List[Dict[str, Any]] = []
        for raw in normalized:
            shifted = dict(raw)
            try:
                shifted["start"] = max(0.0, float(shifted.get("start", 0.0) or 0.0) - offset)
                shifted["end"] = max(0.0, float(shifted.get("end", shifted["start"]) or shifted["start"]) - offset)
            except Exception:
                continue
            corrected.append(shifted)
        return corrected, True, "absolute_to_clip_offset", f"offset={offset:.3f}"
    return normalized, False, "clip_relative", ""


def _normalize_caption_word_items(
    words: List[Any],
    clip_duration: float = 0.0,
) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    previous_end = 0.0
    clip_duration = max(0.0, float(clip_duration or 0.0))

    for index, raw in enumerate(words or []):
        item: Dict[str, Any] = {}
        if isinstance(raw, dict):
            item = dict(raw)
        elif hasattr(raw, "start") or hasattr(raw, "end") or hasattr(raw, "text") or hasattr(raw, "word"):
            item = {
                "start": getattr(raw, "start", None),
                "end": getattr(raw, "end", None),
                "text": getattr(raw, "text", None),
                "word": getattr(raw, "word", None),
                "score": getattr(raw, "score", getattr(raw, "probability", None)),
            }
        elif isinstance(raw, (list, tuple)):
            item = {
                "text": raw[0] if len(raw) > 0 else "",
                "start": raw[1] if len(raw) > 1 else None,
                "end": raw[2] if len(raw) > 2 else None,
                "score": raw[3] if len(raw) > 3 else None,
            }
        elif isinstance(raw, str):
            item = {"text": raw, "start": None, "end": None}
        else:
            continue

        text = str(item.get("text") or item.get("word") or "").strip()
        if not text:
            continue

        raw_start = item.get("start", None)
        raw_end = item.get("end", None)
        try:
            start = float(raw_start) if raw_start is not None else previous_end
        except Exception:
            start = previous_end
        try:
            end = float(raw_end) if raw_end is not None else start + 0.45
        except Exception:
            end = start + 0.45

        if end <= start:
            end = start + 0.45

        start = max(0.0, start)
        end = max(start + 0.01, end)

        previous_end = max(previous_end, end)
        normalized.append(
            {
                "text": text,
                "word": text,
                "start": round(start, 3),
                "end": round(end, 3),
                "score": float(item.get("score", item.get("probability", 0.5)) or 0.5),
                "probability": float(item.get("probability", item.get("score", 0.5)) or 0.5),
                "is_emphasis": bool(item.get("is_emphasis", False)),
                "_normalized_index": index,
            }
        )

    return normalized


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class WordTimestamp:
    text: str
    start: float   # seconds
    end: float     # seconds
    score: float = 0.5      # WhisperX alignment confidence 0-1 (default 0.5 = neutral)
    emphasis: bool = False  # True if this word should be visually highlighted

    @property
    def duration_cs(self) -> int:
        """Duration in centiseconds (ASS \\k unit)."""
        return max(1, int((self.end - self.start) * 100))


@dataclass
class CaptionLine:
    words: List[WordTimestamp]
    line_start: float    # seconds (= first word start)
    line_end: float      # seconds (= last word end + small gap)

    @property
    def full_text(self) -> str:
        return " ".join(w.text for w in self.words)


# ── ASS colour helpers ────────────────────────────────────────────────────────

def _ass_colour(r: int, g: int, b: int, a: int = 0) -> str:
    """ASS &HAABBGGRR colour (note: little-endian channel order)."""
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


# Pre-built palettes
_WHITE   = _ass_colour(255, 255, 255)
_BLACK   = _ass_colour(0,   0,   0)
_YELLOW  = _ass_colour(255, 255, 0)
_CYAN    = _ass_colour(0,   255, 255)
_RED     = _ass_colour(255, 50,  50)
_VPI_ORANGE = _ass_colour(255, 122, 24)
_TRANSP  = "&H00000000"
_SEMI_BG = "&HAA000000"   # semi-transparent black background

_VPI_CAPTION_KEYWORDS = {
    "seguro",
    "seguros",
    "salud",
    "vida",
    "decesos",
    "familia",
    "proteccion",
    "proteger",
    "riesgo",
    "accidente",
    "hospital",
    "medico",
    "ahorro",
    "tranquilidad",
    "cobertura",
    "poliza",
    "autonomo",
    "extranjero",
    "residencia",
}

_CAPTION_KEYWORDS: Dict[str, List[str]] = {
    "decesos": ["alivio", "familia", "momento dificil", "momento difícil", "acompañamiento", "menos carga", "cuidado", "responsabilidad"],
    "salud": ["salud", "no siempre avisa", "especialistas", "pruebas", "tranquilidad", "organizacion", "organización", "respaldo"],
    "autonomos": ["autonomo", "autónomo", "autonomos", "autónomos", "motor", "estabilidad", "ingresos", "continuidad", "estrategia", "bolsillo", "imprevisto"],
    "vida": ["proteccion", "protección", "familia", "futuro", "tranquilidad", "responsabilidad", "ingresos", "ausencia"],
}

_CAPTION_PROTECTED_PHRASES = [
    "seguro de vida",
    "seguro de salud",
    "cuadro medico",
    "cuadro médico",
    "sin copago",
    "extranjeria",
    "extranjería",
    "permiso de residencia",
    "asistencia en viaje",
    "seguro de decesos",
]


def _caption_polish_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_accents(text))


def _caption_phrase_tokens(phrases: Optional[List[str]] = None) -> List[tuple[str, ...]]:
    tokens: List[tuple[str, ...]] = []
    for phrase in phrases or _CAPTION_PROTECTED_PHRASES:
        parts = tuple(_caption_polish_token(part) for part in str(phrase).split() if _caption_polish_token(part))
        if len(parts) >= 2:
            tokens.append(parts)
    return tokens


def _caption_word_tokens(words: List[WordTimestamp]) -> List[str]:
    return [_caption_polish_token(w.text) for w in words]


def _caption_tail_forms_protected_phrase(
    current_tokens: List[str],
    next_token: str,
    protected_phrases: List[tuple[str, ...]],
) -> bool:
    if not current_tokens or not next_token:
        return False
    for phrase in protected_phrases:
        if len(phrase) < 2:
            continue
        if len(current_tokens) < len(phrase) - 1:
            continue
        if tuple(current_tokens[-(len(phrase) - 1):] + [next_token]) == phrase:
            return True
    return False


def _caption_split_index(
    words: List[WordTimestamp],
    max_words_per_line: int,
    max_chars_per_line: int = 0,
    protected_phrases: Optional[List[tuple[str, ...]]] = None,
) -> int:
    if len(words) <= 3:
        return max(1, len(words) // 2 or 1)
    protected_phrases = protected_phrases or _caption_phrase_tokens()
    tokens = _caption_word_tokens(words)
    char_counts = [len(str(w.text or "").strip()) for w in words]
    candidates = list(range(1, len(words)))
    best_idx = max(1, min(len(words) - 1, (len(words) + 1) // 2))
    best_score: float = -1e9
    for idx in candidates:
        left = tokens[:idx]
        right = tokens[idx:]
        if not left or not right:
            continue
        left_chars = sum(char_counts[:idx]) + max(0, idx - 1)
        right_chars = sum(char_counts[idx:]) + max(0, len(words) - idx - 1)
        score = -abs(len(left) - len(right)) * 2.0
        if len(left) == 1:
            score -= 4.0
        if len(right) == 1:
            score -= 4.0
        if len(left) > max_words_per_line:
            score -= (len(left) - max_words_per_line) * 3.0
        if len(right) > max_words_per_line:
            score -= (len(right) - max_words_per_line) * 3.0
        if max_chars_per_line > 0:
            if left_chars > max_chars_per_line:
                score -= (left_chars - max_chars_per_line) * 0.9
            if right_chars > max_chars_per_line:
                score -= (right_chars - max_chars_per_line) * 0.9
        if _caption_tail_forms_protected_phrase(left, right[0], protected_phrases):
            score -= 8.0
        if len(left) >= 2 and len(right) >= 2:
            score += 1.5
        if score > best_score:
            best_idx = idx
            best_score = score
    return best_idx

_ICON_CONCEPTS: Dict[str, List[str]] = {
    "familia": ["family", "familia", "heart", "shield"],
    "salud": ["health", "salud", "cross", "heart"],
    "autonomo": ["briefcase", "autonomo", "autónomo", "user", "work"],
    "riesgo": ["warning", "alert", "riesgo", "alerta"],
    "tranquilidad": ["calm", "tranquilidad", "shield"],
    "decesos": ["heart", "family", "support", "familia", "apoyo"],
}

_ICON_DIRS = (
    "/app/assets/icons",
    "/app/assets/brand/icons",
    "assets/icons",
    "backend/assets/icons",
    "frontend/public/icons",
)


# ── Platform-aware caption safe zones ────────────────────────────────────────
# These MarginV values keep captions above platform UI overlays:
#   TikTok  : bottom bar (like/comment/share) ~280 px on 1920-tall display
#   Reels   : bottom bar + audio info  ~260 px
#   Shorts  : subscribe button + info  ~300 px
#   Universal: modest safe margin

_PLATFORM_MARGIN_V: Dict[str, int] = {
    "tiktok":    280,
    "reels":     260,
    "shorts":    300,
    "universal": 100,
    "default":   100,
}


def _is_beta_clean() -> bool:
    return os.environ.get("VIRACLIP_BETA_CLEAN", "").lower() in {"1", "true", "yes"}


def _premium_captions_enabled() -> bool:
    try:
        from .vpi_production_safe_edit import production_safe_edit_enabled
        return _is_beta_clean() or production_safe_edit_enabled()
    except Exception:
        return _is_beta_clean()


def _margin_v(platform: str) -> int:
    return _PLATFORM_MARGIN_V.get(platform.lower(), _PLATFORM_MARGIN_V["default"])


def _beta_clean_margin_v(platform: str) -> int:
    return int(os.environ.get("CAPTION_BETA_CLEAN_MARGIN_V", _margin_v(platform)))


def _strip_caption_accents(text: str) -> str:
    return str(text or "").translate(str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")).lower()


def _caption_word_token(text: str) -> str:
    token = _strip_caption_accents(text)
    return re.sub(r"[^a-z0-9]+", "", token)


def _select_vpi_caption_keywords(words: List[WordTimestamp], max_terms: int = 2) -> List[str]:
    selected: List[str] = []
    for w in words:
        token = _caption_word_token(w.text)
        if token in _VPI_CAPTION_KEYWORDS and token not in selected:
            selected.append(token)
        if len(selected) >= max_terms:
            break
    return selected


def _safe_zone_adjustment(
    *,
    platform: str,
    base_margin_v: int,
    overlay_plan: Optional[Dict[str, Any]] = None,
    safe_zone_context: Optional[Dict[str, Any]] = None,
    play_res_y: int = 1920,
) -> tuple[int, int, Optional[str]]:
    adjusted_margin_v = base_margin_v
    adjusted_pos_y = int(round(play_res_y * 0.84))
    reasons: List[str] = []
    overlay_plan = overlay_plan or {}
    safe_zone_context = safe_zone_context or {}

    if overlay_plan.get("hook_overlay", {}).get("applied"):
        adjusted_margin_v += 28
        adjusted_pos_y = max(0, adjusted_pos_y - 26)
        reasons.append("hook_overlay")
    if overlay_plan.get("lower_third", {}).get("applied"):
        adjusted_margin_v += 18
        adjusted_pos_y = max(0, adjusted_pos_y - 18)
        reasons.append("lower_third")

    bbox_sources: List[Dict[str, Any]] = []
    for key in ("face_bbox", "speaker_bbox", "bbox"):
        bbox = safe_zone_context.get(key)
        if isinstance(bbox, dict):
            bbox_sources.append(bbox)

    if bbox_sources:
        low_face = False
        for bbox in bbox_sources:
            try:
                bottom = float(bbox.get("y", 0.0)) + float(bbox.get("height", bbox.get("h", 0.0)))
                if bottom >= 0.62:
                    low_face = True
                    break
            except Exception:
                continue
        if low_face:
            adjusted_margin_v += 22
            adjusted_pos_y = max(0, adjusted_pos_y - 18)
            reasons.append("face_bbox")

    if adjusted_margin_v < base_margin_v:
        adjusted_margin_v = base_margin_v
    if adjusted_margin_v == base_margin_v and adjusted_pos_y == int(round(play_res_y * 0.84)):
        return base_margin_v, adjusted_pos_y, None
    return adjusted_margin_v, adjusted_pos_y, ",".join(reasons) or "safe_default"


def _adaptive_font_size(base_size: int, words: List[WordTimestamp]) -> tuple[int, Optional[str]]:
    word_count = len(words)
    char_count = sum(len(str(w.text or "").strip()) for w in words)
    factor = 1.0
    reason = None
    if word_count >= 8 or char_count >= 48:
        factor = 0.82
        reason = "long_block"
    elif word_count >= 6 or char_count >= 36:
        factor = 0.90
        reason = "long_block"
    elif word_count >= 5 or char_count >= 28:
        factor = 0.95
        reason = "long_block"
    if reason is None:
        return base_size, None
    new_size = max(62, int(round(base_size * factor)))
    if new_size >= base_size:
        return base_size, None
    return new_size, reason


# ── Font configuration ─────────────────────────────────────────────────────
_CAPTION_FONT = os.environ.get("CAPTION_FONT_BOLD", "Arial")
_KNOWN_SAFE_FONTS = {"Arial", "DejaVu Sans", "Liberation Sans"}
if _CAPTION_FONT not in _KNOWN_SAFE_FONTS:
    logger.info("[caption] Using custom font '%s' — ensure it's installed or pass font_dir", _CAPTION_FONT)

# ── Visual presets ────────────────────────────────────────────────────────────
_DEFAULT_BETA_CLEAN_PRESET = "vpi_clean"

_VISUAL_PRESETS: Dict[str, Dict[str, Any]] = {
    "vpi_clean": {
        "name": "vpi_clean",
        "caption_style": "tiktok",
        "font": _CAPTION_FONT,
        "font_size": int(os.environ.get("CAPTION_VPI_FONT_SIZE", "72")),
        "primary_colour": _WHITE,
        "highlight_colour": _WHITE,
        "outline_colour": _BLACK,
        "back_colour": _SEMI_BG,
        "bold": -1,
        "italic": 0,
        "underline": 0,
        "strikeout": 0,
        "scale_x": 100,
        "scale_y": 100,
        "spacing": 1,
        "angle": 0,
        "border_style": 1,
        "outline": 3,
        "shadow": 1,
        "alignment": 2,
        "margin_l": 10,
        "margin_r": 10,
        "margin_v": _PLATFORM_MARGIN_V["tiktok"],
        "anchor": "an5",
        "position_x_ratio": 0.5,
        "position_y_ratio": 0.84,
        "max_words_per_block": 3,
        "min_duration_s": 0.65,
        "max_duration_s": 1.8,
        "gap_threshold_s": 0.45,
        "emojis": False,
        "top_titles": False,
        "pip": False,
    },
}


def _active_visual_preset_name() -> str:
    requested = os.environ.get("VIRACLIP_VISUAL_PRESET", "").strip().lower()
    if requested:
        return requested
    if _is_beta_clean():
        return _DEFAULT_BETA_CLEAN_PRESET
    return "default"


def _get_visual_preset(name: str) -> Optional[Dict[str, Any]]:
    if name in _VISUAL_PRESETS:
        return _VISUAL_PRESETS[name]
    if name != "default":
        logger.warning(
            "[vpi-preset] unknown preset=%s; falling back to %s",
            name,
            _DEFAULT_BETA_CLEAN_PRESET,
        )
        return _VISUAL_PRESETS[_DEFAULT_BETA_CLEAN_PRESET]
    return None


def _beta_clean_visual_preset() -> Dict[str, Any]:
    preset = _get_visual_preset(_active_visual_preset_name())
    if preset is None:
        preset = _VISUAL_PRESETS[_DEFAULT_BETA_CLEAN_PRESET]
    tokens = get_vpi_visual_design_tokens()
    colors = tokens.get("colors") or {}
    typography = tokens.get("typography") or {}
    spacing = tokens.get("spacing") or {}
    preset = dict(preset)
    preset["font_size"] = int(round(float(preset.get("font_size") or 72) * float(typography.get("caption_font_scale") or 1.0)))
    preset["primary_colour"] = _ass_colour(245, 245, 242)
    preset["highlight_colour"] = _ass_colour(245, 245, 242)
    preset["outline_colour"] = _ass_colour(255, 255, 255, 220)
    preset["back_colour"] = _ass_colour(26, 26, 26, 230)
    preset["margin_v"] = max(int(preset.get("margin_v") or 0), int(spacing.get("caption_bottom_margin") or 280))
    preset["position_x_ratio"] = 0.5
    preset["position_y_ratio"] = 0.84
    logger.info("[vpi-preset] using preset=%s", preset["name"])
    return preset


def _style_def_from_preset(preset: Dict[str, Any], margin_v: int) -> str:
    return (
        f"Default,{preset['font']},{preset['font_size']},"
        f"{preset['primary_colour']},{preset['highlight_colour']},"
        f"{preset['outline_colour']},{preset['back_colour']},"
        f"{preset['bold']},{preset['italic']},{preset['underline']},{preset['strikeout']},"
        f"{preset['scale_x']},{preset['scale_y']},{preset['spacing']},{preset['angle']},"
        f"{preset['border_style']},{preset['outline']},{preset['shadow']},"
        f"{preset['alignment']},{preset['margin_l']},{preset['margin_r']},{margin_v},1"
    )

# ── Style presets ─────────────────────────────────────────────────────────────
# MarginV is set to a placeholder string "MARGINV" that is substituted at
# script-build time with the platform-specific safe-zone value.

_STYLE_DEFS: Dict[str, str] = {
    # Name,Font,Size,Primary,Secondary,Outline,Back,Bold,Ital,Und,Stk,
    # ScX,ScY,Spacing,Angle,BorderStyle,Outline,Shadow,Align,MarL,MarR,MarV,Enc
    "karaoke": (
        f"Default,{_CAPTION_FONT},72,"
        f"{_WHITE},{_YELLOW},{_BLACK},{_SEMI_BG},"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,MARGINV,1"
    ),
    "highlight": (
        f"Default,{_CAPTION_FONT},68,"
        f"{_BLACK},{_RED},{_BLACK},{_YELLOW},"
        "-1,0,0,0,100,100,0,0,3,0,0,2,10,10,MARGINV,1"
    ),
    "tiktok": (
        f"Default,{_CAPTION_FONT},80,"
        f"{_WHITE},{_YELLOW},{_BLACK},{_SEMI_BG},"
        "-1,0,0,0,100,100,1,0,1,4,2,2,10,10,MARGINV,1"
    ),
    "minimal": (
        f"Default,{_CAPTION_FONT},64,"  # 54→64 más grande
        f"{_WHITE},{_WHITE},{_BLACK},{_SEMI_BG},"  # TRANSP→SEMI_BG fondo visible
        "-1,0,0,0,100,100,0,0,3,2,0,2,10,10,MARGINV,1"  # BorderStyle 1→3 para caja
    ),
    "neon": (
        f"Default,{_CAPTION_FONT},66,"
        f"{_CYAN},{_WHITE},{_CYAN},{_SEMI_BG},"
        "-1,0,0,0,100,100,2,0,1,2,3,2,10,10,MARGINV,1"
    ),
}

# Template → caption style auto-mapping
_TEMPLATE_STYLE_MAP: Dict[str, str] = {
    "tiktok_viral":   "tiktok",
    "reels_drama":    "highlight",
    "youtube_shorts": "karaoke",
    "high_energy":    "highlight",
    "tutorial":       "highlight",  # minimal era invisible - cambiado
    "interview":      "highlight",  # minimal era invisible - cambiado
    "education":      "highlight",  # minimal era invisible - cambiado
}


# ── ASS script builder ────────────────────────────────────────────────────────

def _ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc"""
    cs = int(round(seconds * 100))
    h  = cs // 360000;  cs %= 360000
    m  = cs // 6000;    cs %= 6000
    s  = cs // 100;     cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _is_emphasis_word(word: WordTimestamp, threshold: float = 0.82) -> bool:
    """Return True when word.score >= threshold (WhisperX high confidence)."""
    return word.score >= threshold


def _build_karaoke_text(
    words: List[WordTimestamp],
    emphasis_threshold: float = 0.82,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Build \\k-tagged karaoke text from word list with emphasis support."""
    parts = []
    keyword_terms = set(_select_vpi_caption_keywords(words))
    sensitive_soft = bool(isinstance(caption_polish_profile, dict) and str(caption_polish_profile.get("caption_polish_profile") or "") == "sensitive_soft")
    if isinstance(caption_polish_profile, dict) and not bool(caption_polish_profile.get("keyword_highlight_allowed", True)):
        keyword_terms = set()
    for w in words:
        token = _caption_word_token(w.text)
        if sensitive_soft:
            parts.append(f"{{\\k{w.duration_cs}}}{w.text}")
        elif _is_emphasis_word(w, emphasis_threshold):
            # High impact word: bright yellow + slightly larger
            parts.append(
                f"{{\\k{w.duration_cs}\\c{_YELLOW}\\fscx110\\fscy110}}{w.text}"
                f"{{\\c{_WHITE}\\fscx100\\fscy100}}"
            )
        elif token in keyword_terms:
            parts.append(
                f"{{\\k{w.duration_cs}\\c{_WHITE}\\b1\\fscx106\\fscy106}}{w.text}"
                f"{{\\c{_WHITE}\\b0\\fscx100\\fscy100}}"
            )
        else:
            parts.append(f"{{\\k{w.duration_cs}}}{w.text}")
    return " ".join(parts)


def _build_beta_clean_text(words: List[WordTimestamp], active_idx: int = -1) -> str:
    """Fixed-position text with inline highlight only; no dynamic ASS positioning."""
    parts = []
    for i, w in enumerate(words):
        text = w.text
        if i == active_idx:
            parts.append(f"{{\\c{_WHITE}\\b1}}{text}{{\\c{_WHITE}\\b0}}")
        else:
            parts.append(text)
    return "{\\an2}" + " ".join(parts)


def _build_beta_clean_karaoke_text(
    words: List[WordTimestamp],
    pos_tag: str,
    highlight_colour: str = _WHITE,
    font_size: Optional[int] = None,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Single visual ASS event per block, with active word handled by karaoke timing."""
    polish = caption_polish_profile if isinstance(caption_polish_profile, dict) else {}
    keyword_terms = set(_select_vpi_caption_keywords(words))
    sensitive_soft = bool(str(polish.get("caption_polish_profile") or "") == "sensitive_soft")
    if not bool(polish.get("keyword_highlight_allowed", True)):
        keyword_terms = set()
    max_words_per_line = max(3, int(polish.get("max_words_per_caption") or 5))
    protected_phrases = _caption_phrase_tokens()

    def _render_word(w: WordTimestamp) -> str:
        token = _caption_word_token(w.text)
        duration_cs = max(1, int(round(max(0.08, w.end - w.start) * 100)))
        if sensitive_soft:
            return f"{{\\kf{duration_cs}}}{w.text}"
        if w.emphasis:
            return (
                f"{{\\kf{duration_cs}\\c{highlight_colour}\\b1\\fscx108\\fscy108}}"
                f"{w.text}{{\\c{_WHITE}\\b0\\fscx100\\fscy100}}"
            )
        if token in keyword_terms:
            return (
                f"{{\\kf{duration_cs}\\c{_SOFT_WHITE}\\b1\\fscx106\\fscy106}}{w.text}"
                f"{{\\c{_WHITE}\\b0\\fscx100\\fscy100}}"
            )
        return f"{{\\kf{duration_cs}\\c{highlight_colour}\\b1}}{w.text}{{\\c{_WHITE}\\b0}}"

    prefix = pos_tag
    if font_size:
        prefix = f"{pos_tag}{{\\fs{font_size}}}"
    else:
        prefix = f"{pos_tag}{{\\fs72}}"

    if len(words) <= 3:
        return prefix + "{\\fad(90,120)}" + " ".join(_render_word(w) for w in words)

    split_at = _caption_split_index(
        words,
        max_words_per_line=max_words_per_line,
        max_chars_per_line=int(polish.get("max_chars_per_caption") or 0),
        protected_phrases=protected_phrases,
    )
    first_line = " ".join(_render_word(w) for w in words[:split_at])
    second_line = " ".join(_render_word(w) for w in words[split_at:])
    return prefix + "{\\fad(90,120)}" + first_line + "\\N" + second_line


_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")


def _normalize_caption_text(text: str) -> str:
    return " ".join(_ASS_OVERRIDE_RE.sub("", text).lower().split())


def _strip_accents(text: str) -> str:
    return str(text or "").translate(str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")).lower()


def _topic_from_text(text: str, editorial_type: str = "") -> str:
    haystack = _strip_accents(f"{editorial_type} {text}")
    if "deceso" in haystack or "momento dificil" in haystack or "menos carga" in haystack:
        return "decesos"
    if "salud" in haystack or "especialista" in haystack or "prueba" in haystack:
        return "salud"
    if "autonom" in haystack or "motor" in haystack or "ingreso" in haystack:
        return "autonomos"
    if "vida" in haystack or "proteccion" in haystack or "ausencia" in haystack:
        return "vida"
    return ""


def _select_caption_keywords(text: str, editorial_type: str = "") -> List[str]:
    topic = _topic_from_text(text, editorial_type)
    haystack = _strip_accents(text)
    candidates = list(_CAPTION_KEYWORDS.get(topic) or [])
    if not candidates:
        for terms in _CAPTION_KEYWORDS.values():
            candidates.extend(terms)
    selected: List[str] = []
    for term in candidates:
        if _strip_accents(term) in haystack and term not in selected:
            selected.append(term)
        if len(selected) >= 4:
            break
    return selected


def _discover_caption_icon_assets() -> List[Path]:
    try:
        from .vpi_asset_library_service import build_asset_index
        asset_index = build_asset_index()
        verified_icons = list((asset_index.get("verified") or {}).get("icons") or [])
        if verified_icons:
            resolved: List[Path] = []
            for entry in verified_icons:
                path = Path(str((entry or {}).get("path") or ""))
                if path.exists() and path.is_file():
                    resolved.append(path)
            if resolved:
                return resolved
    except Exception as exc:
        logger.debug("[caption-icon] asset_library_unavailable reason=%s", exc)

    root = Path(__file__).resolve().parents[3]
    exts = {".png", ".jpg", ".jpeg", ".webp", ".svg"}
    assets: List[Path] = []
    for item in _ICON_DIRS:
        directory = Path(item)
        if not directory.is_absolute():
            directory = root / directory
        if not directory.exists() or not directory.is_dir():
            continue
        assets.extend(path for path in sorted(directory.rglob("*")) if path.is_file() and path.suffix.lower() in exts)
    return assets


def _match_caption_icon(concept: str, assets: List[Path]) -> Optional[Path]:
    needles = [_strip_accents(term) for term in _ICON_CONCEPTS.get(concept, [concept])]
    for asset in assets:
        name = _strip_accents(asset.stem)
        if any(term and term in name for term in needles):
            return asset
    return None


def _discover_font_registry() -> Dict[str, Any]:
    try:
        from .vpi_asset_library_service import build_asset_index
        asset_index = build_asset_index()
    except Exception as exc:
        logger.debug("[font-library] asset_library_unavailable reason=%s", exc)
        asset_index = {}
    verified_fonts = list((asset_index.get("verified") or {}).get("fonts") or [])
    selected_font = _CAPTION_FONT
    fallback = True
    if verified_fonts:
        selected_font = Path(str((verified_fonts[0] or {}).get("path") or selected_font)).stem or _CAPTION_FONT
        fallback = False
    logger.info("[font-library] discovered count=%d", len(verified_fonts))
    logger.info("[font-library] selected role=caption_primary font=%s fallback=%s", selected_font, str(fallback).lower())
    return {
        "fonts_discovered": len(verified_fonts),
        "selected_caption_font": selected_font,
        "caption_font_fallback": fallback,
    }


def _hook_overlay_text(text: str, hook_intent: str) -> str:
    lowered = _strip_accents(text)
    original = " ".join(str(text or "").replace("\n", " ").split())
    if hook_intent == "myth_flip":
        for marker in ("no va de miedo", "no es postureo", "no es lujo"):
            if marker in lowered:
                return marker.capitalize()
    if hook_intent == "risk_warning":
        if "la salud no siempre avisa" in lowered:
            return "La salud no siempre avisa"
        if "manana" in lowered:
            return "¿Y si mañana no puedes?"
    if hook_intent == "practical_advice":
        if "antes de mirar" in lowered:
            return "Antes de mirar precios..."
        if "vida real" in lowered:
            return "Mira tu vida real"
    if hook_intent == "autonomous_business_stakes":
        if "autonom" in lowered:
            return "Si eres autónomo..."
        if "motor" in lowered:
            return "Tú eres el motor"
    if hook_intent == "emotional_closure":
        if "cuando mas falta hace" in lowered or "cuando más falta hace" in original.lower():
            return "Cuando más falta hace"
        if "menos carga" in lowered and "familia" in lowered:
            return "Menos carga para tu familia"
    return ""


def plan_caption_overlay_pack(
    text: str,
    *,
    hook_intent: str = "",
    editorial_type: str = "",
    words: Optional[List[Dict[str, Any]]] = None,
    subtitle_already_strong: bool = False,
    local_icon_assets: Optional[List[Path]] = None,
    enable_lower_third: bool = True,
    composition_decision: Optional[Dict[str, Any]] = None,
    global_visual_layer_budget: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    text = str(text or "")
    words = list(words or [])
    hook_intent = str(hook_intent or "")
    visual_tokens = get_vpi_visual_design_tokens()
    visual_design_version = str(visual_tokens.get("visual_design_version") or "a1")
    keyword_terms = _select_caption_keywords(text, editorial_type)
    daily_mode = str(os.environ.get("VPI_DAILY_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}
    if keyword_terms:
        logger.info("[caption-overlay] keyword_emphasis applied=true words=%s", "|".join(keyword_terms[:4]))
    else:
        logger.info("[caption-overlay] skipped reason=no_keywords")

    word_count = len(words) if words else len(text.split())
    caption_start_s = float(words[0].get("start", 0.0)) if words else 0.0
    long_subtitle = word_count >= 18 or len(text) > 160
    sensitive_tone = _topic_from_text(text, editorial_type) == "decesos" and hook_intent == "risk_warning"
    actions: List[str] = []
    density_actions: List[Dict[str, str]] = []

    overlay_text = _hook_overlay_text(text, hook_intent)
    if daily_mode:
        hook_overlay = {
            "applied": False,
            "reason": "daily_mode",
            "rendered": False,
            "disabled_by": "daily_mode",
        }
        logger.info("VPI_HOOK_LOWER_THIRD_DISABLED_DAILY layer=hook_overlay reason=daily_mode")
    elif subtitle_already_strong:
        hook_overlay = {"applied": False, "reason": "subtitle_already_strong"}
        logger.info("[caption-overlay] hook_overlay skipped reason=subtitle_already_strong")
    elif sensitive_tone:
        hook_overlay = {"applied": False, "reason": "sensitive_tone"}
        logger.info("[caption-overlay] hook_overlay skipped reason=sensitive_tone")
    elif long_subtitle:
        hook_overlay = {"applied": False, "reason": "density_guard_long_subtitle"}
        density_actions.append({"action": "skip_overlay", "reason": "too_many_elements"})
        logger.info("[caption-overlay] density_guard action=skip_overlay reason=too_many_elements")
    elif overlay_text:
        hook_overlay = {"applied": True, "text": overlay_text, "start_s": 0.05, "duration_s": 1.1, "safe_zone": "upper_third"}
        actions.append("hook_overlay")
        logger.info('[caption-overlay] hook_overlay applied=true text="%s" duration=%.1f', overlay_text, 1.1)
    else:
        hook_overlay = {"applied": False, "reason": "no_hook_text"}
        logger.info("[caption-overlay] hook_overlay skipped reason=no_hook_text")

    concept = _topic_from_text(text, editorial_type) or ("autonomo" if "autonom" in _strip_accents(text) else "")
    icon_assets = local_icon_assets if local_icon_assets is not None else _discover_caption_icon_assets()
    _icon_entry_by_path: Dict[str, Dict[str, Any]] = {}
    _manifest_found = False
    try:
        from .vpi_asset_library_service import build_asset_index
        _asset_index = build_asset_index()
        _manifest_found = bool(_asset_index.get("manifest_found"))
        for _entry in list((_asset_index.get("verified") or {}).get("icons") or []):
            _icon_entry_by_path[str((_entry or {}).get("path") or "")] = dict(_entry or {})
    except Exception as exc:
        logger.debug("[caption-icon] asset_library_unavailable reason=%s", exc)
    icon: Dict[str, Any] = {"applied": False, "concept": concept, "reason": "not_useful"}
    if long_subtitle or hook_overlay.get("applied"):
        icon["reason"] = "too_many_elements"
        density_actions.append({"action": "skip_icon", "reason": "too_many_elements"})
        logger.info("[caption-overlay] density_guard action=skip_icon reason=too_many_elements")
    elif sensitive_tone:
        icon["reason"] = "sensitive_tone"
        logger.info("[caption-icon] skipped reason=sensitive_tone")
    elif concept:
        asset = _match_caption_icon(concept, icon_assets)
        if asset:
            _meta = _icon_entry_by_path.get(str(asset), {})
            _verified = bool(_meta)
            _license = str((_meta or {}).get("license_name") or "")
            _source = str((_meta or {}).get("source_name") or "")
            if _manifest_found and not _verified:
                icon["reason"] = "no_verified_icon"
                logger.info("[caption-icon] skipped reason=no_verified_icon")
            elif _verified and not _license:
                icon["reason"] = "license_missing"
                logger.info("[caption-icon] skipped reason=license_missing")
            else:
                icon = {
                    "applied": True,
                    "concept": concept,
                    "asset": str(asset),
                    "start_s": 0.2,
                    "duration_s": 1.2,
                    "caption_icon_verified": _verified,
                    "caption_icon_license": _license,
                    "caption_icon_source": _source or ("unverified_local" if not _verified else ""),
                }
                actions.append("semantic_icon")
                logger.info("[caption-icon] concept=%s asset=%s applied=true", concept, asset)
                logger.info(
                    "[caption-icon] verified=%s source=%s license=%s",
                    str(_verified).lower(),
                    icon.get("caption_icon_source") or "unverified_local",
                    icon.get("caption_icon_license") or "none",
                )
        else:
            icon["reason"] = "no_local_asset"
            logger.info("[caption-icon] skipped reason=no_local_asset")
    else:
        logger.info("[caption-icon] skipped reason=not_useful")

    topic = _topic_from_text(text, editorial_type)
    lower_text = {
        "salud": "Seguro de salud",
        "decesos": "Seguro de decesos",
        "autonomos": "Protección para autónomos",
        "vida": "Valentín Protección Integral",
    }.get(topic, "")
    if daily_mode:
        lower_third = {
            "applied": False,
            "reason": "daily_mode",
            "rendered": False,
            "disabled_by": "daily_mode",
        }
        logger.info("VPI_HOOK_LOWER_THIRD_DISABLED_DAILY layer=lower_third reason=daily_mode")
    elif not enable_lower_third or subtitle_already_strong or hook_overlay.get("applied"):
        lower_third = {"applied": False, "reason": "branding_conflict"}
        logger.info("[caption-overlay] lower_third skipped reason=branding_conflict")
    elif long_subtitle:
        lower_third = {"applied": False, "reason": "layout_conflict"}
        logger.info("[caption-overlay] lower_third skipped reason=layout_conflict")
    elif hook_overlay.get("applied"):
        lower_third = {"applied": True, "text": lower_text or "Valentín Protección Integral", "start_s": 1.45, "duration_s": 1.8, "delayed": True}
        actions.append("lower_third")
        density_actions.append({"action": "delay_lower_third", "reason": "too_many_elements"})
        logger.info("[caption-overlay] density_guard action=delay reason=too_many_elements")
        logger.info("[caption-overlay] lower_third applied=true text=%s", lower_third["text"])
    elif lower_text:
        lower_third = {"applied": True, "text": lower_text, "start_s": 0.4, "duration_s": 1.8, "delayed": False}
        actions.append("lower_third")
        logger.info("[caption-overlay] lower_third applied=true text=%s", lower_text)
    else:
        lower_third = {"applied": False, "reason": "layout_conflict"}
        logger.info("[caption-overlay] lower_third skipped reason=layout_conflict")

    if keyword_terms:
        actions.insert(0, "keyword_emphasis")
    _font_registry = _discover_font_registry()

    # ── VPI Premium Composition Pack v1: resolve visual layer conflicts ──
    composition_allowed_layers: List[str] = []
    composition_skipped_layers: List[Dict[str, Any]] = []
    composition_decision_applied = False
    layer_overload = False
    if composition_decision and isinstance(composition_decision, dict) and composition_decision.get("composition_pack"):
        try:
            from .vpi_visual_effects_service import resolve_visual_layer_conflicts as _resolve_visual_layer_conflicts
            _layers_to_resolve: List[Dict[str, Any]] = []
            if hook_overlay.get("applied"):
                _layers_to_resolve.append({
                    "type": "hook_overlay",
                    "start_s": hook_overlay.get("start_s", 0.0),
                    "duration_s": hook_overlay.get("duration_s", 1.1),
                    "text": hook_overlay.get("text", ""),
                })
            if icon.get("applied"):
                _layers_to_resolve.append({
                    "type": "icon",
                    "start_s": icon.get("start_s", 0.2),
                    "duration_s": icon.get("duration_s", 1.2),
                    "text": icon.get("text", "") or icon.get("concept", ""),
                })
            if lower_third.get("applied"):
                _layers_to_resolve.append({
                    "type": "lower_third",
                    "start_s": lower_third.get("start_s", 0.4),
                    "duration_s": lower_third.get("duration_s", 1.8),
                    "text": lower_third.get("text", ""),
                })
            _resolved = _resolve_visual_layer_conflicts(_layers_to_resolve, composition_decision)
            _resolved_layers = list(_resolved.get("allowed_layers") or [])
            _resolved_types = {l.get("type") for l in _resolved_layers}
            composition_allowed_layers = [str(item.get("type") or "") for item in _resolved_layers]
            composition_skipped_layers = list(_resolved.get("skipped_layers") or [])
            composition_decision_applied = bool(_resolved.get("composition_decision_applied"))
            layer_overload = bool(_resolved.get("layer_overload"))
            if "hook_overlay" not in _resolved_types and hook_overlay.get("applied"):
                logger.info("[caption-overlay] composition_allowed name=hook_overlay yes=false reason=composition_conflict_resolver")
                hook_overlay = {"applied": False, "reason": "composition_conflict_resolver"}
                if "hook_overlay" in actions:
                    actions.remove("hook_overlay")
            else:
                logger.info("[caption-overlay] composition_allowed name=hook_overlay yes=%s reason=%s", "true" if "hook_overlay" in _resolved_types else "false", "allowed" if "hook_overlay" in _resolved_types else "not_planned")
            if "icon" not in _resolved_types and icon.get("applied"):
                logger.info("[caption-overlay] composition_allowed name=icon yes=false reason=composition_conflict_resolver")
                icon = {"applied": False, "concept": icon.get("concept", ""), "reason": "composition_conflict_resolver"}
                if "semantic_icon" in actions:
                    actions.remove("semantic_icon")
            else:
                logger.info("[caption-overlay] composition_allowed name=icon yes=%s reason=%s", "true" if "icon" in _resolved_types else "false", "allowed" if "icon" in _resolved_types else "not_planned")
            if "lower_third" not in _resolved_types and lower_third.get("applied"):
                logger.info("[caption-overlay] composition_allowed name=lower_third yes=false reason=composition_conflict_resolver")
                lower_third = {"applied": False, "reason": "composition_conflict_resolver"}
                if "lower_third" in actions:
                    actions.remove("lower_third")
            else:
                logger.info("[caption-overlay] composition_allowed name=lower_third yes=%s reason=%s", "true" if "lower_third" in _resolved_types else "false", "allowed" if "lower_third" in _resolved_types else "not_planned")
            if composition_skipped_layers:
                for skipped in composition_skipped_layers:
                    logger.info("[caption-overlay] density_guard action=%s reason=composition_conflict", f"skip_{skipped.get('type')}")
        except Exception as _comp_resolve_e:
            logger.debug("[composition-pack] conflict_resolver skipped reason=%s", _comp_resolve_e)

    global_budget = global_visual_layer_budget if isinstance(global_visual_layer_budget, dict) else {}
    if global_budget:
        budget_allowed = set(str(item) for item in (global_budget.get("allowed_layers") or global_budget.get("visual_layers_allowed") or []))
        budget_decisions = global_budget.get("layer_decisions") if isinstance(global_budget.get("layer_decisions"), dict) else {}
        for _layer_name, _layer_value in (("hook_overlay", hook_overlay), ("caption_icon", icon), ("lower_third", lower_third)):
            _budget_decision = dict((budget_decisions or {}).get(_layer_name) or {})
            if not _budget_decision and _layer_name == "caption_icon":
                _budget_decision = dict((budget_decisions or {}).get("icon") or {})
            _action = str(_budget_decision.get("action") or "").strip()
            _reason = str(_budget_decision.get("reason") or "visual_layer_budget")
            _allowed = _layer_name in budget_allowed or ("icon" if _layer_name == "caption_icon" else _layer_name) in budget_allowed or _action == "allow"
            if not _allowed or _action == "drop":
                if _layer_value.get("applied"):
                    logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=%s reason=%s", _layer_name, _reason)
                logger.info("OVERLAY_RENDER_BLOCKED_BY_BUDGET layer=%s reason=%s", _layer_name, _reason)
                if _layer_name == "hook_overlay":
                    hook_overlay = {"applied": False, "planned": True, "rendered": False, "dropped_by_budget": True, "budget_drop_reason": _reason, "reason": _reason}
                elif _layer_name == "caption_icon":
                    icon = {"applied": False, "planned": True, "rendered": False, "dropped_by_budget": True, "budget_drop_reason": _reason, "concept": icon.get("concept", ""), "reason": _reason}
                elif _layer_name == "lower_third":
                    lower_third = {"applied": False, "planned": True, "rendered": False, "dropped_by_budget": True, "budget_drop_reason": _reason, "reason": _reason}
            elif _action == "delay":
                _new_start = float(_budget_decision.get("new_start_s") or _layer_value.get("start_s") or 0.0)
                if _layer_name == "hook_overlay" and hook_overlay.get("applied"):
                    hook_overlay["start_s"] = round(_new_start, 2)
                    hook_overlay["end_s"] = round(_new_start + float(hook_overlay.get("duration_s") or 0.0), 2)
                elif _layer_name == "lower_third" and lower_third.get("applied"):
                    lower_third["start_s"] = round(_new_start, 2)
                elif _layer_name == "caption_icon" and icon.get("applied"):
                    icon["start_s"] = round(_new_start, 2)
                logger.info(
                    "OVERLAY_DELAYED_COLLISION_GUARD layer=%s old_start=%.2f new_start=%.2f",
                    _layer_name,
                    float(_layer_value.get("start_s") or 0.0),
                    _new_start,
                )
            elif _action == "reduce":
                logger.info(
                    "OVERLAY_SAFE_ZONE_ASSIGNED layer=%s zone=%s",
                    _layer_name,
                    str(_budget_decision.get("safe_zone") or _layer_value.get("safe_zone") or "default"),
                )
        for _planned_name, _planned_value in (("hook_overlay", hook_overlay), ("caption_icon", icon), ("lower_third", lower_third)):
            if _planned_name == "caption_icon":
                _planned_value.setdefault("planned", bool(_planned_value.get("applied")))
                _planned_value.setdefault("rendered", bool(_planned_value.get("applied")))
            else:
                _planned_value.setdefault("planned", bool(_planned_value.get("applied")))
                _planned_value.setdefault("rendered", bool(_planned_value.get("applied")))
            _planned_value.setdefault("dropped_by_budget", False)
            _planned_value.setdefault("budget_drop_reason", "")

    pack_applied = bool(actions)
    logger.info("[caption-overlay] pack_applied=%s actions=%s", str(pack_applied).lower(), "|".join(actions) or "none")
    logger.info(
        "[editing-richness] caption_overlay_pack=%s reason=%s",
        str(pack_applied).lower(),
        "caption_overlay_actions" if pack_applied else "normal_subtitles_only",
    )
    return {
        "caption_overlay_pack": pack_applied,
        "caption_overlay_actions": actions,
        "keyword_emphasis_applied": bool(keyword_terms),
        "keyword_emphasis_terms": keyword_terms[:4],
        "hook_overlay": hook_overlay,
        "caption_icon": icon,
        "lower_third": lower_third,
        "caption_start_s": caption_start_s,
        "density_guard_actions": density_actions,
        "composition_allowed_layers": composition_allowed_layers,
        "composition_skipped_layers": composition_skipped_layers,
        "composition_decision_applied": composition_decision_applied,
        "layer_overload": layer_overload,
        "caption_overlay_pack_reason": "caption_overlay_actions" if pack_applied else "normal_subtitles_only",
        "font_registry": _font_registry,
        "visual_design_version": visual_design_version,
        "visual_design_tokens_applied": True,
        "visual_design_tokens_applied_to_captions": True,
    }


def _build_highlight_text(
    words: List[WordTimestamp],
    active_idx: int,
    emphasis_threshold: float = 0.82,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build per-word dialogue line where the active word gets a highlight override.
    Used for karaoke-highlight style — each dialogue event represents one word
    being highlighted while others are shown dimmed.

    Emphasis words (high score) use less transparency (H40) even when not active.
    Active words with emphasis use RED color to differentiate from standard active.
    """
    parts = []
    keyword_terms = set(_select_vpi_caption_keywords(words))
    sensitive_soft = bool(isinstance(caption_polish_profile, dict) and str(caption_polish_profile.get("caption_polish_profile") or "") == "sensitive_soft")
    if isinstance(caption_polish_profile, dict) and not bool(caption_polish_profile.get("keyword_highlight_allowed", True)):
        keyword_terms = set()
    for i, w in enumerate(words):
        token = _caption_word_token(w.text)
        if i == active_idx:
            if sensitive_soft:
                parts.append(f"{{\\c{_WHITE}\\bord0\\shad0\\p0}}{w.text}{{\\r}}")
            elif _is_emphasis_word(w, emphasis_threshold):
                # Active + emphasis = RED color for high confidence words
                parts.append(f"{{\\c{_RED}\\bord0\\shad0\\p0}}{w.text}{{\\r}}")
            elif token in keyword_terms:
                parts.append(f"{{\\c{_WHITE}\\b1\\fscx106\\fscy106}}{w.text}{{\\r}}")
            else:
                # Normal active = YELLOW
                parts.append(f"{{\\c{_YELLOW}\\bord0\\shad0\\p0}}{w.text}{{\\r}}")
        elif sensitive_soft:
            parts.append(f"{{\\alpha&H80&}}{w.text}{{\\alpha&H00&}}")
        elif token in keyword_terms:
            parts.append(f"{{\\c{_SOFT_WHITE}\\b1\\fscx104\\fscy104}}{w.text}{{\\c{_WHITE}\\b0}}")
        elif _is_emphasis_word(w, emphasis_threshold):
            # Emphasis words: less transparent (H40) so they stand out more
            parts.append(f"{{\\alpha&H40&}}{w.text}{{\\alpha&H00&}}")
        else:
            # Regular words: more transparent (H80)
            parts.append(f"{{\\alpha&H80&}}{w.text}{{\\alpha&H00&}}")
    return " ".join(parts)


def build_ass_script(
    lines: List[CaptionLine],
    style: str = "tiktok",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    uppercase: bool = True,
    platform: str = "tiktok",
    emphasis_threshold: float = 0.82,
    overlay_plan: Optional[Dict[str, Any]] = None,
    safe_zone_context: Optional[Dict[str, Any]] = None,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build a complete ASS script from caption lines.

    For 'karaoke' and 'tiktok' styles: one dialogue event per line using \\k tags.
    For 'highlight' style: one dialogue event PER WORD so each word can get its
                           own background-box highlight as it's spoken.

    platform: used to set platform-specific caption safe zones (MarginV).
              Supported: 'tiktok', 'reels', 'shorts', 'universal'.
    """
    beta_clean = _premium_captions_enabled()
    preset: Optional[Dict[str, Any]] = None
    safe_zone_context = safe_zone_context or {}
    polish = caption_polish_profile if isinstance(caption_polish_profile, dict) else {}
    keyword_highlight_logged = False
    if beta_clean:
        preset = _beta_clean_visual_preset()
        style = str(preset["caption_style"])
        base_margin_v = int(os.environ.get("CAPTION_BETA_CLEAN_MARGIN_V", preset["margin_v"]))
        margin_v, safe_pos_y, safe_reason = _safe_zone_adjustment(
            platform=platform,
            base_margin_v=base_margin_v,
            overlay_plan=overlay_plan,
            safe_zone_context=safe_zone_context,
            play_res_y=play_res_y,
        )
        style_def = _style_def_from_preset(preset, margin_v)
        logger.info("VPI_PREMIUM_CAPTIONS_STYLE_APPLIED backend=caption_service style=vpi_clean palette=white_premium")
        if safe_reason:
            logger.info("VPI_CAPTION_SAFE_ZONE_ADJUSTED backend=caption_service reason=%s", safe_reason)
    else:
        style_def = _STYLE_DEFS.get(style, _STYLE_DEFS["tiktok"])
        margin_v, _, safe_reason = _safe_zone_adjustment(
            platform=platform,
            base_margin_v=_margin_v(platform),
            overlay_plan=overlay_plan,
            safe_zone_context=safe_zone_context,
            play_res_y=play_res_y,
        )
        style_def = style_def.replace("MARGINV", str(margin_v))
        if safe_reason:
            logger.info("VPI_CAPTION_SAFE_ZONE_ADJUSTED backend=caption_service reason=%s", safe_reason)
    is_highlight = (style == "highlight") and not beta_clean
    if beta_clean:
        assert preset is not None
        pos_x = int(os.environ.get(
            "CAPTION_VPI_POS_X",
            round(play_res_x * float(preset["position_x_ratio"])),
        ))
        pos_y = int(os.environ.get(
            "CAPTION_VPI_POS_Y",
            safe_pos_y,
        ))
        pos_y = min(pos_y, safe_pos_y)
        anchor = str(preset["anchor"])
        pos_tag = f"{{\\{anchor}\\pos({pos_x},{pos_y})}}"
        logger.info(
            "[caption-layout] beta_clean fixed_bottom=true alignment=2 margin_v=%d",
            margin_v,
        )
        logger.info(
            "[caption-layout] preset=%s font=%s font_size=%s outline=%s shadow=%s "
            "highlight=%s max_words=%s min_dur=%.2f max_dur=%.2f "
            "emojis=%s top_titles=%s pip=%s",
            preset["name"],
            preset["font"],
            preset["font_size"],
            preset["outline"],
            preset["shadow"],
            preset["highlight_colour"],
            preset["max_words_per_block"],
            float(preset["min_duration_s"]),
            float(preset["max_duration_s"]),
            preset["emojis"],
            preset["top_titles"],
            preset["pip"],
        )
        logger.info("[caption-layout] no dynamic vertical positioning")
        logger.info(
            "[caption-layout] beta_clean absolute_position=true x=%d y=%d anchor=%s",
            pos_x,
            pos_y,
            anchor,
        )
        logger.info("[caption-layout] fixed_pos_tag applied to all dialogues")
        logger.info(
            "VPI_ASS_CAPTION_PLACEMENT_STABILIZED backend=caption_service pos_y=%d margin_v=%d",
            pos_y,
            margin_v,
        )

    header = f"""\
[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {play_res_x}
PlayResY: {play_res_y}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, \
BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, \
BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style_def}
Style: HookOverlay,{_CAPTION_FONT},58,{_WHITE},{_WHITE},{_BLACK},{_SEMI_BG},-1,0,0,0,100,100,0,0,1,3,2,8,40,40,120,1
Style: LowerThird,{_CAPTION_FONT},42,{_WHITE},{_WHITE},{_BLACK},{_SEMI_BG},-1,0,0,0,100,100,0,0,3,1,0,1,42,42,360,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events: List[str] = []

    previous_end = 0.0
    previous_text = ""
    dedupe_removed = 0
    overlap_fixed = 0
    min_duration_applied = 0

    for line in lines:
        words = line.words
        line_keyword_terms = _select_vpi_caption_keywords(words)
        if not bool(polish.get("keyword_highlight_allowed", True)):
            line_keyword_terms = []
        elif line_keyword_terms and int(polish.get("max_lines") or 2) <= 1:
            line_keyword_terms = line_keyword_terms[:1]
        if line_keyword_terms and not keyword_highlight_logged:
            logger.info(
                "VPI_CAPTION_KEYWORD_HIGHLIGHT_APPLIED backend=caption_service terms=%s",
                "|".join(line_keyword_terms[:2]),
            )
            keyword_highlight_logged = True
        if uppercase:
            words = [
                WordTimestamp(
                    w.text.upper(),
                    w.start,
                    w.end,
                    score=w.score,
                    emphasis=w.emphasis,
                )
                for w in words
            ]

        if beta_clean:
            assert preset is not None
            min_duration_s = float(polish.get("min_caption_duration") or preset["min_duration_s"])
            max_duration_s = float(polish.get("max_caption_duration") or preset["max_duration_s"])
            event_start = max(line.line_start, previous_end)
            if event_start > line.line_start:
                overlap_fixed += 1

            natural_end = max(line.line_end, words[-1].end if words else line.line_end)
            event_end = min(
                event_start + max_duration_s,
                max(natural_end, event_start + min_duration_s),
            )
            if event_end - event_start < min_duration_s:
                event_end = event_start + min_duration_s
                min_duration_applied += 1

            base_size = int(preset["font_size"])
            adjusted_size, size_reason = _adaptive_font_size(base_size, words)
            if size_reason:
                logger.info(
                    "VPI_CAPTION_ADAPTIVE_SIZE_APPLIED backend=caption_service old_size=%d new_size=%d reason=%s",
                    base_size,
                    adjusted_size,
                    size_reason,
                )
            text = _build_beta_clean_karaoke_text(
                words,
                pos_tag,
                str(preset["highlight_colour"]),
                adjusted_size,
                caption_polish_profile=polish,
            )
            normalized_text = _normalize_caption_text(text)
            if normalized_text == previous_text:
                dedupe_removed += 1
                logger.info(
                    "[caption-ass] duplicate text prev_i=%d i=%d",
                    len(events) - 1,
                    len(events),
                )
                continue

            if events and event_start < previous_end:
                logger.info(
                    "[caption-ass] overlap prev_i=%d i=%d prev_end=%.3f start=%.3f",
                    len(events) - 1,
                    len(events),
                    previous_end,
                    event_start,
                )

            logger.info(
                "[caption-sync] group_words=%d event_start=%.3f event_end=%.3f duration=%.3f",
                len(words),
                event_start,
                event_end,
                event_end - event_start,
            )
            logger.info(
                '[caption-ass] event i=%d start=%.3f end=%.3f text="%s"',
                len(events),
                event_start,
                event_end,
                normalized_text[:120],
            )
            events.append(
                f"Dialogue: 0,{_ass_time(event_start)},{_ass_time(event_end)},"
                f"Default,,0,0,0,,{text}"
            )
            previous_end = event_end
            previous_text = normalized_text
        elif is_highlight:
            # One event per word — each word gets the highlight box while active
            for i, w in enumerate(words):
                base_size = 68
                adjusted_size, size_reason = _adaptive_font_size(base_size, words)
                if size_reason:
                    logger.info(
                        "VPI_CAPTION_ADAPTIVE_SIZE_APPLIED backend=caption_service old_size=%d new_size=%d reason=%s",
                        base_size,
                        adjusted_size,
                        size_reason,
                    )
                text = _build_highlight_text(words, i, emphasis_threshold, caption_polish_profile=polish)
                text = f"{{\\fad(90,120)}}{{\\fs{adjusted_size}}}{text}"
                events.append(
                    f"Dialogue: 0,{_ass_time(w.start)},{_ass_time(w.end)},"
                    f"Default,,0,0,0,,{text}"
                )
        else:
            # Full line with \\k timing
            base_size = 72
            adjusted_size, size_reason = _adaptive_font_size(base_size, words)
            if size_reason:
                logger.info(
                    "VPI_CAPTION_ADAPTIVE_SIZE_APPLIED backend=caption_service old_size=%d new_size=%d reason=%s",
                    base_size,
                    adjusted_size,
                    size_reason,
                )
            text = f"{{\\fad(90,120)}}{{\\fs{adjusted_size}}}" + _build_karaoke_text(words, emphasis_threshold, caption_polish_profile=polish)
            events.append(
                f"Dialogue: 0,{_ass_time(line.line_start)},{_ass_time(line.line_end)},"
                f"Default,,0,0,0,,{text}"
            )

    if beta_clean:
        logger.info("[caption-sync] dedupe removed=%d", dedupe_removed)
        logger.info("[caption-sync] overlap_fixed=%d", overlap_fixed)
        logger.info("[caption-sync] min_duration_applied=%d", min_duration_applied)

    overlay_plan = overlay_plan or {}
    hook_overlay = overlay_plan.get("hook_overlay") or {}
    if hook_overlay.get("applied") and hook_overlay.get("text"):
        start = float(hook_overlay.get("start_s") or 0.05)
        end = start + float(hook_overlay.get("duration_s") or 1.1)
        text = str(hook_overlay.get("text") or "").replace("{", "").replace("}", "")
        events.append(
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},HookOverlay,,0,0,0,,"
            f"{{\\an8\\pos({play_res_x // 2},{int(play_res_y * 0.16)})\\fad(80,120)}}{text}"
        )
    lower = overlay_plan.get("lower_third") or {}
    if lower.get("applied") and lower.get("text"):
        start = float(lower.get("start_s") or 1.45)
        end = start + float(lower.get("duration_s") or 1.8)
        text = str(lower.get("text") or "").replace("{", "").replace("}", "")
        events.append(
            f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},LowerThird,,0,0,0,,"
            f"{{\\an1\\pos(54,{int(play_res_y * 0.66)})\\fad(100,160)}}{text}"
        )

    return header + "\n".join(events) + "\n"


# ── Caption line segmentation ─────────────────────────────────────────────────

# Sentence-ending punctuation triggers line breaks
_SENTENCE_ENDINGS = {".", "!", "?", "…"}


def segment_words_into_lines(
    words: List[Dict[str, Any]],
    max_words_per_line: int = 5,
    max_line_duration: float = 4.0,
    gap_threshold: float = 0.8,
    emphasis_threshold: float = 0.88,
    emphasis_indices: Optional[List[int]] = None,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
    protected_phrases: Optional[List[str]] = None,
) -> List[CaptionLine]:
    """
    Group word-level timestamps into caption lines suitable for display.

    Splits on:
      - Word gaps > gap_threshold seconds (sentence breaks)
      - Lines that would exceed max_words_per_line
      - Lines that would exceed max_line_duration seconds
      - Sentence-ending punctuation (., !, ?, …)

    Args:
        words: List of dicts with 'text', 'start', 'end', 'score' keys (Whisper format).
        max_words_per_line: Target max words per caption bubble.
        max_line_duration: Max display duration before forced split (seconds).
        gap_threshold: Gap between words (seconds) that triggers a line break.
        emphasis_threshold: Score threshold for auto-marking emphasis (default 0.88).
        emphasis_indices: Optional list of word indices from LangGraph to mark as emphasis.
        caption_polish_profile: Optional VPI polish profile with line/timing limits.
        protected_phrases: Optional phrase list that should not be split across lines.
    """
    if not words:
        return []

    wts = [
        WordTimestamp(
            text=re.sub(r"[^\w\s''-]", "", (w.get("text") or w.get("word") or "")).strip(),
            start=float(w.get("start", 0)),
            end=float(w.get("end", 0)),
            score=float(w.get("score", w.get("probability", 0.5))),
            emphasis=False,
        )
        for w in words
        if (w.get("text") or w.get("word") or "").strip()
    ]

    # Mark high-score words as emphasis (score >= threshold, default 0.88)
    for wt in wts:
        if wt.score >= emphasis_threshold:
            wt.emphasis = True

    # Mark words from LangGraph emphasis_indices as emphasis (positional override)
    if emphasis_indices:
        for idx in emphasis_indices:
            if 0 <= idx < len(wts):
                wts[idx].emphasis = True

    polish = caption_polish_profile if isinstance(caption_polish_profile, dict) else {}
    if polish:
        max_words_per_line = min(max_words_per_line, int(polish.get("max_words_per_caption") or max_words_per_line))
        max_line_duration = min(max_line_duration, float(polish.get("max_caption_duration") or max_line_duration))
        gap_threshold = min(gap_threshold, max(0.25, float(polish.get("gap_threshold_s") or gap_threshold)))
    min_caption_duration = float(polish.get("min_caption_duration") or 0.0)
    max_caption_duration = float(polish.get("max_caption_duration") or max_line_duration)
    max_chars_per_caption = int(polish.get("max_chars_per_caption") or 0)
    protected_phrase_tokens = _caption_phrase_tokens(protected_phrases)

    lines: List[CaptionLine] = []
    current: List[WordTimestamp] = []

    beta_clean = _is_beta_clean()
    if beta_clean:
        preset = _beta_clean_visual_preset()
        max_words_per_line = min(max_words_per_line, int(preset["max_words_per_block"]))
        max_line_duration = min(max_line_duration, float(preset["max_duration_s"]))
        gap_threshold = min(gap_threshold, float(preset["gap_threshold_s"]))

    for i, wt in enumerate(wts):
        force_break = False
        if current:
            gap = wt.start - current[-1].end
            dur = wt.end - current[0].start
            last_text = current[-1].text.rstrip()
            current_chars = sum(len(str(item.text or "").strip()) for item in current) + max(0, len(current) - 1)
            next_chars = current_chars + (1 if current else 0) + len(str(wt.text or "").strip())
            # Break on sentence endings, gaps, max words, or max duration
            ends_sentence = any(last_text.endswith(p) for p in _SENTENCE_ENDINGS)
            if (
                ends_sentence
                or gap > gap_threshold
                or len(current) >= max_words_per_line
                or dur > max_line_duration
                or (max_chars_per_caption > 0 and next_chars > max_chars_per_caption)
            ):
                next_token = _caption_polish_token(wt.text)
                current_tokens = _caption_word_tokens(current)
                if _caption_tail_forms_protected_phrase(current_tokens, next_token, protected_phrase_tokens):
                    force_break = False
                else:
                    force_break = True

        if force_break and current:
            line_end = current[-1].end if beta_clean else current[-1].end + 0.15
            if min_caption_duration > 0:
                line_end = max(line_end, current[0].start + min_caption_duration)
            if beta_clean:
                line_end = min(line_end, current[0].start + max_caption_duration)
            lines.append(CaptionLine(
                words=current,
                line_start=current[0].start,
                line_end=line_end,
            ))
            current = []

        current.append(wt)

    if current:
        line_end = current[-1].end + (0.08 if beta_clean else 0.15)
        if min_caption_duration > 0:
            line_end = max(line_end, current[0].start + min_caption_duration)
        if beta_clean:
            line_end = min(line_end, current[0].start + max_caption_duration)
        lines.append(CaptionLine(
            words=current,
            line_start=current[0].start,
            line_end=line_end,
        ))

    # Merge single-word orphan lines when a safe combination exists.
    if len(lines) > 1:
        merged_lines: List[CaptionLine] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if (
                len(line.words) == 1
                and merged_lines
                and len(merged_lines[-1].words) < max_words_per_line
            ):
                prev = merged_lines[-1]
                combined_words = prev.words + line.words
                combined_duration = float(line.line_end - prev.line_start)
                if combined_duration <= max_caption_duration * 1.15:
                    merged_lines[-1] = CaptionLine(
                        words=combined_words,
                        line_start=prev.line_start,
                        line_end=max(prev.line_end, line.line_end),
                    )
                    i += 1
                    continue
            merged_lines.append(line)
            i += 1
        lines = merged_lines

    return lines


def _highlight_indices_for_terms(words: List[Dict[str, Any]], terms: List[str]) -> List[int]:
    normalized_terms = [str(term).lower() for term in terms if str(term).strip()]
    indices: set[int] = set()
    if not normalized_terms:
        return []
    word_texts = [
        re.sub(r"[^\w\s'-]", "", (w.get("text") or w.get("word") or "")).strip().lower()
        for w in words
    ]
    for term in normalized_terms:
        parts = term.split()
        if not parts:
            continue
        for idx in range(0, len(word_texts) - len(parts) + 1):
            if word_texts[idx : idx + len(parts)] == parts:
                indices.update(range(idx, idx + len(parts)))
    return sorted(indices)


_STRONG_PHRASE_PRIORITY = [
    "no es solo",
    "dependen de ti",
    "mas adelante",
    "más adelante",
    "personas mayores",
    "seguro de vida",
    "responsabilidad",
    "proteger",
    "proteccion",
    "protección",
]


def _select_editorial_highlights(
    words: List[Dict[str, Any]],
    terms: List[str],
    editorial_type: str = "",
    hook_first3_status: str = "",
    hook_first3_score: int = 0,
) -> tuple[List[int], List[Dict[str, Any]]]:
    """Select a restrained set of VPI highlight indices.

    v4.0 retention: when hook_first3_status is READY and score >= 5,
    ensures emphasis words appear in the first 3 seconds of subtitles
    for visual reinforcement of the hook.

    The ASS renderer only knows emphasized words, so strong/medium levels are
    stored in metadata/logs while the visual output stays deliberately sober.
    """
    if editorial_type == "weak_intro":
        logger.info("[subtitle-intelligence] skipped reason=weak_intro")
        return [], []

    base_lines = segment_words_into_lines(words, max_words_per_line=5, emphasis_indices=[])
    if not base_lines:
        return [], []

    word_lookup = [
        re.sub(r"[^\w\s'-]", "", (w.get("text") or w.get("word") or "")).strip().lower()
        for w in words
    ]
    normalized_terms = []
    for term in terms:
        raw = str(term).strip()
        if not raw:
            continue
        normalized_terms.append((raw, raw.lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")))

    candidates: List[Dict[str, Any]] = []
    for raw, norm in normalized_terms:
        parts = norm.split()
        if not parts:
            continue
        priority = _STRONG_PHRASE_PRIORITY.index(raw.lower()) if raw.lower() in _STRONG_PHRASE_PRIORITY else 99
        level = "strong" if priority <= 5 or len(parts) > 1 else "medium"
        for idx in range(0, len(word_lookup) - len(parts) + 1):
            window = [
                token.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
                for token in word_lookup[idx : idx + len(parts)]
            ]
            if window == parts:
                candidates.append({
                    "term": raw,
                    "indices": list(range(idx, idx + len(parts))),
                    "start_idx": idx,
                    "priority": priority,
                    "level": level,
                })

    if not candidates:
        return [], []

    selected: List[Dict[str, Any]] = []
    selected_indices: set[int] = set()
    previous_line_idx = -10
    # Track timestamps for 4s window density check
    highlight_timestamps: List[float] = []
    for line_idx, line in enumerate(base_lines):
        line_indices = set()
        cursor = 0
        for line_word in line.words:
            target = line_word.text.lower()
            while cursor < len(word_lookup):
                if word_lookup[cursor] == target:
                    line_indices.add(cursor)
                    cursor += 1
                    break
                cursor += 1
        line_candidates = [
            item for item in candidates
            if set(item["indices"]).issubset(line_indices)
        ]
        if not line_candidates:
            continue
        if line_idx - previous_line_idx < 1:
            logger.info("[subtitle-intelligence] skipped reason=too_many_highlights line=%s", line_idx)
            continue
        line_candidates.sort(key=lambda item: (item["priority"], item["start_idx"]))
        strong_used = False
        per_line = 0
        for item in line_candidates:
            # v3.2: max 1 strong highlight per line
            if per_line >= 1:
                logger.info("[subtitle-intelligence] skipped reason=too_many_highlights line=%s", line_idx)
                break
            level = item["level"]
            if level == "strong" and strong_used:
                level = "medium"
            if level == "strong":
                strong_used = True
            # v3.2: max 2 highlight terms in any 4s window
            line_mid_ts = (line.line_start + line.line_end) / 2
            highlight_timestamps.append(line_mid_ts)
            # Prune timestamps older than 4s
            highlight_timestamps = [t for t in highlight_timestamps if line_mid_ts - t <= 4.0]
            if len(highlight_timestamps) > 2:
                logger.info(
                    "[subtitle-intelligence] skipped reason=density_4s_window line=%s count=%d",
                    line_idx, len(highlight_timestamps),
                )
                highlight_timestamps.pop()
                continue
            selected.append({"line": line_idx, "term": item["term"], "level": level, "reason": "editorial_priority"})
            selected_indices.update(item["indices"])
            logger.info(
                "[subtitle-intelligence] line=%s highlighted=%s level=%s reason=editorial_priority",
                line_idx,
                item["term"],
                level,
            )
            per_line += 1
        previous_line_idx = line_idx
    return sorted(selected_indices), selected


# ── FFmpeg burn-in ────────────────────────────────────────────────────────────

async def _run_ffmpeg_caption(
    ffmpeg_exe: str,
    video_path: Path,
    vf: str,
    output_path: Path,
) -> bool:
    """
    Try NVENC first, fall back to libx264 on ANY failure.

    Some FFmpeg builds don't recognise the ``-rc`` option used with NVENC
    (``-rc constqp -qp 20``), producing *"Unrecognized option 'rc'"* instead
    of an NVENC-specific error.  The old code only retried when stderr
    contained ``nvenc`` or ``h264_nvenc``, missing this case.

    Fix: if the first attempt (NVENC) fails for *any* reason, log the
    failure and retry with safe libx264 options.  If libx264 also fails,
    log and return False.
    """
    nvenc_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-qp", "20"]
    libx264_args = ["-c:v", "libx264", "-preset", "fast", "-crf", "20"]

    # ── Beta-clean OR NVENC disabled: skip NVENC, go straight to libx264 ─
    _beta_clean = os.environ.get("VIRACLIP_BETA_CLEAN", "").lower() in ("1", "true", "yes")
    _enable_nvenc = os.environ.get("VIRACLIP_ENABLE_NVENC", "false").lower() in ("1", "true", "yes")
    if _beta_clean or not _enable_nvenc:
        reason = "beta-clean" if _beta_clean else "VIRACLIP_ENABLE_NVENC=false"
        logger.info(
            "[caption] Caption burn using libx264 (%s)", reason
        )
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            *libx264_args,
            "-c:a", "copy",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode == 0:
            logger.info("[caption] libx264 caption burn succeeded for %s", output_path.name)
            return True
        _err = stderr.decode("utf-8", errors="replace")[-500:]
        logger.error(
            "[caption] libx264 caption burn failed (exit %d): %s",
            proc.returncode, _err,
        )
        return False

    try:
        from ..utils.gpu_utils import is_ffmpeg_nvenc_runtime_available
        _nvenc_available = is_ffmpeg_nvenc_runtime_available()
    except Exception as exc:
        logger.debug("[caption] NVENC runtime probe unavailable: %s", exc)
        _nvenc_available = False

    logger.info("[gpu] ffmpeg nvenc runtime available=%s", str(_nvenc_available).lower())
    if not _nvenc_available:
        logger.info("[caption] Caption burn using libx264 (NVENC runtime unavailable)")
        proc = await asyncio.create_subprocess_exec(
            ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            *libx264_args,
            "-c:a", "copy",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode == 0:
            logger.info("[caption] libx264 caption burn succeeded for %s", output_path.name)
            return True
        _err = stderr.decode("utf-8", errors="replace")[-500:]
        logger.error(
            "[caption] libx264 caption burn failed (exit %d): %s",
            proc.returncode, _err,
        )
        return False

    # ── Attempt 1: NVENC ────────────────────────────────────────────────
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        *nvenc_args,
        "-c:a", "copy",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
    if proc.returncode == 0:
        return True

    # NVENC failed — log and fall through to libx264
    _err = stderr.decode("utf-8", errors="replace")[-500:]
    logger.warning("[gpu] NVENC failed; retrying with libx264")
    logger.warning("[caption] NVENC caption burn failed (exit %d): %s", proc.returncode, _err)

    # ── Attempt 2: libx264 (safe fallback) ──────────────────────────────
    proc = await asyncio.create_subprocess_exec(
        ffmpeg_exe, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        *libx264_args,
        "-c:a", "copy",
        str(output_path),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
    if proc.returncode == 0:
        logger.info("[caption] libx264 caption burn succeeded for %s", output_path.name)
        return True

    _err2 = stderr.decode("utf-8", errors="replace")[-500:]
    logger.error(
        "[caption] libx264 caption burn failed (exit %d): %s",
        proc.returncode, _err2,
    )
    return False


async def burn_captions(
    video_path: Path,
    output_path: Path,
    words: List[Dict[str, Any]],
    style: str = "tiktok",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    max_words_per_line: int = 5,
    font_dir: Optional[str] = None,
    platform: str = "tiktok",
    caption_decisions: Optional[Dict[str, Any]] = None,
    emphasis_threshold: float = 0.82,
) -> bool:
    """
    Generate an ASS file from word timestamps and burn it into the video
    using FFmpeg's `subtitles` filter (libass rendering).

    Args:
        caption_decisions: Optional dict from LangGraph with keys like
            'emphasis_indices' for positional emphasis override.
        emphasis_threshold: Score threshold for marking words as emphasis (default 0.82).

    Returns True on success, False on failure (video is still written as-is).
    """
    # Extract emphasis indices from LangGraph/VPI decisions (positional override)
    caption_decisions = caption_decisions or {}
    daily_mode = str(os.environ.get("VPI_DAILY_MODE", "")).strip().lower() in {"1", "true", "yes", "on"}
    clip_duration_hint = float(caption_decisions.get("clip_duration") or 0.0)
    words = _normalize_caption_word_items(words, clip_duration_hint)
    logger.info("VPI_CAPTION_WORD_ITEMS_NORMALIZED count=%d clip_duration=%.2f", len(words), clip_duration_hint)
    visual_tokens = get_vpi_visual_design_tokens()
    caption_decisions["visual_design_version"] = str(visual_tokens.get("visual_design_version") or "a1")
    caption_decisions["visual_design_tokens_applied"] = True
    caption_decisions["visual_design_tokens_applied_to_captions"] = True
    logger.info(
        "VPI_VISUAL_TOKENS_APPLIED backend=caption_service visual_design_version=%s",
        caption_decisions["visual_design_version"],
    )
    emphasis_indices = caption_decisions.get("emphasis_indices")
    highlighted_terms = list(caption_decisions.get("highlighted_terms") or [])
    hook_emphasis_words = list(caption_decisions.get("hook_emphasis_words") or [])
    hook_subtitle_text = str(caption_decisions.get("hook_subtitle_text") or "")
    segment_text = str(caption_decisions.get("segment_text") or " ".join(str(w.get("word") or w.get("text") or "") for w in words))
    editorial_type = str(caption_decisions.get("editorial_type") or "")
    hook_intent = str(caption_decisions.get("hook_intent") or "")
    composition_decision = caption_decisions.get("composition_decision") if isinstance(caption_decisions.get("composition_decision"), dict) else {}
    hook_first3_status = str(caption_decisions.get("hook_first3_status") or "")
    hook_first3_score = int(caption_decisions.get("hook_first3_score") or 0)
    rendered_highlights = False
    overlay_plan = plan_caption_overlay_pack(
        segment_text,
        hook_intent=hook_intent,
        editorial_type=editorial_type,
        words=words,
        subtitle_already_strong=bool(caption_decisions.get("hook_caption_applied")),
        composition_decision=composition_decision,
        enable_lower_third=not daily_mode,
        global_visual_layer_budget=caption_decisions.get("global_visual_layer_budget") if isinstance(caption_decisions, dict) else None,
    )
    caption_decisions["caption_overlay_pack"] = overlay_plan
    caption_decisions["visual_design_version"] = str(overlay_plan.get("visual_design_version") or caption_decisions.get("visual_design_version") or "a1")
    caption_decisions["visual_design_tokens_applied"] = bool(overlay_plan.get("visual_design_tokens_applied", True))
    caption_decisions["visual_design_tokens_applied_to_captions"] = True
    caption_overlay_terms = list(overlay_plan.get("keyword_emphasis_terms") or [])
    combined_terms = hook_emphasis_words + highlighted_terms + caption_overlay_terms
    safe_zone_context = {
        "face_bbox": caption_decisions.get("face_bbox"),
        "speaker_bbox": caption_decisions.get("speaker_bbox"),
        "bbox": caption_decisions.get("bbox"),
    }
    # v3.2 metadata
    captions_highlight_count = 0
    hook_caption_applied = False
    caption_density_warning = False
    # v4.0 retention: first-3-seconds subtitle reinforcement
    hook_first3_reinforced = False
    if combined_terms:
        term_indices, highlight_decisions = _select_editorial_highlights(words, combined_terms, editorial_type)
        caption_decisions["highlight_decisions"] = highlight_decisions
        captions_highlight_count = len(highlight_decisions)
        if term_indices:
            emphasis_indices = sorted(set(emphasis_indices or []) | set(term_indices))
            rendered_highlights = True
        hook_indices = _highlight_indices_for_terms(words, hook_emphasis_words)
        if hook_indices:
            hook_caption_applied = True
            logger.info("[hook-subtitle] applied=true text=%s", hook_subtitle_text or "|".join(hook_emphasis_words[:2]))
        elif hook_subtitle_text:
            if rendered_highlights:
                logger.info("[hook-subtitle] fallback_words=%s", "|".join(hook_emphasis_words[:3]))
            else:
                logger.info("[hook-subtitle] metadata_only reason=headline_not_in_transcript text=%s", hook_subtitle_text)
        logger.info(
            "[subtitle-intelligence] highlighted=%s rendered=%s reason=%s",
            "|".join(combined_terms[:12]),
            str(rendered_highlights).lower(),
            "emphasis_indices" if rendered_highlights else "terms_not_found",
        )
        # v3.2: density warning if > 2 highlights in 4s window
        if captions_highlight_count > 2:
            caption_density_warning = True
            logger.info("[subtitle-intelligence] caption_density_warning=true count=%d", captions_highlight_count)
    elif str(caption_decisions.get("hook_type") or "") == "weak_intro":
        logger.info("[hook-subtitle] skipped reason=weak_intro")
        logger.info("[subtitle-intelligence] highlighted= rendered=false reason=weak_intro")
    else:
        logger.info("[subtitle-intelligence] highlighted= rendered=false reason=no_terms")
    # Store v3.2 metadata in caption_decisions
    caption_decisions["captions_highlight_count"] = captions_highlight_count
    caption_decisions["hook_caption_applied"] = hook_caption_applied
    caption_decisions["caption_density_warning"] = caption_density_warning
    words, caption_timebase_corrected, caption_timebase_source, caption_sync_warning = _normalize_caption_words_to_clip_timebase(
        words,
        clip_duration_hint,
    )
    if caption_timebase_corrected:
        logger.info(
            "VPI_CAPTION_TIMEBASE_CORRECTED source=%s warning=%s",
            caption_timebase_source,
            caption_sync_warning or "none",
        )
    else:
        logger.info(
            "VPI_ASS_TIMING_APPROX_SIMPLE_MODE source=%s warning=%s",
            caption_timebase_source,
            caption_sync_warning or "none",
        )
    logger.info(
        "VPI_CAPTION_TIMEBASE_LOCALIZED_FALLBACK source=%s warning=%s",
        caption_timebase_source,
        caption_sync_warning or "none",
    )
    caption_decisions["caption_timebase_corrected"] = bool(caption_timebase_corrected)
    caption_decisions["caption_timebase_source"] = caption_timebase_source
    caption_decisions["caption_sync_warning"] = caption_sync_warning
    # v4.0 retention: first-3-seconds subtitle reinforcement
    # When hook_first3_status is READY and score >= 5, ensure the first
    # subtitle line has emphasis words for visual reinforcement of the hook.
    if hook_first3_status == "READY" and hook_first3_score >= 5:
        hook_first3_reinforced = True
        logger.info(
            "[hook-first3] subtitle_reinforcement=true status=%s score=%d",
            hook_first3_status, hook_first3_score,
        )
        # Ensure hook_emphasis_words are included in emphasis_indices
        if hook_emphasis_words and not hook_indices:
            hook_indices = _highlight_indices_for_terms(words, hook_emphasis_words)
            if hook_indices:
                emphasis_indices = sorted(set(emphasis_indices or []) | set(hook_indices))
                logger.info(
                    "[hook-first3] emphasis_indices_reinforced=%s",
                    hook_indices,
                )
        # If hook_subtitle_text is set but not found in transcript, log it
        if hook_subtitle_text and not hook_indices:
            logger.info(
                "[hook-first3] hook_text_not_in_transcript text=%s",
                hook_subtitle_text,
            )
    caption_decisions["hook_first3_reinforced"] = hook_first3_reinforced
    clip_duration_hint = float(words[-1].get("end", 0.0) if words else 0.0)
    caption_density_hint = float(len(words) / max(1.0, clip_duration_hint or 1.0))
    caption_polish_profile = choose_vpi_caption_polish_profile(
        editorial_type=editorial_type,
        clip_duration=clip_duration_hint,
        caption_density=caption_density_hint,
        hook_strategy_final=hook_intent or hook_first3_status,
        premium_restraint_mode=str(caption_decisions.get("premium_restraint_mode") or ""),
        visual_layout_strategy=str(caption_decisions.get("visual_layout_strategy") or ""),
        broll_timing_strategy=str(caption_decisions.get("broll_timing_strategy") or ""),
        cta_decision=str(caption_decisions.get("cta_decision") or ""),
        sensitive_topic=bool(editorial_type == "decesos" or "decesos" in segment_text.lower()),
        words_with_timestamps=words,
    )
    if not caption_timebase_corrected:
        simple_profile = dict(caption_polish_profile or {})
        simple_profile["caption_polish_profile"] = "standard_clean"
        simple_profile["caption_pacing_reason"] = ",".join(
            [part for part in [
                str(simple_profile.get("caption_pacing_reason") or ""),
                "timebase_approx_simple_mode",
            ] if part]
        )
        simple_profile["max_words_per_caption"] = min(int(simple_profile.get("max_words_per_caption") or 5), 5)
        simple_profile["max_caption_duration"] = min(float(simple_profile.get("max_caption_duration") or 2.2), 2.2)
        simple_profile["max_chars_per_caption"] = min(int(simple_profile.get("max_chars_per_caption") or 30), 28)
        caption_polish_profile = simple_profile
    if int(caption_polish_profile.get("max_chars_per_caption") or 0) > 0:
        logger.info(
            "VPI_ASS_CAPTION_DENSITY_REDUCED profile=%s max_words=%d max_chars=%d max_dur=%.2f",
            str(caption_polish_profile.get("caption_polish_profile") or "standard_clean"),
            int(caption_polish_profile.get("max_words_per_caption") or 5),
            int(caption_polish_profile.get("max_chars_per_caption") or 0),
            float(caption_polish_profile.get("max_caption_duration") or 0.0),
        )
    lines = segment_words_into_lines(
        words,
        max_words_per_line=max_words_per_line,
        emphasis_indices=emphasis_indices,
        caption_polish_profile=caption_polish_profile,
    )
    line_durations = [float(line.line_end - line.line_start) for line in lines]
    min_caption_duration = float(caption_polish_profile.get("min_caption_duration") or 0.0)
    max_caption_duration = float(caption_polish_profile.get("max_caption_duration") or 0.0)
    caption_linebreak_polish_applied = bool(
        lines
        and (
            len(lines) != max(1, (len(words) + (int(caption_polish_profile.get("max_words_per_caption") or 5) - 1)) // int(caption_polish_profile.get("max_words_per_caption") or 5))
            or any(len(line.words) == 1 for line in lines)
            or any(_caption_tail_forms_protected_phrase(_caption_word_tokens(line.words[:-1]), _caption_polish_token(line.words[-1].text), _caption_phrase_tokens()) for line in lines if len(line.words) > 1)
        )
    )
    caption_orphan_words_avoided = not any(len(line.words) == 1 for line in lines)
    caption_protected_phrases_preserved = bool(
        lines
        and any(
            any(
                phrase in _caption_polish_token(line.full_text)
                for phrase in (_caption_polish_token(p) for p in _CAPTION_PROTECTED_PHRASES)
            )
            for line in lines
        )
    )
    caption_timing_polish_applied = bool(min_caption_duration or max_caption_duration)
    caption_too_fast_adjusted = bool(min_caption_duration and any(duration <= (min_caption_duration + 0.03) for duration in line_durations))
    caption_duration_balance_ok = bool(
        lines
        and all(
            duration >= max(0.50, min_caption_duration - 0.05)
            and (not max_caption_duration or duration <= max_caption_duration * 1.2)
            for duration in line_durations
        )
    )
    caption_keyword_highlight_count = max(captions_highlight_count, len([term for term in caption_overlay_terms if term]))
    caption_highlight_policy = str(caption_polish_profile.get("caption_highlight_policy") or "single_keyword_sober")
    caption_hook_conflict_avoided = bool(hook_caption_applied or not hook_text or caption_density_warning)
    caption_cta_conflict_avoided = bool(str(caption_decisions.get("cta_decision") or "") != "show_cta" or caption_polish_profile.get("caption_polish_profile") != "dense_explainer")
    caption_broll_conflict_avoided = bool(str(caption_decisions.get("broll_timing_strategy") or "") in {"", "no_broll"} or caption_polish_profile.get("caption_polish_profile") in {"calm_readable", "sensitive_soft"})
    caption_visual_conflict_avoided = bool(caption_hook_conflict_avoided or caption_cta_conflict_avoided or caption_broll_conflict_avoided)
    caption_priority_enforced = bool(daily_mode or caption_density_warning or hook_caption_applied or caption_visual_conflict_avoided)
    hook_text_active = bool(hook_caption_applied or hook_subtitle_text or caption_decisions.get("hook_text"))
    lower_third_active = bool(lower_third.get("applied") and lower_third_text)
    suppressed_text_layers = list(
        dict.fromkeys(
            [
                "hook_overlay" if hook_text_active and (daily_mode or caption_density_warning or caption_visual_conflict_avoided) else "",
                "lower_third" if lower_third_active and (daily_mode or caption_density_warning or hook_text_active or caption_visual_conflict_avoided) else "",
            ]
        )
    )
    text_layer_count_final = int(1 + int(bool(hook_text_active and "hook_overlay" not in suppressed_text_layers)) + int(bool(lower_third_active and "lower_third" not in suppressed_text_layers)))
    if caption_priority_enforced and text_layer_count_final > 2:
        text_layer_count_final = 2
    caption_decisions.update({
        "caption_polish_profile": str(caption_polish_profile.get("caption_polish_profile") or "standard_clean"),
        "caption_pacing_reason": str(caption_polish_profile.get("caption_pacing_reason") or ""),
        "caption_polish_applied": bool(caption_polish_profile.get("caption_polish_applied", True)),
        "caption_polish_partial": False,
        "caption_linebreak_polish_applied": bool(caption_linebreak_polish_applied),
        "caption_orphan_words_avoided": bool(caption_orphan_words_avoided),
        "caption_protected_phrases_preserved": bool(caption_protected_phrases_preserved),
        "caption_timing_polish_applied": bool(caption_timing_polish_applied),
        "caption_too_fast_adjusted": bool(caption_too_fast_adjusted),
        "caption_duration_balance_ok": bool(caption_duration_balance_ok),
        "caption_keyword_highlight_count": int(caption_keyword_highlight_count),
        "caption_highlight_policy": caption_highlight_policy,
        "caption_hook_conflict_avoided": bool(caption_hook_conflict_avoided),
        "caption_cta_conflict_avoided": bool(caption_cta_conflict_avoided),
        "caption_broll_conflict_avoided": bool(caption_broll_conflict_avoided),
        "caption_visual_conflict_avoided": bool(caption_visual_conflict_avoided),
        "caption_priority_enforced": bool(caption_priority_enforced),
        "text_overlap_prevented": bool(caption_visual_conflict_avoided or caption_priority_enforced or text_layer_count_final <= 2),
        "suppressed_text_layers": suppressed_text_layers,
        "text_layer_count_final": int(text_layer_count_final),
    })
    overlay_plan.update({
        "caption_polish_profile": caption_decisions["caption_polish_profile"],
        "caption_pacing_reason": caption_decisions["caption_pacing_reason"],
        "caption_polish_applied": caption_decisions["caption_polish_applied"],
        "caption_polish_partial": caption_decisions["caption_polish_partial"],
        "caption_linebreak_polish_applied": caption_decisions["caption_linebreak_polish_applied"],
        "caption_orphan_words_avoided": caption_decisions["caption_orphan_words_avoided"],
        "caption_protected_phrases_preserved": caption_decisions["caption_protected_phrases_preserved"],
        "caption_timing_polish_applied": caption_decisions["caption_timing_polish_applied"],
        "caption_too_fast_adjusted": caption_decisions["caption_too_fast_adjusted"],
        "caption_duration_balance_ok": caption_decisions["caption_duration_balance_ok"],
        "caption_keyword_highlight_count": caption_decisions["caption_keyword_highlight_count"],
        "caption_highlight_policy": caption_decisions["caption_highlight_policy"],
        "caption_hook_conflict_avoided": caption_decisions["caption_hook_conflict_avoided"],
        "caption_cta_conflict_avoided": caption_decisions["caption_cta_conflict_avoided"],
        "caption_broll_conflict_avoided": caption_decisions["caption_broll_conflict_avoided"],
        "caption_visual_conflict_avoided": caption_decisions["caption_visual_conflict_avoided"],
    })
    if caption_linebreak_polish_applied:
        logger.info(
            "VPI_CAPTION_LINEBREAK_POLISHED profile=%s protected=%s orphan_avoided=%s",
            caption_decisions["caption_polish_profile"],
            str(caption_protected_phrases_preserved).lower(),
            str(caption_orphan_words_avoided).lower(),
        )
    if caption_timing_polish_applied:
        logger.info(
            "VPI_CAPTION_TIMING_POLISHED profile=%s min=%.2f max=%.2f fast_adjusted=%s",
            caption_decisions["caption_polish_profile"],
            min_caption_duration,
            max_caption_duration,
            str(caption_too_fast_adjusted).lower(),
        )
    if caption_keyword_highlight_count:
        logger.info(
            "VPI_CAPTION_HIGHLIGHT_APPLIED count=%d policy=%s",
            caption_keyword_highlight_count,
            caption_highlight_policy,
        )
    if caption_visual_conflict_avoided:
        logger.info(
            "VPI_CAPTION_VISUAL_CONFLICT_AVOIDED hook=%s cta=%s broll=%s",
            str(caption_hook_conflict_avoided).lower(),
            str(caption_cta_conflict_avoided).lower(),
            str(caption_broll_conflict_avoided).lower(),
        )
    if not caption_duration_balance_ok or not caption_orphan_words_avoided or not caption_protected_phrases_preserved:
        logger.warning(
            "VPI_CAPTION_POLISH_WARNING profile=%s duration_ok=%s orphan_ok=%s protected_ok=%s",
            caption_decisions["caption_polish_profile"],
            str(caption_duration_balance_ok).lower(),
            str(caption_orphan_words_avoided).lower(),
            str(caption_protected_phrases_preserved).lower(),
        )

    if not lines:
        logger.warning("[caption] No words provided — skipping caption burn-in")
        return False

    ass_content = build_ass_script(
        lines, style=style, play_res_x=play_res_x, play_res_y=play_res_y,
        platform=platform, emphasis_threshold=emphasis_threshold,
        overlay_plan=overlay_plan,
        safe_zone_context=safe_zone_context,
        caption_polish_profile=caption_polish_profile,
    )
    if _is_beta_clean():
        logger.info("[caption-sync] source=cached_words words=%d lines=%d", len(words), len(lines))

    # ── Subtitle QA: speed guard + emoji injection + profanity filter ──────────
    try:
        from ..video_processing.subtitle_qa import run_subtitle_qa as _run_qa
        _qa_result = _run_qa(
            ass_content,
            apply_fixes=not _is_beta_clean(),
            add_emojis=not _is_beta_clean(),
            censor_profanity=False,
        )
        if _qa_result.fixed_content:
            ass_content = _qa_result.fixed_content
        if _qa_result.issues:
            logger.debug("[caption] subtitle_qa issues: %s", _qa_result.issues)
    except Exception as _qa_e:
        logger.warning("[caption] subtitle_qa skipped (no QA applied): %s", _qa_e)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ass", delete=False, encoding="utf-8"
    ) as f:
        f.write(ass_content)
        ass_path = f.name

    if _is_beta_clean():
        try:
            debug_dir = Path(os.environ.get("CAPTION_DEBUG_DIR", "/app/temp/caption_debug"))
            debug_dir.mkdir(parents=True, exist_ok=True)
            debug_path = debug_dir / f"{output_path.stem}.ass"
            debug_path.write_text(ass_content, encoding="utf-8")
            logger.info("[caption-debug] ass_path=%s", debug_path)
        except Exception as debug_exc:
            logger.debug("[caption-debug] failed to preserve ASS: %s", debug_exc)

    try:
        # Escape path for FFmpeg filter string (colons must be escaped on Linux)
        safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
        font_clause = f":fontsdir={font_dir}" if font_dir else ""
        vf = f"subtitles='{safe_ass}'{font_clause}"

        success = await _run_ffmpeg_caption(_get_ffmpeg_exe(), video_path, vf, output_path)
        if not success:
            return False

        logger.info("[caption] Burned %d lines (%s style) → %s",
                    len(lines), style, output_path.name)
        return True

    except (asyncio.TimeoutError, Exception) as exc:
        logger.error("[caption] burn_captions error: %s", exc)
        return False
    finally:
        try:
            Path(ass_path).unlink(missing_ok=True)
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

class CaptionService:
    """Unified interface for ASS caption generation and burn-in."""

    STYLES = list(_STYLE_DEFS.keys())

    @staticmethod
    def style_for_template(template_name: str, platform: str = "tiktok") -> str:
        """Auto-select the best caption style for a given render template + platform."""
        return _TEMPLATE_STYLE_MAP.get(template_name, "tiktok")

    async def burn(
        self,
        video_path: Path,
        output_path: Path,
        words: List[Dict[str, Any]],
        style: str = "tiktok",
        font_dir: Optional[str] = None,
        platform: str = "tiktok",
        caption_decisions: Optional[Dict[str, Any]] = None,
        emphasis_threshold: float = 0.82,
    ) -> bool:
        return await burn_captions(
            video_path, output_path, words,
            style=style, font_dir=font_dir, platform=platform,
            caption_decisions=caption_decisions, emphasis_threshold=emphasis_threshold,
        )

    def generate_ass(
        self,
        words: List[Dict[str, Any]],
        style: str = "tiktok",
        play_res_x: int = 1080,
        play_res_y: int = 1920,
        platform: str = "tiktok",
        emphasis_threshold: float = 0.82,
    ) -> str:
        """Return the raw ASS script string (for preview or saving)."""
        lines = segment_words_into_lines(words)
        return build_ass_script(lines, style=style,
                                play_res_x=play_res_x, play_res_y=play_res_y,
                                platform=platform, emphasis_threshold=emphasis_threshold)

    def segment_words(
        self,
        words: List[Dict[str, Any]],
        max_words_per_line: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return segmented caption lines as serialisable dicts."""
        lines = segment_words_into_lines(words, max_words_per_line=max_words_per_line)
        return [
            {
                "words": [{"text": w.text, "start": w.start, "end": w.end, "score": w.score}
                           for w in line.words],
                "start": line.line_start,
                "end": line.line_end,
                "text": line.full_text,
            }
            for line in lines
        ]

    def get_styles(self) -> List[str]:
        return self.STYLES


_instance: Optional[CaptionService] = None


def get_caption_service() -> CaptionService:
    global _instance
    if _instance is None:
        _instance = CaptionService()
    return _instance
