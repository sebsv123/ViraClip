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
import re
import tempfile
from src import gpu_utils


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
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


def _margin_v(platform: str) -> int:
    return _PLATFORM_MARGIN_V.get(platform.lower(), _PLATFORM_MARGIN_V["default"])


# ── Style presets ─────────────────────────────────────────────────────────────
# MarginV is set to a placeholder string "MARGINV" that is substituted at
# script-build time with the platform-specific safe-zone value.

_STYLE_DEFS: Dict[str, str] = {
    # Name,Font,Size,Primary,Secondary,Outline,Back,Bold,Ital,Und,Stk,
    # ScX,ScY,Spacing,Angle,BorderStyle,Outline,Shadow,Align,MarL,MarR,MarV,Enc
    "karaoke": (
        "Default,TikTokSans-Bold,72,"
        f"{_WHITE},{_YELLOW},{_BLACK},{_SEMI_BG},"
        "-1,0,0,0,100,100,0,0,1,3,1,2,10,10,MARGINV,1"
    ),
    "highlight": (
        "Default,Montserrat-Bold,68,"
        f"{_BLACK},{_RED},{_BLACK},{_YELLOW},"
        "-1,0,0,0,100,100,0,0,3,0,0,2,10,10,MARGINV,1"
    ),
    "tiktok": (
        "Default,TikTokSans-Bold,80,"
        f"{_WHITE},{_YELLOW},{_BLACK},{_SEMI_BG},"
        "-1,0,0,0,100,100,1,0,1,4,2,2,10,10,MARGINV,1"
    ),
    "minimal": (
        "Default,Montserrat-Bold,64,"  # 54→64 más grande
        f"{_WHITE},{_WHITE},{_BLACK},{_SEMI_BG},"  # TRANSP→SEMI_BG fondo visible
        "-1,0,0,0,100,100,0,0,3,2,0,2,10,10,MARGINV,1"  # BorderStyle 1→3 para caja
    ),
    "neon": (
        "Default,Montserrat-Bold,66,"
        f"{_CYAN},{_WHITE},{_CYAN},{_SEMI_BG},"
        "-1,0,0,0,100,100,2,0,1,2,3,2,10,10,MARGINV,1"
    ),
    "clean_podcast": (
        "Default,Montserrat-Bold,64,"
        f"{_WHITE},{_YELLOW},{_BLACK},{_SEMI_BG},"
        "-1,0,0,0,100,100,0,0,3,2,0,2,10,10,MARGINV,1"
    ),
    "tiktok_loud": (
        "Default,Poppins-Bold,80,"
        f"{_WHITE},{_YELLOW},{_BLACK},{_SEMI_BG},"
        "-1,0,0,0,100,100,0,0,1,4,2,2,10,10,MARGINV,1"
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
    "clean_podcast":  "clean_podcast",
    "tiktok_loud":    "tiktok_loud",
    "minimal":        "minimal",
}


# ── ASS script builder ────────────────────────────────────────────────────────

def _ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc"""
    cs = int(round(seconds * 100))
    h  = cs // 360000;  cs %= 360000
    m  = cs // 6000;    cs %= 6000
    s  = cs // 100;     cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ── Emphasis word detection ───────────────────────────────────────────────────
# Words that should get visual emphasis in subtitles (claims, numbers, contrast,
# surprise markers). Only a few words per line get emphasis — never filler words
# or entire sentences.
_EMPHASIS_WORDS = {
    # English claims
    "never", "always", "secret", "truth", "lie", "hack", "shocking",
    "surprised", "incredible", "insane", "amazing", "unbelievable",
    "nobody", "everyone", "everybody", "worst", "best", "first",
    "last", "only", "real", "actual", "exposed", "revealed",
    "guaranteed", "proven", "scientific", "research", "study",
    "million", "billion", "thousand", "percent", "%",
    # Spanish claims
    "nunca", "siempre", "secreto", "verdad", "mentira", "increíble",
    "sorprendente", "impresionante", "alucinante", "brutal",
    "nadie", "todos", "peor", "mejor", "primero", "único",
    "real", "auténtico", "expuesto", "revelado",
    "millón", "millones", "mil", "ciento", "por ciento",
    # Numbers (digits)
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "10", "100", "1000",
    # Contrast / comparison
    "but", "however", "although", "instead", "rather",
    "pero", "sin embargo", "aunque", "en cambio", "al contrario",
}

_EMPHASIS_COLOR = "&H00FFFF&"  # yellow highlight for emphasis words


def _is_emphasis_word(text: str) -> bool:
    """Check if a word should get visual emphasis in subtitles."""
    clean = text.lower().strip(".,!?;:'\"¿¡()[]{}")
    if clean in _EMPHASIS_WORDS:
        return True
    # Check if it contains digits (numbers)
    if any(c.isdigit() for c in clean):
        return True
    return False


def _build_karaoke_text(words: List[WordTimestamp]) -> str:
    """Build \\k-tagged karaoke text from word list.
    
    Emphasis words (claims, numbers, contrast, surprise) get a yellow
    colour override for higher visual weight. Only a few words per line
    get emphasis — never filler words or entire sentences.
    """
    parts = []
    for w in words:
        if _is_emphasis_word(w.text):
            parts.append(f"{{\\c{_EMPHASIS_COLOR}\\k{w.duration_cs}}}{w.text}{{\\c}}")
        else:
            parts.append(f"{{\\k{w.duration_cs}}}{w.text}")
    return " ".join(parts)


def _build_highlight_text(words: List[WordTimestamp], active_idx: int) -> str:
    """
    Build per-word dialogue line where the active word gets a highlight override.
    Used for karaoke-highlight style — each dialogue event represents one word
    being highlighted while others are shown dimmed.
    """
    parts = []
    for i, w in enumerate(words):
        if i == active_idx:
            parts.append(f"{{\\c{_YELLOW}\\bord0\\shad0\\p0}}{w.text}{{\\r}}")
        else:
            parts.append(f"{{\\alpha&H80&}}{w.text}{{\\alpha&H00&}}")
    return " ".join(parts)


# ── Subtitle positioning constants (on 1920-tall canvas) ──────────────────────
# Lower third: 85% of frame height = 1632px (default subtitle zone)
# Upper third: 15% of frame height = 288px (when broll is active)
# Minimum vertical distance between simultaneous text elements: 120px
_SUBTITLE_Y_LOWER = 1632   # 0.85 * 1920
_SUBTITLE_Y_UPPER = 288    # 0.15 * 1920
_MIN_TEXT_GAP_PX = 120


def _subtitle_margin_v(
    line_start: float,
    line_end: float,
    platform_margin: int,
    caption_offset_y: int,
    broll_segments: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """
    Compute the per-line MarginV for a subtitle line.

    FIX 3: Hardcoded to 120 for ALL clips. Dynamic positioning based on
    broll overlap is disabled because it caused inconsistent vertical
    positioning across clips in the same task.
    """
    return 120


def build_ass_script(
    lines: List[CaptionLine],
    style: str = "tiktok",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    uppercase: bool = True,
    platform: str = "tiktok",
    caption_offset_y: int = 0,
    broll_segments: Optional[List[Dict[str, Any]]] = None,
    clip_start: float = 0.0,
) -> str:
    """
    Build a complete ASS script from caption lines.

    For 'karaoke' and 'tiktok' styles: one dialogue event per line using \k tags.
    For 'highlight' style: one dialogue event PER WORD so each word can get its
                           own background-box highlight as it's spoken.

    platform: used to set platform-specific caption safe zones (MarginV).
              Supported: 'tiktok', 'reels', 'shorts', 'universal'.
    caption_offset_y: additional vertical offset (px) to shift captions upward
                      (used when source video has burned-in subtitles).
    broll_segments: list of dicts with 'start_time' and 'duration' keys.
                    When a broll overlaps a subtitle line, the subtitle is
                    moved to the upper third of the frame to avoid overlap.
    clip_start: seconds to subtract from all timestamps so they are relative
                to the clip start (FIX 1: subtitle desync fix).
    """
    platform_margin = _margin_v(platform)
    style_def = _STYLE_DEFS.get(style, _STYLE_DEFS["tiktok"])
    style_def = style_def.replace("MARGINV", str(platform_margin + caption_offset_y))
    is_highlight = (style == "highlight")


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

    for line in lines:
        words = line.words
        if uppercase:
            words = [WordTimestamp(w.text.upper(), w.start, w.end) for w in words]

        # Compute per-line MarginV based on broll overlap
        line_margin_v = _subtitle_margin_v(
            line.line_start, line.line_end,
            platform_margin, caption_offset_y,
            broll_segments=broll_segments,
        )

        # FIX 1: Subtract clip_start so timestamps are relative to the clip
        line_start_rel = max(0.0, line.line_start - clip_start)
        line_end_rel = max(0.0, line.line_end - clip_start)

        if is_highlight:
            # One event per word — each word gets the highlight box while active
            for i, w in enumerate(words):
                w_start_rel = max(0.0, w.start - clip_start)
                w_end_rel = max(0.0, w.end - clip_start)
                text = _build_highlight_text(words, i)
                events.append(
                    f"Dialogue: 0,{_ass_time(w_start_rel)},{_ass_time(w_end_rel)},"
                    f"Default,,0,0,{line_margin_v},,{text}"
                )
        else:
            # Full line with \\k timing
            text = _build_karaoke_text(words)
            events.append(
                f"Dialogue: 0,{_ass_time(line_start_rel)},{_ass_time(line_end_rel)},"
                f"Default,,0,0,{line_margin_v},,{text}"
            )


    return header + "\n".join(events) + "\n"


# ── Caption line segmentation ─────────────────────────────────────────────────

def segment_words_into_lines(
    words: List[Dict[str, Any]],
    max_words_per_line: int = 5,
    max_line_duration: float = 4.0,
    gap_threshold: float = 0.8,
    language: str = "es",
    max_chars_per_line: int = 0,
) -> List[CaptionLine]:
    """
    Group word-level timestamps into caption lines suitable for display.

    Splits on:
      - Word gaps > gap_threshold seconds (sentence breaks)
      - Lines that would exceed max_words_per_line
      - Lines that would exceed max_line_duration seconds
      - Lines that would exceed max_chars_per_line characters (mobile-friendly)

    For Spanish (language="es"), reduces max_words_per_line to 3 and
    max_line_duration to 3.0s to prevent long Spanish phrases from
    overflowing the subtitle area. Also sets max_chars_per_line to 28
    (Spanish words are longer on average).

    Args:
        words: List of dicts with 'text', 'start', 'end' keys (Whisper format).
        max_words_per_line: Target max words per caption bubble.
        max_line_duration: Max display duration before forced split (seconds).
        gap_threshold: Gap between words (seconds) that triggers a line break.
        language: Language code ("es" for Spanish, "en" for English, etc.).
        max_chars_per_line: Max characters per line (0 = auto-detect based on language).
    """
    # Spanish subtitles need shorter lines: Spanish words are longer on average
    # (e.g., "excelentísimo" vs "excellent") and phrases need earlier breaks.
    if language == "es":
        max_words_per_line = min(max_words_per_line, 3)
        max_line_duration = min(max_line_duration, 3.0)
        gap_threshold = min(gap_threshold, 0.6)
        if max_chars_per_line == 0:
            max_chars_per_line = 28  # Spanish: shorter lines for mobile
    elif language == "en":
        if max_chars_per_line == 0:
            max_chars_per_line = 35  # English: slightly longer lines
    else:
        if max_chars_per_line == 0:
            max_chars_per_line = 30  # Other languages: moderate
    if not words:
        return []

    wts = [
        WordTimestamp(
            text=re.sub(r"[^\w\s'¿¡áéíóúüñÁÉÍÓÚÜÑ]", "", (w.get("text") or w.get("word") or "")).strip(),
            start=float(w.get("start", 0)),
            end=float(w.get("end", 0)),
        )
        for w in words
        if (w.get("text") or w.get("word") or "").strip()
    ]

    lines: List[CaptionLine] = []
    current: List[WordTimestamp] = []

    for i, wt in enumerate(wts):
        force_break = False
        if current:
            gap = wt.start - current[-1].end
            dur = wt.end - current[0].start
            if (
                gap > gap_threshold
                or len(current) >= max_words_per_line
                or dur > max_line_duration
            ):
                force_break = True

        if force_break and current:
            lines.append(CaptionLine(
                words=current,
                line_start=current[0].start,
                line_end=current[-1].end + 0.15,
            ))
            current = []

        current.append(wt)

    if current:
        lines.append(CaptionLine(
            words=current,
            line_start=current[0].start,
            line_end=current[-1].end + 0.15,
        ))

    # FIX 2: Prevent overlapping subtitle events — if end_time of event N
    # exceeds start_time of event N+1, clamp end_time of event N to
    # start_time of event N+1 - 0.05s (50ms minimum gap).
    for i in range(len(lines) - 1):
        if lines[i].line_end > lines[i + 1].line_start:
            lines[i].line_end = max(lines[i].line_start, lines[i + 1].line_start - 0.05)

    return lines


# ── Clip-index preset rotation ────────────────────────────────────────────────
# Rotate caption visual style per clip_index so consecutive clips in a batch
# look different (colour, size, animation feel).

CAPTION_PRESETS: List[Dict[str, Any]] = [
    # preset 0 — default TikTok look (white text, yellow highlight, large)
    {"color": _WHITE, "font_size_multiplier": 1.0, "animation": "karaoke"},
    # preset 1 — cyan text, slightly smaller, highlight-style
    {"color": _CYAN, "font_size_multiplier": 0.85, "animation": "highlight"},
    # preset 2 — golden text, bigger, neon-style
    {"color": _YELLOW, "font_size_multiplier": 1.15, "animation": "neon"},
]


# ── FFmpeg burn-in ────────────────────────────────────────────────────────────

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
    caption_offset_y: int = 0,
    clip_index: int = 0,
    clip_start: float = 0.0,
) -> bool:
    """
    Generate an ASS file from word timestamps and burn it into the video
    using FFmpeg's `subtitles` filter (libass rendering).

    When clip_index is provided, rotates through CAPTION_PRESETS to vary
    the visual style across consecutive clips in a batch.

    clip_start: seconds to subtract from all timestamps so they are relative
                to the clip start (FIX 1: subtitle desync fix).

    Returns True on success, False on failure (video is still written as-is).
    """
    # Rotate caption preset based on clip_index
    preset = CAPTION_PRESETS[clip_index % len(CAPTION_PRESETS)]
    style = preset["animation"]

    lines = segment_words_into_lines(words, max_words_per_line=max_words_per_line)
    if not lines:
        logger.warning("[caption] No words provided — skipping caption burn-in")
        return False

    ass_content = build_ass_script(
        lines, style=style, play_res_x=play_res_x, play_res_y=play_res_y,
        platform=platform, caption_offset_y=caption_offset_y,
        clip_start=clip_start,
    )

    # ── Subtitle QA: speed guard + emoji injection + profanity filter ──────────
    try:
        from ...video_processing.subtitle_qa import run_subtitle_qa as _run_qa
        _qa_result = _run_qa(ass_content, apply_fixes=True, inject_emoji=True, censor_profanity=False)
        if _qa_result.fixed_content:
            ass_content = _qa_result.fixed_content
        if _qa_result.issues:
            logger.debug("[caption] subtitle_qa issues: %s", _qa_result.issues)
    except Exception as _qa_e:
        logger.debug("[caption] subtitle_qa skipped: %s", _qa_e)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ass", delete=False, encoding="utf-8"
    ) as f:
        f.write(ass_content)
        ass_path = f.name

    try:
        # Escape path for FFmpeg filter string (colons must be escaped on Linux)
        safe_ass = ass_path.replace("\\", "/").replace(":", "\\:")
        font_clause = f":fontsdir={font_dir}" if font_dir else ""
        logger.info(
            "[SUBTITLE] ASS file generated at %s, size: %d bytes",
            ass_path, Path(ass_path).stat().st_size if Path(ass_path).exists() else 0,
        )
        # UTF-8 encoding for Spanish characters (á é í ó ú ñ ü ¿ ¡)
        vf = f"subtitles='{safe_ass}'{font_clause}:charenc=UTF-8"

        proc = await asyncio.create_subprocess_exec(
            _get_ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            *gpu_utils.ffmpeg_codec_flags("high"),
            "-c:a", "copy",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300.0)
        if proc.returncode != 0:
            logger.error("[caption] FFmpeg burn-in failed: %s", stderr.decode()[-500:])
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
        caption_offset_y: int = 0,
        clip_start: float = 0.0,
    ) -> bool:
        return await burn_captions(
            video_path, output_path, words,
            style=style, font_dir=font_dir, platform=platform,
            caption_offset_y=caption_offset_y,
            clip_start=clip_start,
        )

    def generate_ass(
        self,
        words: List[Dict[str, Any]],
        style: str = "tiktok",
        play_res_x: int = 1080,
        play_res_y: int = 1920,
        platform: str = "tiktok",
        caption_offset_y: int = 0,
        clip_start: float = 0.0,
    ) -> str:
        """Return the raw ASS script string (for preview or saving)."""
        lines = segment_words_into_lines(words)
        return build_ass_script(lines, style=style,
                                play_res_x=play_res_x, play_res_y=play_res_y,
                                platform=platform, caption_offset_y=caption_offset_y,
                                clip_start=clip_start)

    def segment_words(
        self,
        words: List[Dict[str, Any]],
        max_words_per_line: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return segmented caption lines as serialisable dicts."""
        lines = segment_words_into_lines(words, max_words_per_line=max_words_per_line)
        return [
            {
                "words": [{"text": w.text, "start": w.start, "end": w.end}
                           for w in line.words],
                "start": line.line_start,
                "end": line.line_end,
                "text": line.full_text,
            }
            for line in lines
        ]

    def get_styles(self) -> List[str]:
        return self.STYLES


# ── CAPTION_BACKEND routing factory ──────────────────────────────────────────

def _get_caption_backend() -> CaptionService:
    """
    Factory that returns the appropriate caption backend based on CAPTION_BACKEND.

    - "auto_subtitle" → AutoSubtitleBackend (AssemblyAI + confidence-based)
    - "legacy" (default) → CaptionService (ASS drawtext-based)

    If AutoSubtitleBackend fails at runtime, falls back dynamically to
    LegacyCaptionBackend for that clip.
    """
    from ...config import get_config
    cfg = get_config()
    backend_name = cfg.caption_backend

    if backend_name == "auto_subtitle":
        try:
            from ...services.subtitle_backend_auto import get_auto_subtitle_backend
            backend = get_auto_subtitle_backend()
            logger.info("[Caption] Using AutoSubtitleBackend (CAPTION_BACKEND=auto_subtitle)")
            return backend  # type: ignore[return-value]
        except Exception as exc:
            logger.warning(
                "[Caption] AutoSubtitleBackend init failed: %s — falling back to LegacyCaptionBackend",
                exc,
            )
            # Fall through to legacy

    if backend_name not in ("legacy", "auto_subtitle"):
        logger.warning(
            "[Caption] Unknown CAPTION_BACKEND='%s' — falling back to legacy",
            backend_name,
        )

    logger.info("[Caption] Using LegacyCaptionBackend (CAPTION_BACKEND=legacy)")
    return get_caption_service()


# ── Runtime fallback wrapper ─────────────────────────────────────────────────

async def burn_captions_with_fallback(
    video_path: Path,
    output_path: Path,
    words: List[Dict[str, Any]],
    style: str = "tiktok",
    font_dir: Optional[str] = None,
    platform: str = "tiktok",
    caption_offset_y: int = 0,
    clip_start: float = 0.0,
) -> bool:
    """
    Burn captions using the backend selected by CAPTION_BACKEND.

    If the selected backend fails at runtime, falls back dynamically to
    LegacyCaptionBackend for this clip.

    clip_start: seconds to subtract from all timestamps so they are relative
                to the clip start (FIX 1: subtitle desync fix).
    """
    backend = _get_caption_backend()

    # Check if this is an AutoSubtitleBackend instance
    is_auto = type(backend).__name__ == "AutoSubtitleBackend"

    try:
        if is_auto:
            # AutoSubtitleBackend has a different interface
            result = await backend.generate(
                video_path=str(video_path),
                output_path=str(output_path),
                words=words,
            )
            return bool(result)
        else:
            # Legacy CaptionService
            return await backend.burn(
                video_path=video_path,
                output_path=output_path,
                words=words,
                style=style,
                font_dir=font_dir,
                platform=platform,
                caption_offset_y=caption_offset_y,
                clip_start=clip_start,
            )
    except Exception as exc:
        logger.warning(
            "[Caption] %s failed: %s — falling back to LegacyCaptionBackend",
            type(backend).__name__,
            exc,
        )
        # Fallback to legacy
        fallback = get_caption_service()
        return await fallback.burn(
            video_path=video_path,
            output_path=output_path,
            words=words,
            style=style,
            font_dir=font_dir,
            platform=platform,
            caption_offset_y=caption_offset_y,
            clip_start=clip_start,
        )


_instance: Optional[CaptionService] = None


def get_caption_service() -> CaptionService:
    global _instance
    if _instance is None:
        _instance = CaptionService()
    return _instance
