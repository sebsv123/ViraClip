"""
vpi_ass_caption_service.py — ASS caption plan generator for ViraClipTimelinePlan.

Generates a per-clip ASSCaptionPlan that describes how captions should be
rendered via FFmpeg/libass.  This is a *planning* module — it does NOT
render anything.  Downstream services (caption_service, overlay_renderer)
consume the plan to produce the final .ass file and burn it into video.

Design
------
- Pure data: no FFmpeg, no file I/O.
- Consumes word timestamps and visual-style metadata.
- Produces an ASSCaptionPlan with style definitions, dialogue events,
  and per-word karaoke/highlight metadata.
- Compatible with ViraClipTimelinePlan (CAPTION_TEXT, CAPTION_BG tracks).

Integration
-----------
- caption_service.py: consumes ASSCaptionPlan → build_ass_script()
- vpi_timeline_plan.py: CAPTION_TEXT track items → ASS dialogue events
- vpi_retention_editing_service.py: caption_decisions → ASSCaptionPlan
"""

from __future__ import annotations

import dataclasses
import os
import logging
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from .vpi_production_safe_edit import production_safe_edit_enabled
from .vpi_visual_effects_service import choose_vpi_caption_polish_profile, get_vpi_visual_design_tokens

logger = logging.getLogger(__name__)


# ── ASS colour helpers ──────────────────────────────────────────────────────────

def ass_colour(r: int, g: int, b: int, a: int = 0) -> str:
    """ASS &HAABBGGRR colour (little-endian channel order)."""
    return f"&H{a:02X}{b:02X}{g:02X}{r:02X}"


# Pre-built palette
ASS_WHITE = ass_colour(255, 255, 255)
ASS_SOFT_WHITE = ass_colour(245, 245, 245)
ASS_BLACK = ass_colour(0, 0, 0)
ASS_YELLOW = ass_colour(255, 255, 0)
ASS_CYAN = ass_colour(0, 255, 255)
ASS_RED = ass_colour(255, 50, 50)
ASS_VPI_ORANGE = ass_colour(255, 122, 24)
ASS_TRANSP = "&H00000000"
ASS_SEMI_BG = "&HAA000000"

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


def _normalize_caption_words_to_clip_timebase(
    words: List[Dict[str, Any]],
    clip_duration: float,
) -> Tuple[List[Dict[str, Any]], bool, str, str]:
    """Return words shifted to clip-relative time when timestamps look absolute."""
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
        starts.append(start)
        ends.append(end)
        normalized.append(dict(raw))
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


# ── ASS caption style ──────────────────────────────────────────────────────────


class ASSCaptionStyle(Enum):
    """ASS caption style presets."""
    KARAOKE = "karaoke"           # Word-by-word colour flip via \\k tags
    HIGHLIGHT = "highlight"       # Opaque coloured box behind active word
    TIKTOK = "tiktok"             # Large bold centred caps, drop shadow
    MINIMAL = "minimal"           # Small white text, thin black outline
    NEON = "neon"                 # Glowing cyan text on dark transparent bg
    VPI_CLEAN = "vpi_clean"       # Beta Clean default — white premium


# ── ASS dialogue event ─────────────────────────────────────────────────────────


@dataclass
class ASSCaptionEvent:
    """A single ASS Dialogue event."""
    layer: int = 0                 # Z-layer (0 = background, 1 = overlay)
    start: float = 0.0             # Start time in seconds
    end: float = 0.0               # End time in seconds
    style: str = "Default"         # ASS style name
    text: str = ""                 # ASS-escaped text with inline tags
    margin_l: int = 0
    margin_r: int = 0
    margin_v: int = 280            # Bottom margin (platform-dependent)
    effect: str = ""               # ASS transition effect
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_ass_dialogue(self) -> str:
        """Format as an ASS Dialogue line."""
        start_ass = _seconds_to_ass_time(self.start)
        end_ass = _seconds_to_ass_time(self.end)
        return (
            f"Dialogue: {self.layer},{start_ass},{end_ass},"
            f"{self.style},,{self.margin_l},{self.margin_r},{self.margin_v},"
            f"{self.effect},{self.text}"
        )


# ── ASS style definition ───────────────────────────────────────────────────────


@dataclass
class ASSCaptionStyleDef:
    """Definition of a single ASS style."""
    name: str = "Default"
    font_name: str = "Arial"
    font_size: float = 80.0
    primary_colour: str = ASS_WHITE
    secondary_colour: str = ASS_YELLOW
    outline_colour: str = ASS_BLACK
    back_colour: str = ASS_SEMI_BG
    bold: int = 0                  # -1 = bold, 0 = normal
    italic: int = 0
    underline: int = 0
    strikeout: int = 0
    scale_x: float = 100.0
    scale_y: float = 100.0
    spacing: float = 0.0
    angle: float = 0.0
    border_style: int = 1          # 1 = outline+shadow, 3 = opaque box
    outline: float = 2.0
    shadow: float = 2.0
    alignment: int = 2             # 2 = bottom centre
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 280
    encoding: int = 1

    def to_ass_style(self) -> str:
        """Format as an ASS Style line."""
        return (
            f"Style: {self.name},{self.font_name},{self.font_size:.0f},"
            f"{self.primary_colour},{self.secondary_colour},"
            f"{self.outline_colour},{self.back_colour},"
            f"{self.bold},{self.italic},{self.underline},{self.strikeout},"
            f"{self.scale_x:.0f},{self.scale_y:.0f},{self.spacing:.0f},"
            f"{self.angle:.0f},{self.border_style},{self.outline:.0f},"
            f"{self.shadow:.0f},{self.alignment},{self.margin_l},"
            f"{self.margin_r},{self.margin_v},{self.encoding}"
        )


# ── Per-word karaoke metadata ──────────────────────────────────────────────────


@dataclass
class WordKaraokeMeta:
    """Karaoke metadata for a single word."""
    text: str
    duration_cs: int               # Duration in centiseconds
    is_emphasis: bool = False      # Should be visually highlighted
    score: float = 0.5             # WhisperX alignment confidence
    colour_override: Optional[str] = None  # ASS colour override


# ── The caption plan ───────────────────────────────────────────────────────────


