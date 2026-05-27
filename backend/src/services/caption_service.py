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

logger = logging.getLogger(__name__)


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


def _margin_v(platform: str) -> int:
    return _PLATFORM_MARGIN_V.get(platform.lower(), _PLATFORM_MARGIN_V["default"])


def _beta_clean_margin_v(platform: str) -> int:
    return int(os.environ.get("CAPTION_BETA_CLEAN_MARGIN_V", _margin_v(platform)))


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
        "font_size": int(os.environ.get("CAPTION_VPI_FONT_SIZE", "80")),
        "primary_colour": _WHITE,
        "highlight_colour": _VPI_ORANGE,
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
        "outline": 4,
        "shadow": 2,
        "alignment": 2,
        "margin_l": 10,
        "margin_r": 10,
        "margin_v": _PLATFORM_MARGIN_V["tiktok"],
        "anchor": "an5",
        "position_x_ratio": 0.5,
        "position_y_ratio": 0.78,
        "max_words_per_block": 4,
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


def _build_karaoke_text(words: List[WordTimestamp], emphasis_threshold: float = 0.82) -> str:
    """Build \\k-tagged karaoke text from word list with emphasis support."""
    parts = []
    for w in words:
        if _is_emphasis_word(w, emphasis_threshold):
            # High impact word: bright yellow + slightly larger
            parts.append(
                f"{{\\k{w.duration_cs}\\c{_YELLOW}\\fscx110\\fscy110}}{w.text}"
                f"{{\\c{_WHITE}\\fscx100\\fscy100}}"
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
            parts.append(f"{{\\c{_YELLOW}}}{text}{{\\c{_WHITE}}}")
        else:
            parts.append(text)
    return "{\\an2}" + " ".join(parts)


def _build_beta_clean_karaoke_text(
    words: List[WordTimestamp],
    pos_tag: str,
    highlight_colour: str = _VPI_ORANGE,
) -> str:
    """Single visual ASS event per block, with active word handled by karaoke timing."""
    parts = []
    for w in words:
        duration_cs = max(1, int(round(max(0.08, w.end - w.start) * 100)))
        parts.append(f"{{\\kf{duration_cs}\\c{highlight_colour}}}{w.text}{{\\c{_WHITE}}}")
    return pos_tag + " ".join(parts)


_ASS_OVERRIDE_RE = re.compile(r"\{[^}]*\}")


def _normalize_caption_text(text: str) -> str:
    return " ".join(_ASS_OVERRIDE_RE.sub("", text).lower().split())


def _build_highlight_text(words: List[WordTimestamp], active_idx: int, emphasis_threshold: float = 0.82) -> str:
    """
    Build per-word dialogue line where the active word gets a highlight override.
    Used for karaoke-highlight style — each dialogue event represents one word
    being highlighted while others are shown dimmed.

    Emphasis words (high score) use less transparency (H40) even when not active.
    Active words with emphasis use RED color to differentiate from standard active.
    """
    parts = []
    for i, w in enumerate(words):
        if i == active_idx:
            if _is_emphasis_word(w, emphasis_threshold):
                # Active + emphasis = RED color for high confidence words
                parts.append(f"{{\\c{_RED}\\bord0\\shad0\\p0}}{w.text}{{\\r}}")
            else:
                # Normal active = YELLOW
                parts.append(f"{{\\c{_YELLOW}\\bord0\\shad0\\p0}}{w.text}{{\\r}}")
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
) -> str:
    """
    Build a complete ASS script from caption lines.

    For 'karaoke' and 'tiktok' styles: one dialogue event per line using \\k tags.
    For 'highlight' style: one dialogue event PER WORD so each word can get its
                           own background-box highlight as it's spoken.

    platform: used to set platform-specific caption safe zones (MarginV).
              Supported: 'tiktok', 'reels', 'shorts', 'universal'.
    """
    beta_clean = _is_beta_clean()
    preset: Optional[Dict[str, Any]] = None
    if beta_clean:
        preset = _beta_clean_visual_preset()
        style = str(preset["caption_style"])
        margin_v = int(os.environ.get("CAPTION_BETA_CLEAN_MARGIN_V", preset["margin_v"]))
        style_def = _style_def_from_preset(preset, margin_v)
    else:
        style_def = _STYLE_DEFS.get(style, _STYLE_DEFS["tiktok"])
        margin_v = _margin_v(platform)
        style_def = style_def.replace("MARGINV", str(margin_v))
    is_highlight = (style == "highlight") and not beta_clean
    if beta_clean:
        assert preset is not None
        pos_x = int(os.environ.get(
            "CAPTION_VPI_POS_X",
            round(play_res_x * float(preset["position_x_ratio"])),
        ))
        pos_y = int(os.environ.get(
            "CAPTION_VPI_POS_Y",
            round(play_res_y * float(preset["position_y_ratio"])),
        ))
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
            min_duration_s = float(preset["min_duration_s"])
            max_duration_s = float(preset["max_duration_s"])
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

            text = _build_beta_clean_karaoke_text(
                words,
                pos_tag,
                str(preset["highlight_colour"]),
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
                text = _build_highlight_text(words, i, emphasis_threshold)
                events.append(
                    f"Dialogue: 0,{_ass_time(w.start)},{_ass_time(w.end)},"
                    f"Default,,0,0,0,,{text}"
                )
        else:
            # Full line with \\k timing
            text = _build_karaoke_text(words, emphasis_threshold)
            events.append(
                f"Dialogue: 0,{_ass_time(line.line_start)},{_ass_time(line.line_end)},"
                f"Default,,0,0,0,,{text}"
            )

    if beta_clean:
        logger.info("[caption-sync] dedupe removed=%d", dedupe_removed)
        logger.info("[caption-sync] overlap_fixed=%d", overlap_fixed)
        logger.info("[caption-sync] min_duration_applied=%d", min_duration_applied)

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
            # Break on sentence endings, gaps, max words, or max duration
            ends_sentence = any(last_text.endswith(p) for p in _SENTENCE_ENDINGS)
            if (
                ends_sentence
                or gap > gap_threshold
                or len(current) >= max_words_per_line
                or dur > max_line_duration
            ):
                force_break = True

        if force_break and current:
            line_end = current[-1].end if beta_clean else current[-1].end + 0.15
            if beta_clean:
                line_end = min(line_end, current[0].start + max_line_duration)
            lines.append(CaptionLine(
                words=current,
                line_start=current[0].start,
                line_end=line_end,
            ))
            current = []

        current.append(wt)

    if current:
        line_end = current[-1].end + (0.08 if beta_clean else 0.15)
        if beta_clean:
            line_end = min(line_end, current[0].start + max_line_duration)
        lines.append(CaptionLine(
            words=current,
            line_start=current[0].start,
            line_end=line_end,
        ))

    return lines


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
    # Extract emphasis indices from LangGraph decisions (positional override)
    emphasis_indices = (caption_decisions or {}).get("emphasis_indices")
    lines = segment_words_into_lines(words, max_words_per_line=max_words_per_line, emphasis_indices=emphasis_indices)
    if not lines:
        logger.warning("[caption] No words provided — skipping caption burn-in")
        return False

    ass_content = build_ass_script(
        lines, style=style, play_res_x=play_res_x, play_res_y=play_res_y,
        platform=platform, emphasis_threshold=emphasis_threshold,
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
