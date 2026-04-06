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
        "Default,Montserrat-Bold,54,"
        f"{_WHITE},{_WHITE},{_BLACK},{_TRANSP},"
        "0,0,0,0,100,100,0,0,1,2,0,2,10,10,MARGINV,1"
    ),
    "neon": (
        "Default,Montserrat-Bold,66,"
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
    "tutorial":       "minimal",
    "interview":      "minimal",
    "education":      "minimal",
}


# ── ASS script builder ────────────────────────────────────────────────────────

def _ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp H:MM:SS.cc"""
    cs = int(round(seconds * 100))
    h  = cs // 360000;  cs %= 360000
    m  = cs // 6000;    cs %= 6000
    s  = cs // 100;     cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _build_karaoke_text(words: List[WordTimestamp]) -> str:
    """Build \\k-tagged karaoke text from word list."""
    parts = []
    for w in words:
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


def build_ass_script(
    lines: List[CaptionLine],
    style: str = "tiktok",
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    uppercase: bool = True,
    platform: str = "tiktok",
) -> str:
    """
    Build a complete ASS script from caption lines.

    For 'karaoke' and 'tiktok' styles: one dialogue event per line using \\k tags.
    For 'highlight' style: one dialogue event PER WORD so each word can get its
                           own background-box highlight as it's spoken.

    platform: used to set platform-specific caption safe zones (MarginV).
              Supported: 'tiktok', 'reels', 'shorts', 'universal'.
    """
    style_def = _STYLE_DEFS.get(style, _STYLE_DEFS["tiktok"])
    style_def = style_def.replace("MARGINV", str(_margin_v(platform)))
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

        if is_highlight:
            # One event per word — each word gets the highlight box while active
            for i, w in enumerate(words):
                text = _build_highlight_text(words, i)
                events.append(
                    f"Dialogue: 0,{_ass_time(w.start)},{_ass_time(w.end)},"
                    f"Default,,0,0,0,,{text}"
                )
        else:
            # Full line with \\k timing
            text = _build_karaoke_text(words)
            events.append(
                f"Dialogue: 0,{_ass_time(line.line_start)},{_ass_time(line.line_end)},"
                f"Default,,0,0,0,,{text}"
            )

    return header + "\n".join(events) + "\n"


# ── Caption line segmentation ─────────────────────────────────────────────────

def segment_words_into_lines(
    words: List[Dict[str, Any]],
    max_words_per_line: int = 5,
    max_line_duration: float = 4.0,
    gap_threshold: float = 0.8,
) -> List[CaptionLine]:
    """
    Group word-level timestamps into caption lines suitable for display.

    Splits on:
      - Word gaps > gap_threshold seconds (sentence breaks)
      - Lines that would exceed max_words_per_line
      - Lines that would exceed max_line_duration seconds

    Args:
        words: List of dicts with 'text', 'start', 'end' keys (Whisper format).
        max_words_per_line: Target max words per caption bubble.
        max_line_duration: Max display duration before forced split (seconds).
        gap_threshold: Gap between words (seconds) that triggers a line break.
    """
    if not words:
        return []

    wts = [
        WordTimestamp(
            text=re.sub(r"[^\w\s''-]", "", w.get("text", "")).strip(),
            start=float(w.get("start", 0)),
            end=float(w.get("end", 0)),
        )
        for w in words
        if w.get("text", "").strip()
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

    return lines


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
) -> bool:
    """
    Generate an ASS file from word timestamps and burn it into the video
    using FFmpeg's `subtitles` filter (libass rendering).

    Returns True on success, False on failure (video is still written as-is).
    """
    lines = segment_words_into_lines(words, max_words_per_line=max_words_per_line)
    if not lines:
        logger.warning("[caption] No words provided — skipping caption burn-in")
        return False

    ass_content = build_ass_script(
        lines, style=style, play_res_x=play_res_x, play_res_y=play_res_y,
        platform=platform,
    )

    # ── Subtitle QA: speed guard + emoji injection + profanity filter ──────────
    try:
        from ..video_processing.subtitle_qa import run_subtitle_qa as _run_qa
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
        vf = f"subtitles='{safe_ass}'{font_clause}"

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video_path),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
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
    ) -> bool:
        return await burn_captions(
            video_path, output_path, words,
            style=style, font_dir=font_dir, platform=platform,
        )

    def generate_ass(
        self,
        words: List[Dict[str, Any]],
        style: str = "tiktok",
        play_res_x: int = 1080,
        play_res_y: int = 1920,
        platform: str = "tiktok",
    ) -> str:
        """Return the raw ASS script string (for preview or saving)."""
        lines = segment_words_into_lines(words)
        return build_ass_script(lines, style=style,
                                play_res_x=play_res_x, play_res_y=play_res_y,
                                platform=platform)

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


_instance: Optional[CaptionService] = None


def get_caption_service() -> CaptionService:
    global _instance
    if _instance is None:
        _instance = CaptionService()
    return _instance