@dataclass
class ASSCaptionPlan:
    """
    Complete ASS caption plan for a single clip.

    This is the contract between the planning layer and the rendering layer.
    Downstream services consume this to produce the final .ass file.
    """
    clip_id: str
    styles: List[ASSCaptionStyleDef] = field(default_factory=list)
    events: List[ASSCaptionEvent] = field(default_factory=list)
    play_res_x: int = 1080
    play_res_y: int = 1920
    platform: str = "tiktok"       # "tiktok", "reels", "shorts", "universal"
    visual_style: str = "vpi_clean"
    wrap_style: int = 2            # 0 = smart, 1 = end-of-line, 2 = no word wrap

    # Per-word metadata for karaoke rendering
    word_metas: List[WordKaraokeMeta] = field(default_factory=list)

    # Hook overlay event (optional)
    hook_event: Optional[ASSCaptionEvent] = None

    # Lower-third event (optional)
    lower_third_event: Optional[ASSCaptionEvent] = None

    # Quality flags
    has_karaoke: bool = False
    has_emphasis: bool = False
    has_hook_overlay: bool = False
    has_lower_third: bool = False
    total_words: int = 0
    total_duration: float = 0.0
    visual_design_version: str = "a1"
    visual_design_tokens_applied: bool = False
    visual_design_tokens_applied_to_captions: bool = False
    caption_polish_profile: str = "standard_clean"
    caption_pacing_reason: str = ""
    caption_polish_applied: bool = False
    caption_polish_partial: bool = False
    caption_linebreak_polish_applied: bool = False
    caption_orphan_words_avoided: bool = False
    caption_protected_phrases_preserved: bool = False
    caption_timing_polish_applied: bool = False
    caption_too_fast_adjusted: bool = False
    caption_duration_balance_ok: bool = True
    caption_keyword_highlight_count: int = 0
    caption_highlight_policy: str = "single_keyword_sober"
    caption_hook_conflict_avoided: bool = False
    caption_cta_conflict_avoided: bool = False
    caption_broll_conflict_avoided: bool = False
    caption_visual_conflict_avoided: bool = False
    caption_timebase_corrected: bool = False
    caption_timebase_source: str = "clip_relative"
    caption_sync_warning: str = ""
    text_overlap_prevented: bool = True
    suppressed_text_layers: List[str] = field(default_factory=list)
    text_layer_count_final: int = 1
    caption_priority_enforced: bool = True
    ass_karaoke_enabled: bool = True
    ass_approx_simple_mode: bool = False
    ass_event_count_before: int = 0
    ass_event_count_final: int = 0
    ass_event_hard_cap: int = 22
    ass_event_hard_cap_exceeded_for_readability: bool = False
    ass_events_merged_for_daily: bool = False
    ass_hook_overlay_removed: bool = False

    # Real (sweep-computed) overlap metrics — see _compute_ass_temporal_overlap_metrics
    temporal_overlap_count: int = 0
    max_simultaneous_dialogues: int = 0
    min_gap_between_events: float = 0.0
    max_dialogue_chars_final: int = 0
    max_dialogue_words_final: int = 0
    captions_overlap_removed: bool = True

    warnings: List[str] = field(default_factory=list)

    def to_ass_script(self) -> str:
        """Generate a complete .ass file string from this plan."""
        lines: List[str] = []
        lines.append("[Script Info]")
        lines.append("ScriptType: v4.00+")
        lines.append(f"PlayResX: {self.play_res_x}")
        lines.append(f"PlayResY: {self.play_res_y}")
        lines.append("")

        lines.append("[V4+ Styles]")
        lines.append(
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, Strikeout, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        )
        for style in self.styles:
            lines.append(style.to_ass_style())
        lines.append("")

        lines.append("[Events]")
        lines.append(
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text"
        )
        for event in self.events:
            lines.append(event.to_ass_dialogue())

        # Hook overlay (layer 1)
        if self.hook_event:
            lines.append(self.hook_event.to_ass_dialogue())

        # Lower third (layer 1)
        if self.lower_third_event:
            lines.append(self.lower_third_event.to_ass_dialogue())

        return "\n".join(lines)

    def validate(self) -> List[str]:
        """Validate the plan and return warnings."""
        warnings: List[str] = []
        if not self.styles:
            warnings.append("No ASS styles defined")
        if not self.events:
            warnings.append("No ASS dialogue events")
        if self.total_words == 0 and self.events:
            warnings.append("Total words is 0 but events exist")
        self.warnings = warnings
        return warnings


# ── Platform margin mapping ────────────────────────────────────────────────────


_PLATFORM_MARGIN_V: Dict[str, int] = {
    "tiktok": 280,
    "reels": 260,
    "shorts": 300,
    "universal": 100,
}


def _platform_margin_v(platform: str) -> int:
    return _PLATFORM_MARGIN_V.get(platform, 280)


def _premium_captions_enabled() -> bool:
    return production_safe_edit_enabled()


def _strip_caption_accents(text: str) -> str:
    return str(text or "").translate(str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")).lower()


def _caption_word_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _strip_caption_accents(text))


def _select_vpi_caption_keywords(words: List[Dict[str, Any]], max_terms: int = 2) -> List[str]:
    if max_terms <= 0:
        return []
    selected: List[str] = []
    for word in words:
        token = _caption_word_token(str((word or {}).get("text") or ""))
        if token in _VPI_CAPTION_KEYWORDS and token not in selected:
            selected.append(token)
        if len(selected) >= max_terms:
            break
    return selected


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
    return re.sub(r"[^a-z0-9]+", "", _strip_caption_accents(text))


def _caption_phrase_tokens(phrases: Optional[List[str]] = None) -> List[tuple[str, ...]]:
    result: List[tuple[str, ...]] = []
    for phrase in phrases or _CAPTION_PROTECTED_PHRASES:
        parts = tuple(_caption_polish_token(part) for part in str(phrase).split() if _caption_polish_token(part))
        if len(parts) >= 2:
            result.append(parts)
    return result


def _caption_word_tokens(words: List[Dict[str, Any]]) -> List[str]:
    return [_caption_polish_token(str((word or {}).get("text") or "")) for word in words]


def _caption_tail_forms_protected_phrase(current_tokens: List[str], next_token: str, protected_phrases: List[tuple[str, ...]]) -> bool:
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
    words: List[Dict[str, Any]],
    max_words_per_line: int,
    max_chars_per_line: int = 0,
    protected_phrases: Optional[List[tuple[str, ...]]] = None,
) -> int:
    if len(words) <= 3:
        return max(1, len(words) // 2 or 1)
    protected_phrases = protected_phrases or _caption_phrase_tokens()
    tokens = _caption_word_tokens(words)
    char_counts = [len(str((word or {}).get("text") or "").strip()) for word in words]
    best_idx = max(1, min(len(words) - 1, (len(words) + 1) // 2))
    best_score = -1e9
    for idx in range(1, len(words)):
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


def _adaptive_font_size(base_size: int, words: List[Dict[str, Any]]) -> Tuple[int, Optional[str]]:
    word_count = len(words)
    char_count = sum(len(str((w or {}).get("text") or "").strip()) for w in words)
    factor = 1.0
    reason: Optional[str] = None
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


def _safe_zone_adjustment(
    *,
    platform: str,
    base_margin_v: int,
    hook_present: bool = False,
    lower_third_present: bool = False,
    words: Optional[List[Dict[str, Any]]] = None,
    play_res_y: int = 1920,
) -> Tuple[int, int, Optional[str]]:
    adjusted_margin_v = base_margin_v
    adjusted_pos_y = int(round(play_res_y * 0.84))
    reasons: List[str] = []
    words = words or []

    if hook_present:
        adjusted_margin_v += 28
        adjusted_pos_y = max(0, adjusted_pos_y - 26)
        reasons.append("hook_overlay")
    if lower_third_present:
        adjusted_margin_v += 18
        adjusted_pos_y = max(0, adjusted_pos_y - 18)
        reasons.append("lower_third")

    bbox_sources: List[Dict[str, Any]] = []
    for item in words:
        for key in ("face_bbox", "speaker_bbox", "bbox"):
            bbox = (item or {}).get(key)
            if isinstance(bbox, dict):
                bbox_sources.append(bbox)
    for bbox in bbox_sources:
        try:
            bottom = float(bbox.get("y", 0.0)) + float(bbox.get("height", bbox.get("h", 0.0)))
            if bottom >= 0.62:
                adjusted_margin_v += 22
                adjusted_pos_y = max(0, adjusted_pos_y - 18)
                reasons.append("face_bbox")
                break
        except Exception:
            continue

    if adjusted_margin_v == base_margin_v and adjusted_pos_y == int(round(play_res_y * 0.84)):
        return base_margin_v, adjusted_pos_y, None
    return adjusted_margin_v, adjusted_pos_y, ",".join(reasons) or "safe_default"


def _wrap_two_lines(
    words: List[Dict[str, Any]],
    emphasis_threshold: float = 0.82,
    emphasis_colour: str = ASS_WHITE,
    keyword_terms: Optional[List[str]] = None,
    font_size: Optional[int] = None,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    polish = caption_polish_profile if isinstance(caption_polish_profile, dict) else {}
    keyword_terms = list(keyword_terms or [])
    if not bool(polish.get("keyword_highlight_allowed", True)):
        keyword_terms = []
    keyword_set = {term for term in keyword_terms if term}
    max_words_per_line = max(3, int(polish.get("max_words_per_caption") or 5))
    protected_phrases = _caption_phrase_tokens()

    def _render_word(word: Dict[str, Any]) -> str:
        text = _ass_escape(word.get("text", ""))
        token = _caption_word_token(word.get("text", ""))
        duration_cs = max(1, int((word.get("end", 0.0) - word.get("start", 0.0)) * 100))
        score = word.get("score", 0.5)
        if score >= emphasis_threshold:
            return (
                f"{{\\k{duration_cs}\\c{emphasis_colour}\\fscx108\\fscy108}}{text}"
                f"{{\\c{ASS_WHITE}\\fscx100\\fscy100}}"
            )
        if token in keyword_set:
            return (
                f"{{\\k{duration_cs}\\c{ASS_SOFT_WHITE}\\b1\\fscx106\\fscy106}}{text}"
                f"{{\\c{ASS_WHITE}\\b0\\fscx100\\fscy100}}"
            )
        return f"{{\\k{duration_cs}}}{text}"

    prefix = "{\\fad(90,120)}"
    if font_size:
        prefix = f"{{\\fad(90,120)\\fs{font_size}}}"
    else:
        prefix = "{\\fad(90,120)\\fs72}"

    if len(words) <= 3:
        return prefix + " ".join(_render_word(w) for w in words)
    split_at = _caption_split_index(
        words,
        max_words_per_line=max_words_per_line,
        max_chars_per_line=int(polish.get("max_chars_per_caption") or 0),
        protected_phrases=protected_phrases,
    )
    first_line = " ".join(_render_word(w) for w in words[:split_at])
    second_line = " ".join(_render_word(w) for w in words[split_at:])
    return prefix + first_line + "\\N" + second_line


def _wrap_plain_two_lines(
    words: List[Dict[str, Any]],
    font_size: Optional[int] = None,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    polish = caption_polish_profile if isinstance(caption_polish_profile, dict) else {}
    max_words_per_line = max(2, int(polish.get("max_words_per_caption") or 3))
    # Real per-line character ceiling (Fix 3 / H9.2): the polish profile value is
    # advisory-only upstream (it can be 0/disabled or oversized for merged blocks),
    # so clamp it into a readable range. Oversized blocks must be prevented earlier
    # by the hard-cap merge ceilings (Fix 2) — this is a last-resort guard against
    # ever emitting a 200+ char line, never the primary splitting mechanism.
    max_chars_per_line_hard = 42
    max_chars_per_line = int(polish.get("max_chars_per_caption") or 0)
    if max_chars_per_line <= 0 or max_chars_per_line > max_chars_per_line_hard:
        max_chars_per_line = max_chars_per_line_hard
    protected_phrases = _caption_phrase_tokens()
    prefix = "{\\fad(90,120)}"
    if font_size:
        prefix = f"{{\\fad(90,120)\\fs{font_size}}}"
    else:
        prefix = "{\\fad(90,120)\\fs72}"

    if len(words) <= 3:
        return prefix + " ".join(_ass_escape(str(w.get("text", ""))) for w in words)
    split_at = _caption_split_index(
        words,
        max_words_per_line=max_words_per_line,
        max_chars_per_line=max_chars_per_line,
        protected_phrases=protected_phrases,
    )
    first_line = " ".join(_ass_escape(str(w.get("text", ""))) for w in words[:split_at])
    second_line = " ".join(_ass_escape(str(w.get("text", ""))) for w in words[split_at:])
    return prefix + first_line + ("\\N" + second_line if second_line else "")


# ── Time helpers ───────────────────────────────────────────────────────────────


def _seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS time format H:MM:SS.cc (centiseconds)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ── ASS text escaping ──────────────────────────────────────────────────────────


def _ass_escape(text: str) -> str:
    """Escape special characters for ASS text."""
    return text.replace("{", "\\{").replace("}", "\\}")


# ── Karaoke text builder ───────────────────────────────────────────────────────


def _build_karaoke_text(
    words: List[Dict[str, Any]],
    emphasis_threshold: float = 0.82,
    emphasis_colour: str = ASS_YELLOW,
) -> str:
    """Build ASS karaoke text with \\k tags and emphasis highlighting.

    Each word dict should have keys: 'text', 'start', 'end', 'score'.
    """
    parts: List[str] = []
    for w in words:
        text = _ass_escape(w.get("text", ""))
        duration_cs = max(1, int((w.get("end", 0.0) - w.get("start", 0.0)) * 100))
        score = w.get("score", 0.5)
        if score >= emphasis_threshold:
            parts.append(
                f"{{\\k{duration_cs}\\c{emphasis_colour}\\fscx110\\fscy110}}{text}"
                f"{{\\c{ASS_WHITE}\\fscx100\\fscy100}}"
            )
        else:
            parts.append(f"{{\\k{duration_cs}}}{text}")
    return " ".join(parts)


# ── Highlight text builder ─────────────────────────────────────────────────────


def _build_highlight_text(
    words: List[Dict[str, Any]],
    emphasis_threshold: float = 0.82,
    active_colour: str = ASS_RED,
) -> str:
    """Build per-word highlight text with active-word background boxes.

    Each word gets its own dialogue event with active-word highlighting.
    """
    parts: List[str] = []
    for i, w in enumerate(words):
        text = _ass_escape(w.get("text", ""))
        score = w.get("score", 0.5)
        if score >= emphasis_threshold:
            parts.append(f"{{\\c{active_colour}\\bord0\\shad0\\p0}}{text}{{\\r}}")
        else:
            parts.append(f"{{\\alpha&H40&}}{text}{{\\alpha&H00&}}")
    return " ".join(parts)


# ── Style definitions for presets ──────────────────────────────────────────────


def _build_default_styles(
    platform: str = "tiktok",
    visual_style: str = "vpi_clean",
) -> List[ASSCaptionStyleDef]:
    """Build the standard set of ASS styles for a clip."""
    margin_v = _platform_margin_v(platform)
    premium = _premium_captions_enabled() or str(visual_style or "").strip().lower() == "vpi_clean"
    tokens = get_vpi_visual_design_tokens()
    colors = tokens.get("colors") or {}
    typography = tokens.get("typography") or {}
    spacing = tokens.get("spacing") or {}

    def _hex_colour(value: str, fallback: str) -> str:
        raw = str(value or "").strip().lstrip("#")
        if len(raw) != 6:
            return fallback
        try:
            return ass_colour(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
        except Exception:
            return fallback

    if visual_style == "neon" and not premium:
        default_style = ASSCaptionStyleDef(
            name="Default",
            font_size=80,
            primary_colour=ASS_CYAN,
            secondary_colour=ASS_WHITE,
            outline_colour=ASS_BLACK,
            back_colour=ASS_TRANSP,
            border_style=1,
            outline=1.5,
            shadow=3.0,
            margin_v=margin_v,
        )
    elif visual_style == "minimal" and not premium:
        default_style = ASSCaptionStyleDef(
            name="Default",
            font_size=60,
            primary_colour=ASS_WHITE,
            secondary_colour=ASS_WHITE,
            outline_colour=ASS_BLACK,
            back_colour=ASS_SEMI_BG,
            border_style=3,
            outline=0,
            shadow=0,
            margin_v=margin_v,
        )
    elif visual_style == "tiktok" and not premium:
        default_style = ASSCaptionStyleDef(
            name="Default",
            font_size=100,
            primary_colour=ASS_WHITE,
            secondary_colour=ASS_YELLOW,
            outline_colour=ASS_BLACK,
            back_colour=ASS_TRANSP,
            bold=-1,
            border_style=1,
            outline=3.0,
            shadow=4.0,
            alignment=2,
            margin_v=margin_v,
        )
    else:
        # vpi_clean / karaoke / highlight (premium white palette)
        default_style = ASSCaptionStyleDef(
            name="Default",
            font_size=int(round(72 * float(typography.get("caption_font_scale") or 1.0))),
            primary_colour=_hex_colour(str(colors.get("text_primary") or ""), ASS_WHITE),
            secondary_colour=_hex_colour(str(colors.get("text_secondary") or ""), ASS_SOFT_WHITE),
            outline_colour=_hex_colour(str(colors.get("border_soft") or ""), ASS_BLACK),
            back_colour=_hex_colour(str(colors.get("bg_panel") or ""), ASS_SEMI_BG),
            border_style=1,
            outline=3.0,
            shadow=1.0,
            margin_v=max(margin_v, int(spacing.get("caption_bottom_margin") or margin_v)),
        )

    hook_style = ASSCaptionStyleDef(
        name="HookOverlay",
        font_size=int(round(58 * float(typography.get("hook_font_scale") or 1.0))),
        primary_colour=_hex_colour(str(colors.get("text_primary") or ""), ASS_WHITE),
        secondary_colour=_hex_colour(str(colors.get("text_secondary") or ""), ASS_SOFT_WHITE),
        outline_colour=_hex_colour(str(colors.get("border_soft") or ""), ASS_BLACK),
        back_colour=_hex_colour(str(colors.get("bg_panel_strong") or ""), ASS_SEMI_BG),
        border_style=0,
        outline=1.0,
        shadow=1.0,
        alignment=8,  # top centre
        margin_l=int(spacing.get("safe_padding") or 40),
        margin_r=int(spacing.get("safe_padding") or 40),
        margin_v=int(spacing.get("hook_top_margin") or 120),
    )

    lower_third_style = ASSCaptionStyleDef(
        name="LowerThird",
        font_size=int(round(42 * float(typography.get("badge_font_scale") or 1.0))),
        primary_colour=_hex_colour(str(colors.get("text_primary") or ""), ASS_WHITE),
        secondary_colour=_hex_colour(str(colors.get("text_secondary") or ""), ASS_SOFT_WHITE),
        outline_colour=_hex_colour(str(colors.get("border_soft") or ""), ASS_BLACK),
        back_colour=_hex_colour(str(colors.get("bg_panel") or ""), ASS_SEMI_BG),
        border_style=0,
        outline=1.0,
        shadow=1.0,
        alignment=1,  # bottom left
        margin_l=int(spacing.get("safe_padding") or 42),
        margin_r=int(spacing.get("safe_padding") or 42),
        margin_v=int(spacing.get("caption_bottom_margin") or 360),
    )

    return [default_style, hook_style, lower_third_style]


def _compute_ass_temporal_overlap_metrics(events: List["ASSCaptionEvent"]) -> Dict[str, Any]:
    """Sweep real Dialogue events (sorted by start) for genuine temporal-overlap metrics.

    Mirrors the read-only analysis used in H9.1 forensics (sweep-line over
    [start, end) plus consecutive-pair overlap count) so plan metadata reflects
    plan.events as actually written, not which text layers were suppressed.
    """
    by_start = sorted(events, key=lambda e: e.start)
    overlap_count = 0
    min_gap: Optional[float] = None
    for i in range(len(by_start) - 1):
        a, b = by_start[i], by_start[i + 1]
        gap = b.start - a.end
        if min_gap is None or gap < min_gap:
            min_gap = gap
        if b.start < a.end - 1e-6:
            overlap_count += 1

    sweep: List[Tuple[float, int]] = []
    for e in events:
        sweep.append((e.start, 1))
        sweep.append((e.end, -1))
    sweep.sort(key=lambda x: (x[0], -x[1]))
    current = 0
    max_simultaneous = 0
    for _, delta in sweep:
        current += delta
        max_simultaneous = max(max_simultaneous, current)

    max_chars = 0
    max_words = 0
    for e in events:
        plain = re.sub(r"\{[^}]*\}", "", e.text or "").replace("\\N", " ").replace("\\n", " ")
        max_chars = max(max_chars, len(plain.strip()))
        max_words = max(max_words, len([w for w in plain.split() if w]))

    return {
        "temporal_overlap_count": overlap_count,
        "max_simultaneous_dialogues": max_simultaneous,
        "min_gap_between_events": round(min_gap, 4) if min_gap is not None else 0.0,
        "max_dialogue_chars_final": max_chars,
        "max_dialogue_words_final": max_words,
    }


# ── Main plan builder ──────────────────────────────────────────────────────────


def build_ass_caption_plan(
    clip_id: str,
    words: List[Dict[str, Any]],
    clip_duration: float,
    platform: str = "tiktok",
    visual_style: str = "vpi_clean",
    caption_style: str = "karaoke",
    editorial_type: str = "",
    caption_density: float = 0.0,
    hook_strategy_final: str = "",
    premium_restraint_mode: str = "",
    visual_layout_strategy: str = "",
    broll_timing_strategy: str = "",
    cta_decision: str = "",
    sensitive_topic: bool = False,
    emphasis_indices: Optional[List[int]] = None,
    hook_text: Optional[str] = None,
    hook_start: Optional[float] = None,
    hook_end: Optional[float] = None,
    lower_third_text: Optional[str] = None,
    lower_third_start: Optional[float] = None,
    lower_third_end: Optional[float] = None,
    margin_v_override: Optional[int] = None,
    approx_simple_mode: bool = False,
    global_visual_layer_budget: Optional[Dict[str, Any]] = None,
) -> ASSCaptionPlan:
    """Build a complete ASSCaptionPlan for a clip.

    Args:
        clip_id: Unique clip identifier.
        words: List of word dicts with 'text', 'start', 'end', 'score' keys.
        clip_duration: Total clip duration in seconds.
        platform: Target platform ('tiktok', 'reels', 'shorts', 'universal').
        visual_style: Visual style preset name.
        caption_style: ASS caption style ('karaoke', 'highlight', 'tiktok',
            'minimal', 'neon', 'vpi_clean').
        emphasis_indices: Indices of words to emphasise.
        hook_text: Hook overlay text (optional).
        hook_start: Hook overlay start time (optional).
        hook_end: Hook overlay end time (optional).
        lower_third_text: Lower-third text (optional).
        lower_third_start: Lower-third start time (optional).
        lower_third_end: Lower-third end time (optional).
        margin_v_override: Override bottom margin (optional).

    Returns:
        ASSCaptionPlan ready for downstream consumption.
    """
    budget = global_visual_layer_budget if isinstance(global_visual_layer_budget, dict) else {}
    words, caption_timebase_corrected, caption_timebase_source, caption_sync_warning = _normalize_caption_words_to_clip_timebase(
        list(words or []),
        float(clip_duration or 0.0),
    )
    budget_decisions = budget.get("layer_decisions") if isinstance(budget.get("layer_decisions"), dict) else {}
    budget_allowed = set(str(item) for item in (budget.get("allowed_layers") or budget.get("visual_layers_allowed") or []))
    premium = _premium_captions_enabled() or str(visual_style or "").strip().lower() == "vpi_clean"
    suppressed_text_layers: List[str] = []

    def _budget_action(layer: str) -> str:
        _decision = dict((budget_decisions or {}).get(layer) or {})
        _action = str(_decision.get("action") or "").strip()
        if _action:
            return _action
        if budget and layer not in budget_allowed:
            return "drop"
        return "allow"

    if hook_text:
        _hook_budget_action = _budget_action("hook_overlay")
        if _hook_budget_action == "drop":
            logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=hook_overlay reason=%s", str((budget_decisions or {}).get("hook_overlay", {}).get("reason") or "visual_layer_budget"))
            logger.info("OVERLAY_RENDER_BLOCKED_BY_BUDGET layer=hook_overlay reason=%s", str((budget_decisions or {}).get("hook_overlay", {}).get("reason") or "visual_layer_budget"))
            hook_text = None
            hook_start = None
            hook_end = None
            suppressed_text_layers.append("hook_overlay")
        elif _hook_budget_action == "delay":
            _hook_new_start = float((budget_decisions or {}).get("hook_overlay", {}).get("new_start_s") or hook_start or 0.0)
            _hook_duration = max(0.0, float(hook_end or 0.0) - float(hook_start or 0.0))
            hook_start = _hook_new_start
            hook_end = _hook_new_start + _hook_duration if _hook_duration > 0 else hook_end
            logger.info(
                "OVERLAY_DELAYED_COLLISION_GUARD layer=hook_overlay old_start=%.2f new_start=%.2f",
                float((budget_decisions or {}).get("hook_overlay", {}).get("start_s") or 0.0),
                _hook_new_start,
            )

    if lower_third_text:
        _lt_budget_action = _budget_action("lower_third")
        if _lt_budget_action == "drop":
            logger.info("OVERLAY_DROPPED_COLLISION_GUARD layer=lower_third reason=%s", str((budget_decisions or {}).get("lower_third", {}).get("reason") or "visual_layer_budget"))
            logger.info("OVERLAY_RENDER_BLOCKED_BY_BUDGET layer=lower_third reason=%s", str((budget_decisions or {}).get("lower_third", {}).get("reason") or "visual_layer_budget"))
            lower_third_text = None
            lower_third_start = None
            lower_third_end = None
            suppressed_text_layers.append("lower_third")
        elif _lt_budget_action == "delay":
            _lt_new_start = float((budget_decisions or {}).get("lower_third", {}).get("new_start_s") or lower_third_start or 0.0)
            _lt_duration = max(0.0, float(lower_third_end or 0.0) - float(lower_third_start or 0.0))
            lower_third_start = _lt_new_start
            lower_third_end = _lt_new_start + _lt_duration if _lt_duration > 0 else lower_third_end
            logger.info(
                "OVERLAY_DELAYED_COLLISION_GUARD layer=lower_third old_start=%.2f new_start=%.2f",
                float((budget_decisions or {}).get("lower_third", {}).get("start_s") or 0.0),
                _lt_new_start,
            )

    plan = ASSCaptionPlan(
        clip_id=clip_id,
        platform=platform,
        visual_style=visual_style,
    )
    visual_tokens = get_vpi_visual_design_tokens()
    plan.visual_design_version = str(visual_tokens.get("visual_design_version") or "a1")
    plan.visual_design_tokens_applied = True
    plan.visual_design_tokens_applied_to_captions = True
    logger.info("VPI_VISUAL_TOKENS_APPLIED backend=vpi_ass visual_design_version=%s", plan.visual_design_version)

    density_hint = float(caption_density or (len(words) / max(1.0, float(clip_duration or 0.0) or 1.0)))
    caption_polish_profile = choose_vpi_caption_polish_profile(
        editorial_type=editorial_type,
        clip_duration=clip_duration,
        caption_density=density_hint,
        hook_strategy_final=hook_strategy_final or (hook_text or ""),
        premium_restraint_mode=premium_restraint_mode,
        visual_layout_strategy=visual_layout_strategy,
        broll_timing_strategy=broll_timing_strategy,
        cta_decision=cta_decision,
        sensitive_topic=bool(sensitive_topic or editorial_type == "decesos" or "decesos" in str(editorial_type).lower()),
        words_with_timestamps=words,
    )
    plan.caption_polish_profile = str(caption_polish_profile.get("caption_polish_profile") or "standard_clean")
    plan.caption_pacing_reason = str(caption_polish_profile.get("caption_pacing_reason") or "")
    plan.caption_polish_applied = bool(caption_polish_profile.get("caption_polish_applied", True))
    plan.caption_polish_partial = False
    plan.caption_timebase_corrected = bool(caption_timebase_corrected)
    plan.caption_timebase_source = caption_timebase_source
    plan.caption_sync_warning = caption_sync_warning
    _daily_mode_active = os.environ.get("VPI_DAILY_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    _production_safe_active = os.environ.get("VPI_PRODUCTION_SAFE_EDIT", "").strip().lower() in {"1", "true", "yes", "on"}
    simple_caption_mode = bool(approx_simple_mode or not caption_timebase_corrected or _daily_mode_active or _production_safe_active)
    keyword_terms = _select_vpi_caption_keywords(
        words,
        max_terms=0 if simple_caption_mode or not bool(caption_polish_profile.get("keyword_highlight_allowed", True)) else 2,
    )
    if simple_caption_mode:
        caption_polish_profile = dict(caption_polish_profile or {})
        caption_polish_profile["caption_polish_profile"] = "standard_clean"
        caption_polish_profile["caption_pacing_reason"] = ",".join(
            [part for part in [
                str(caption_polish_profile.get("caption_pacing_reason") or ""),
                "approx_simple_mode",
            ] if part]
        )
        caption_polish_profile["max_words_per_caption"] = min(int(caption_polish_profile.get("max_words_per_caption") or 3), 3)
        caption_polish_profile["max_caption_duration"] = min(float(caption_polish_profile.get("max_caption_duration") or 2.2), 2.4)
        caption_polish_profile["max_chars_per_caption"] = min(int(caption_polish_profile.get("max_chars_per_caption") or 28), 28)
        caption_polish_profile["keyword_highlight_allowed"] = False
        logger.info(
            "VPI_ASS_APPROX_TIMING_SIMPLE_CAPTIONS clip_id=%s timebase=%s approx=%s",
            clip_id,
            caption_timebase_source,
            str(not caption_timebase_corrected).lower(),
        )
    caption_overlay_terms = list(
        (
            budget.get("keyword_emphasis_terms")
            if isinstance(budget.get("keyword_emphasis_terms"), list)
            else keyword_terms
        )
        or []
    )
    if simple_caption_mode:
        caption_overlay_terms = []
        emphasis_indices = []
    if keyword_terms:
        logger.info(
            "VPI_CAPTION_KEYWORD_HIGHLIGHT_APPLIED backend=vpi_ass terms=%s",
            "|".join(keyword_terms[:2]),
        )

    # 1. Build styles
    plan.styles = _build_default_styles(platform, visual_style)
    base_margin_v = margin_v_override or _platform_margin_v(platform)
    margin_v, safe_pos_y, safe_reason = _safe_zone_adjustment(
        platform=platform,
        base_margin_v=base_margin_v,
        hook_present=bool(hook_text),
        lower_third_present=bool(lower_third_text),
        words=words,
        play_res_y=plan.play_res_y,
    )
    if safe_reason:
        logger.info("VPI_CAPTION_SAFE_ZONE_ADJUSTED backend=vpi_ass reason=%s", safe_reason)
    if plan.styles:
        plan.styles[0].margin_v = margin_v
        if simple_caption_mode:
            plan.styles[0].margin_v = min(plan.styles[0].margin_v, 240)
            logger.info(
                "VPI_ASS_CAPTION_PLACEMENT_STABILIZED clip_id=%s margin_v=%d alignment=%d",
                clip_id,
                int(plan.styles[0].margin_v),
                int(plan.styles[0].alignment),
            )

    # 2. Build per-word metadata
    emphasis_set = set(emphasis_indices or [])
    word_metas: List[WordKaraokeMeta] = []
    for i, w in enumerate(words):
        text = w.get("text", "")
        duration_cs = max(1, int((w.get("end", 0.0) - w.get("start", 0.0)) * 100))
        is_emphasis = i in emphasis_set or w.get("score", 0.5) >= 0.82
        word_metas.append(WordKaraokeMeta(
            text=text,
            duration_cs=duration_cs,
            is_emphasis=is_emphasis,
            score=w.get("score", 0.5),
        ))
    plan.word_metas = word_metas
    plan.total_words = len(words)
    plan.total_duration = clip_duration

    # 3. Build dialogue events
    if simple_caption_mode:
        plan.has_karaoke = False
        plan.has_emphasis = False
        hard_cap_events = 22
        target_events = max(16, min(hard_cap_events, int(round(max(float(clip_duration or 0.0), 1.0) / 2.0))))
        target_event_duration = max(1.6, min(2.2, float(clip_duration or 0.0) / max(1, target_events)))
        max_chars_per_caption = 28
        max_words_per_block = max(2, min(4, int((len(words) + max(1, target_events) - 1) / max(1, target_events))))
        line_words: List[List[Dict[str, Any]]] = []
        current_line: List[Dict[str, Any]] = []
        current_chars = 0
        for w in words:
            current_line.append(w)
            current_chars += len(str(w.get("text", "") or w.get("word", "")).strip())
            line_start = float(current_line[0].get("start", 0.0))
            line_end = float(current_line[-1].get("end", line_start))
            current_duration = max(0.0, line_end - line_start)
            if len(current_line) >= max_words_per_block or current_chars >= max_chars_per_caption or current_duration >= target_event_duration:
                line_words.append(current_line)
                current_line = []
                current_chars = 0
        if current_line:
            line_words.append(current_line)
        ass_event_count_before = len(line_words)
        merged_for_daily = False
        hard_cap_exceeded_for_readability = False
        # Fix 2 (H9.2): never let a merge produce an oversized "wall of text" block.
        # These are absolute ceilings on the RESULT of a merge — independent of the
        # softer per-caption polish-profile targets above (max_chars_per_caption=28
        # etc.), which only govern the initial word-grouping pass.
        max_chars_per_caption_hard = 84
        max_words_per_caption_hard = 14
        max_duration_hard = 2.8

        def _merged_block_metrics(block: List[Dict[str, Any]]) -> Tuple[int, int, float]:
            text_chars = sum(len(str(w.get("text", "") or w.get("word", "")).strip()) for w in block)
            text_chars += max(0, len(block) - 1)  # spaces between words
            b_start = float(block[0].get("start", 0.0))
            b_end = float(block[-1].get("end", b_start))
            return text_chars, len(block), max(0.0, b_end - b_start)

        while len(line_words) > hard_cap_events and len(line_words) > 1:
            best_idx: Optional[int] = None
            best_gap = None
            blocked_pairs = 0
            for idx in range(len(line_words) - 1):
                left = line_words[idx]
                right = line_words[idx + 1]
                left_end = float(left[-1].get("end", left[0].get("start", 0.0)))
                right_start = float(right[0].get("start", left_end))
                gap = right_start - left_end
                merged_chars, merged_words, merged_duration = _merged_block_metrics(left + right)
                if (
                    merged_chars > max_chars_per_caption_hard
                    or merged_words > max_words_per_caption_hard
                    or merged_duration > max_duration_hard
                ):
                    blocked_pairs += 1
                    continue
                if best_gap is None or gap < best_gap:
                    best_gap = gap
                    best_idx = idx
            if best_idx is None:
                # No remaining adjacent pair can be merged without exceeding the
                # readability ceilings — prefer 23-26 (or more) small events over a
                # single 84+/14+ word mega-Dialogue. Stop merging and relax the cap.
                logger.info(
                    "VPI_ASS_MERGE_BLOCKED_BY_TEXT_LENGTH clip_id=%s remaining_events=%d hard_cap=%d "
                    "blocked_pairs=%d max_chars_hard=%d max_words_hard=%d max_duration_hard=%.2f",
                    clip_id,
                    len(line_words),
                    hard_cap_events,
                    blocked_pairs,
                    max_chars_per_caption_hard,
                    max_words_per_caption_hard,
                    max_duration_hard,
                )
                break
            merged_for_daily = True
            line_words[best_idx].extend(line_words.pop(best_idx + 1))
        if len(line_words) > hard_cap_events:
            hard_cap_exceeded_for_readability = True
            logger.warning(
                "VPI_ASS_HARD_CAP_RELAXED_FOR_READABILITY clip_id=%s hard_cap=%d final=%d "
                "reason=text_length_ceiling max_chars_hard=%d max_words_hard=%d max_duration_hard=%.2f",
                clip_id,
                hard_cap_events,
                len(line_words),
                max_chars_per_caption_hard,
                max_words_per_caption_hard,
                max_duration_hard,
            )
        if merged_for_daily:
            logger.info(
                "VPI_ASS_EVENTS_MERGED_FOR_DAILY clip_id=%s before=%d after=%d hard_cap=%d",
                clip_id,
                ass_event_count_before,
                len(line_words),
                hard_cap_events,
            )
        logger.info(
            "VPI_ASS_EVENT_HARD_CAP_APPLIED clip_id=%s before=%d final=%d hard_cap=%d",
            clip_id,
            ass_event_count_before,
            len(line_words),
            hard_cap_events,
        )
        logger.info(
            "VPI_ASS_EVENT_COUNT_REDUCED clip_id=%s words=%d events=%d mode=simple",
            clip_id,
            len(words),
            len(line_words),
        )
        # Fix 1 (H9.2): running previous_end clamp — mirrors the proven-correct
        # pattern in caption_service.py::build_ass_script() (event_start =
        # max(line.line_start, previous_end)). The min-duration floor must never be
        # re-applied AFTER the next-start clamp (that was the root cause of the
        # Type-A real overlap: it silently re-extended event_end past next_start).
        # Overlap is guaranteed prevented at the START side: each event_start is
        # clamped to previous_end + gap, so event_start[i+1] >= previous_end[i] + gap
        # > previous_end[i] = event_end[i], regardless of how event_end is computed.
        min_duration = 1.15
        max_duration = 2.6
        min_gap_between = 0.05
        previous_end: Optional[float] = None
        overlap_prevented_count = 0
        for idx, line in enumerate(line_words):
            raw_start = float(line[0].get("start", 0.0))
            raw_end = float(line[-1].get("end", raw_start))
            if previous_end is None:
                event_start = raw_start
            else:
                event_start = max(raw_start, previous_end + min_gap_between)
                if event_start > raw_start + 1e-6:
                    overlap_prevented_count += 1
                    logger.info(
                        "VPI_ASS_TEMPORAL_OVERLAP_PREVENTED clip_id=%s idx=%d raw_start=%.3f "
                        "previous_end=%.3f event_start=%.3f",
                        clip_id,
                        idx,
                        raw_start,
                        previous_end,
                        event_start,
                    )
            natural_end = max(raw_end, event_start + min_duration)
            event_end = min(natural_end, event_start + max_duration)
            if idx + 1 < len(line_words):
                next_raw_start = float(line_words[idx + 1][0].get("start", event_end + min_gap_between))
                next_start_limit = next_raw_start - min_gap_between
                if event_end > next_start_limit:
                    clamped_end = max(event_start + 0.35, next_start_limit)
                    if clamped_end < event_end:
                        event_end = clamped_end
                        logger.info(
                            "VPI_ASS_EVENT_TIMING_CLAMPED_TO_NEXT_START clip_id=%s idx=%d "
                            "event_start=%.3f event_end=%.3f next_start=%.3f",
                            clip_id,
                            idx,
                            event_start,
                            event_end,
                            next_raw_start,
                        )
            if event_end <= event_start:
                event_end = event_start + 0.35
            previous_end = event_end
            base_font_size = 72
            adjusted_font_size, size_reason = _adaptive_font_size(base_font_size, line)
            if size_reason:
                logger.info(
                    "VPI_CAPTION_ADAPTIVE_SIZE_APPLIED backend=vpi_ass old_size=%d new_size=%d reason=%s",
                    base_font_size,
                    adjusted_font_size,
                    size_reason,
                )
            ass_text = _wrap_plain_two_lines(
                line,
                font_size=adjusted_font_size,
                caption_polish_profile=caption_polish_profile,
            )
            plan.events.append(
                ASSCaptionEvent(
                    layer=0,
                    start=event_start,
                    end=event_end,
                    style="Default",
                    text=ass_text,
                    margin_v=margin_v,
                )
            )
        plan.has_hook_overlay = False
        plan.has_lower_third = False
        if hook_text:
            suppressed_text_layers.append("hook_overlay")
            logger.info("VPI_ASS_HOOK_OVERLAY_REMOVED clip_id=%s reason=approx_simple_mode", clip_id)
            logger.info("VPI_NON_TEXT_VISUAL_HOOK_DISABLED_FOR_CAPTIONS clip_id=%s reason=approx_simple_mode", clip_id)
        if lower_third_text:
            suppressed_text_layers.append("lower_third")
            logger.info("VPI_ASS_LOWER_THIRD_REMOVED_FROM_PLAN clip_id=%s reason=approx_simple_mode", clip_id)
        plan.ass_event_count_before = int(ass_event_count_before)
        plan.ass_event_hard_cap = int(hard_cap_events)
        plan.ass_event_hard_cap_exceeded_for_readability = bool(hard_cap_exceeded_for_readability)
        plan.ass_events_merged_for_daily = bool(merged_for_daily)
        plan.ass_approx_simple_mode = True
    elif caption_style == "highlight":
        # Per-word dialogue events
        for i, w in enumerate(words):
            text = _ass_escape(w.get("text", ""))
            score = w.get("score", 0.5)
            if score >= 0.82 or i in emphasis_set:
                ass_text = f"{{\\c{ASS_WHITE}\\b1}}{text}{{\\r}}"
            else:
                ass_text = f"{{\\alpha&H40&}}{text}{{\\alpha&H00&}}"

            event = ASSCaptionEvent(
                layer=0,
                start=w.get("start", 0.0),
                end=w.get("end", 0.0),
                style="Default",
                text=ass_text,
                margin_v=margin_v,
            )
            plan.events.append(event)
        plan.has_karaoke = False
        plan.has_emphasis = True
    else:
        # Karaoke-style grouped dialogue events
        # Group words into lines using the polish profile's max word budget.
        max_words_per_block = max(3, int(caption_polish_profile.get("max_words_per_caption") or 5))
        line_words: List[List[Dict[str, Any]]] = []
        current_line: List[Dict[str, Any]] = []
        for w in words:
            current_line.append(w)
            if len(current_line) >= max_words_per_block:
                line_words.append(current_line)
                current_line = []
        if current_line:
            line_words.append(current_line)

        for line in line_words:
            line_start = line[0].get("start", 0.0)
            line_end = line[-1].get("end", 0.0)
            base_font_size = 72
            adjusted_font_size, size_reason = _adaptive_font_size(base_font_size, line)
            if size_reason:
                logger.info(
                    "VPI_CAPTION_ADAPTIVE_SIZE_APPLIED backend=vpi_ass old_size=%d new_size=%d reason=%s",
                    base_font_size,
                    adjusted_font_size,
                    size_reason,
                )
            ass_text = _wrap_two_lines(
                line,
                emphasis_threshold=0.82,
                emphasis_colour=ASS_WHITE,
                keyword_terms=keyword_terms,
                font_size=adjusted_font_size,
                caption_polish_profile=caption_polish_profile,
            )

            event = ASSCaptionEvent(
                layer=0,
                start=line_start,
                end=line_end,
                style="Default",
                text=ass_text,
                margin_v=margin_v,
            )
            plan.events.append(event)
        plan.has_karaoke = True
        plan.has_emphasis = any(w.get("score", 0.5) >= 0.82 for w in words)

    # 4. Hook overlay event
    if not simple_caption_mode and hook_text and hook_start is not None and hook_end is not None:
        escaped = _ass_escape(hook_text)
        plan.hook_event = ASSCaptionEvent(
            layer=1,
            start=hook_start,
            end=hook_end,
            style="HookOverlay",
            text=f"{{\\an8\\pos(540,307)\\fad(80,120)}}{escaped}",
            margin_v=margin_v,
        )
        plan.has_hook_overlay = True

    # 5. Lower-third event
    if not simple_caption_mode and lower_third_text and lower_third_start is not None and lower_third_end is not None:
        escaped = _ass_escape(lower_third_text)
        plan.lower_third_event = ASSCaptionEvent(
            layer=1,
            start=lower_third_start,
            end=lower_third_end,
            style="LowerThird",
            text=f"{{\\an1\\fad(80,120)}}{escaped}",
            margin_v=margin_v,
        )
        plan.has_lower_third = True

    caption_events = list(plan.events)
    if plan.hook_event:
        caption_events.append(plan.hook_event)
    if plan.lower_third_event:
        caption_events.append(plan.lower_third_event)
    line_durations = [float(event.end - event.start) for event in plan.events if float(event.end or 0.0) >= float(event.start or 0.0)]
    caption_min_duration = float(caption_polish_profile.get("min_caption_duration") or 0.0)
    caption_max_duration = float(caption_polish_profile.get("max_caption_duration") or 0.0)
    caption_orphan_words_avoided = bool(all(len(group) > 1 for group in line_words)) if "line_words" in locals() and caption_style != "highlight" else True
    caption_protected_phrases_preserved = bool(
        any(
            phrase in _caption_polish_token(" ".join(event.text for event in plan.events))
            for phrase in (_caption_polish_token(p) for p in _CAPTION_PROTECTED_PHRASES)
        )
    )
    caption_timing_polish_applied = True
    caption_too_fast_adjusted = bool(caption_min_duration and any(duration <= (caption_min_duration + 0.03) for duration in line_durations))
    caption_duration_balance_ok = bool(
        not line_durations
        or all(
            duration >= max(0.50, caption_min_duration - 0.05)
            and (not caption_max_duration or duration <= caption_max_duration * 1.2)
            for duration in line_durations
        )
    )
    caption_keyword_highlight_count = 0 if simple_caption_mode else (len(keyword_terms) if plan.has_karaoke or plan.has_emphasis else min(len(keyword_terms), len(plan.events)))
    caption_highlight_policy = str(caption_polish_profile.get("caption_highlight_policy") or "single_keyword_sober")
    caption_linebreak_polish_applied = bool(caption_polish_profile)
    caption_hook_conflict_avoided = bool(simple_caption_mode or not hook_text or plan.has_hook_overlay or caption_linebreak_polish_applied)
    caption_cta_conflict_avoided = bool(str(cta_decision or "") != "show_cta" or caption_highlight_policy != "dense")
    caption_broll_conflict_avoided = bool(str(broll_timing_strategy or "") in {"", "no_broll"} or caption_polish_profile.get("caption_polish_profile") in {"calm_readable", "sensitive_soft"})
    caption_visual_conflict_avoided = bool(caption_hook_conflict_avoided or caption_cta_conflict_avoided or caption_broll_conflict_avoided)
    plan.text_overlap_prevented = bool(simple_caption_mode or not hook_text or not lower_third_text or caption_visual_conflict_avoided)
    plan.suppressed_text_layers = list(dict.fromkeys(suppressed_text_layers))
    plan.text_layer_count_final = 1
    plan.caption_priority_enforced = bool(simple_caption_mode or plan.text_overlap_prevented or caption_density >= 0.55 or plan.caption_polish_profile in {"dense_explainer", "sensitive_soft"})
    plan.caption_linebreak_polish_applied = bool(caption_linebreak_polish_applied)
    plan.caption_orphan_words_avoided = bool(caption_orphan_words_avoided)
    plan.caption_protected_phrases_preserved = bool(caption_protected_phrases_preserved)
    plan.caption_timing_polish_applied = bool(caption_timing_polish_applied)
    plan.caption_too_fast_adjusted = bool(caption_too_fast_adjusted)
    plan.caption_duration_balance_ok = bool(caption_duration_balance_ok)
    plan.caption_keyword_highlight_count = int(caption_keyword_highlight_count)
    plan.caption_highlight_policy = caption_highlight_policy
    plan.caption_hook_conflict_avoided = bool(caption_hook_conflict_avoided)
    plan.caption_cta_conflict_avoided = bool(caption_cta_conflict_avoided)
    plan.caption_broll_conflict_avoided = bool(caption_broll_conflict_avoided)
    plan.caption_visual_conflict_avoided = bool(caption_visual_conflict_avoided)
    plan.text_overlap_prevented = bool(simple_caption_mode or not hook_text or not lower_third_text or caption_visual_conflict_avoided)
    plan.suppressed_text_layers = list(dict.fromkeys(suppressed_text_layers))
    plan.text_layer_count_final = 1 if simple_caption_mode else int(1 + int(bool(hook_text)) + int(bool(lower_third_text)))
    if plan.caption_priority_enforced and plan.text_layer_count_final > 2:
        plan.text_layer_count_final = 2
    plan.ass_karaoke_enabled = bool(plan.has_karaoke and not simple_caption_mode)
    plan.ass_approx_simple_mode = bool(simple_caption_mode)
    plan.ass_event_count_final = int(len(plan.events))
    plan.ass_hook_overlay_removed = bool(simple_caption_mode and bool(hook_text))
    if simple_caption_mode:
        plan.caption_sync_warning = str(plan.caption_sync_warning or "approx_simple_mode")
        plan.caption_linebreak_polish_applied = True
        plan.caption_timing_polish_applied = True
        plan.caption_orphan_words_avoided = True
        plan.caption_protected_phrases_preserved = True
        plan.caption_visual_conflict_avoided = True
        plan.caption_hook_conflict_avoided = True
        plan.caption_broll_conflict_avoided = True
        plan.caption_cta_conflict_avoided = True
        plan.caption_priority_enforced = True
        plan.suppressed_text_layers = list(dict.fromkeys(suppressed_text_layers + (["hook_overlay"] if bool(hook_text) else []) + (["lower_third"] if bool(lower_third_text) else [])))
        plan.text_layer_count_final = 1
        logger.info("VPI_ASS_KARAOKE_DISABLED_APPROX clip_id=%s reason=approx_simple_mode", clip_id)
        logger.info("VPI_ASS_CAPTION_OVERLAP_REMOVED clip_id=%s layers=%s", clip_id, "|".join(plan.suppressed_text_layers) or "none")
        logger.info(
            "VPI_ASS_EVENT_COUNT_FINAL clip_id=%s before=%d final=%d hard_cap=%d",
            clip_id,
            int(getattr(plan, "ass_event_count_before", len(plan.events)) or len(plan.events)),
            int(plan.ass_event_count_final),
            int(getattr(plan, "ass_event_hard_cap", 22) or 22),
        )

    # Fix 4 (H9.2): real overlap metadata — sweep plan.events (the same Dialogue
    # events that get serialized to the .ass file) sorted by start/end and derive
    # text_overlap_prevented / captions_overlap_removed from THAT, not from which
    # competing text layers were suppressed. This replaces the prior false-positive
    # `text_overlap_prevented = True` hard override (Type C bug from H9.1).
    overlap_metrics = _compute_ass_temporal_overlap_metrics(plan.events)
    plan.temporal_overlap_count = int(overlap_metrics["temporal_overlap_count"])
    plan.max_simultaneous_dialogues = int(overlap_metrics["max_simultaneous_dialogues"])
    plan.min_gap_between_events = float(overlap_metrics["min_gap_between_events"])
    plan.max_dialogue_chars_final = int(overlap_metrics["max_dialogue_chars_final"])
    plan.max_dialogue_words_final = int(overlap_metrics["max_dialogue_words_final"])
    plan.captions_overlap_removed = bool(plan.temporal_overlap_count == 0)
    plan.text_overlap_prevented = bool(plan.temporal_overlap_count == 0 and plan.text_layer_count_final <= 1)
    if plan.temporal_overlap_count > 0:
        logger.warning(
            "VPI_ASS_TEMPORAL_OVERLAP_REMAINING clip_id=%s overlap_count=%d max_simultaneous=%d "
            "min_gap=%.4f events=%d",
            clip_id,
            plan.temporal_overlap_count,
            plan.max_simultaneous_dialogues,
            plan.min_gap_between_events,
            len(plan.events),
        )
    else:
        logger.info(
            "VPI_ASS_TEMPORAL_OVERLAP_PREVENTED clip_id=%s overlap_count=%d max_simultaneous=%d "
            "min_gap=%.4f events=%d",
            clip_id,
            plan.temporal_overlap_count,
            plan.max_simultaneous_dialogues,
            plan.min_gap_between_events,
            len(plan.events),
        )

    logger.info(
        "VPI_CAPTION_POLISH_PROFILE_SELECTED profile=%s timebase=%s corrected=%s",
        plan.caption_polish_profile,
        plan.caption_timebase_source,
        str(plan.caption_timebase_corrected).lower(),
    )
    if plan.caption_linebreak_polish_applied:
        logger.info(
            "VPI_CAPTION_LINEBREAK_POLISHED profile=%s protected=%s orphan_avoided=%s",
            plan.caption_polish_profile,
            str(caption_protected_phrases_preserved).lower(),
            str(caption_orphan_words_avoided).lower(),
        )
    if plan.caption_timing_polish_applied:
        logger.info(
            "VPI_CAPTION_TIMING_POLISHED profile=%s min=%.2f max=%.2f fast_adjusted=%s",
            plan.caption_polish_profile,
            caption_min_duration,
            caption_max_duration,
            str(caption_too_fast_adjusted).lower(),
        )
    if plan.caption_keyword_highlight_count:
        logger.info(
            "VPI_CAPTION_HIGHLIGHT_APPLIED count=%d policy=%s",
            plan.caption_keyword_highlight_count,
            caption_highlight_policy,
        )
    if plan.caption_visual_conflict_avoided:
        logger.info(
            "VPI_CAPTION_VISUAL_CONFLICT_AVOIDED hook=%s cta=%s broll=%s",
            str(caption_hook_conflict_avoided).lower(),
            str(caption_cta_conflict_avoided).lower(),
            str(caption_broll_conflict_avoided).lower(),
        )
    if caption_sync_warning:
        logger.warning(
            "VPI_CAPTION_SYNC_WARNING timebase=%s warning=%s",
            plan.caption_timebase_source,
            caption_sync_warning,
        )
    if not caption_duration_balance_ok or not caption_orphan_words_avoided or not caption_protected_phrases_preserved:
        plan.caption_polish_partial = True
        plan.warnings.append("caption_polish_partial")
        logger.warning(
            "VPI_CAPTION_POLISH_WARNING profile=%s duration_ok=%s orphan_ok=%s protected_ok=%s",
            plan.caption_polish_profile,
            str(caption_duration_balance_ok).lower(),
            str(caption_orphan_words_avoided).lower(),
            str(caption_protected_phrases_preserved).lower(),
        )

    # 6. Validate
    plan.validate()
    if premium:
        logger.info("VPI_PREMIUM_CAPTIONS_STYLE_APPLIED backend=vpi_ass style=vpi_clean palette=white_premium")

    return plan


def build_ass_subtitle_text(
    words: List[Dict[str, Any]],
    caption_style: str = "karaoke",
    emphasis_indices: Optional[List[int]] = None,
    caption_polish_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the ASS subtitle text string for a list of words.

    This is a lightweight helper that produces just the text portion
    of an ASS dialogue event, without the full plan structure.

    Args:
        words: List of word dicts with 'text', 'start', 'end', 'score'.
        caption_style: ASS caption style.
        emphasis_indices: Indices of words to emphasise.

    Returns:
        ASS-escaped text string with inline tags.
    """
    emphasis_set = set(emphasis_indices or [])
    keyword_terms = _select_vpi_caption_keywords(words)
    if isinstance(caption_polish_profile, dict) and not bool(caption_polish_profile.get("keyword_highlight_allowed", True)):
        keyword_terms = []

    if caption_style == "highlight":
        parts: List[str] = []
        for i, w in enumerate(words):
            text = _ass_escape(w.get("text", ""))
            token = _caption_word_token(w.get("text", ""))
            score = w.get("score", 0.5)
            if score >= 0.82 or i in emphasis_set:
                parts.append(f"{{\\c{ASS_WHITE}\\b1}}{text}{{\\r}}")
            elif token in keyword_terms:
                parts.append(f"{{\\c{ASS_SOFT_WHITE}\\b1\\fscx106\\fscy106}}{text}{{\\c{ASS_WHITE}\\b0}}")
            else:
                parts.append(f"{{\\alpha&H40&}}{text}{{\\alpha&H00&}}")
        return " ".join(parts)
    else:
        return _wrap_two_lines(words, emphasis_threshold=0.82, emphasis_colour=ASS_WHITE, keyword_terms=keyword_terms, font_size=72, caption_polish_profile=caption_polish_profile)
