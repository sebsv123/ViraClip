"""Subtitle burning utilities for the video domain.

Generates word-level ASS subtitles (CapCut/TikTok style) and burns
them into video using ffmpeg. Also handles 9:16 vertical conversion.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from ... import gpu_utils
from ._helpers import get_ffmpeg_exe, seconds_to_ass_time

logger = logging.getLogger(__name__)


async def burn_subtitles_word_level(
    video_path: str,
    words: List[Dict[str, Any]],
    output_path: str,
    style: str = "viral",
) -> str:
    """
    Quema subtítulos estilo CapCut/TikTok con animación profesional:
    - 85px bold, shadow + outline grueso
    - Palabra activa en amarillo (o rojo si is_emphasis=True)
    - Animación pop-in: escala 80%→100% en 150ms via ASS \\t()
    - Máx 4 palabras por línea
    - Sin \\r resets (evita el bug libass con \\fscx + \\r)
    """
    if not words:
        logger.warning("[ASS] No words provided — skipping subtitle burn")
        return output_path

    ass_path = str(Path(video_path).with_suffix("")) + "_subtitles.ass"

    _fonts_dir = Path(__file__).parent.parent.parent / "fonts"
    # Prefer THEBOLDFONT (viral/Hormozi style), fall back in order
    _font_candidates = [
        ("THEBOLDFONT", "THEBOLDFONT.ttf"),
        ("BarlowCondensed-Bold", "BarlowCondensed-Bold.ttf"),
        ("TikTokSans", "TikTokSans-Regular.ttf"),
    ]
    _fontname = "Arial"
    for _fn, _ff in _font_candidates:
        if (_fonts_dir / _ff).exists():
            _fontname = _fn
            break

    # ASS colour codes (BBGGRR inline format, no alpha byte)
    _YELLOW = "&H00FFFF&"   # active word — yellow
    _ORANGE = "&H0066FF&"   # impact word — orange
    _RED = "&H0000FF&"      # emphasis word — red
    _WHITE = "&HFFFFFF&"    # inactive words — white
    _OUTLINE = "&H00000000"  # black outline (AABBGGRR)
    _SHADOW = "&HA0000000"   # semi-transparent black back box

    # Impact keywords → orange highlight (ES + EN)
    _IMPACT_WORDS = {
        "dinero", "money", "gratis", "free", "peligroso", "dangerous",
        "nuevo", "new", "secreto", "secret", "viral", "increible",
        "incredible", "importante", "important", "urgente", "urgent",
        "millones", "millions", "euros", "dolares", "dollars", "error",
        "hack", "truco", "trick", "boom", "clave", "key", "ahora", "now",
        "unico", "unique", "gratis", "lanzar", "launch", "exclusivo",
    }

    # pop-in bounce: 60%→115% in 100ms then settle to 100% by 200ms (MrBeast style)
    _POPIN = r"{\fscx60\fscy60\t(0,100,\fscx115\fscy115)\t(100,200,\fscx100\fscy100)}"

    ass_header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "Encoding: UTF-8\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        # Fontsize=105, Bold=1, Outline=8, Shadow=4, Alignment=2 (bottom-center)
        f"Style: Viral,{_fontname},105,&H0000FFFF,&H00FFFFFF,{_OUTLINE},"
        f"{_SHADOW},1,0,0,0,100,100,0,0,1,8,4,2,30,30,400,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    WORDS_PER_LINE = 3      # max words per group
    MAX_GAP_S = 0.35        # break group on short pauses
    MAX_SPAN_S = 1.8        # shorter groups = better sync
    events: List[str] = []

    # Build groups by TIME PROXIMITY, not word count.
    # This prevents a group from spanning a long pause, which causes perceived desync.
    all_valid = [w for w in words if (w.get("word") or "").strip()]
    groups: List[List[Dict]] = []
    current: List[Dict] = []
    _all_valid_list = list(all_valid)
    for _wi, w in enumerate(_all_valid_list):
        if not current:
            current.append(w)
            continue
        gap = float(w.get("start", 0)) - float(current[-1].get("end", 0))
        span = float(w.get("end", 0)) - float(current[0].get("start", 0))
        # Detectar inicio de oración: próxima palabra empieza con mayúscula y hay pausa
        _word_text = (w.get("word") or "").strip()
        _is_sentence_start = bool(_word_text) and _word_text[0].isupper()
        _has_natural_pause = gap > 0.2  # 200ms = pausa natural de oración
        if (len(current) >= WORDS_PER_LINE
                or gap > MAX_GAP_S
                or span > MAX_SPAN_S
                or (_is_sentence_start and _has_natural_pause)):
            groups.append(current)
            current = [w]
        else:
            current.append(w)
    if current:
        groups.append(current)

    for group in groups:
        # Filter out empty word entries
        valid = [w for w in group if (w.get("word") or "").strip()]
        if not valid:
            continue

        # ONE event per group — spans from first word start to last word end.
        g_start = float(valid[0].get("start", 0.0))
        g_end = float(valid[-1].get("end", g_start + 0.4 * len(valid)))
        if g_end <= g_start:
            g_end = g_start + 0.4 * len(valid)
        # Compensación de latencia de renderizado ASS (-33ms)
        _ASS_RENDER_OFFSET = -0.033
        g_start = max(0.0, g_start + _ASS_RENDER_OFFSET)
        g_end = max(g_start + 0.1, g_end + _ASS_RENDER_OFFSET)

        # Color: emphasis → red, impact keyword → orange, else → yellow
        parts: List[str] = []
        for w in valid:
            t = (w.get("word") or "").strip().upper()
            if not t:
                continue
            if bool(w.get("is_emphasis", False)):
                parts.append(f"{{\\c{_RED}}}{t}")
            elif t.lower() in _IMPACT_WORDS:
                parts.append(f"{{\\c{_ORANGE}}}{t}")
            else:
                parts.append(f"{{\\c{_YELLOW}}}{t}")

        if parts:
            line_text = _POPIN + " ".join(parts) + "{\\r}"
            events.append(
                f"Dialogue: 0,"
                f"{seconds_to_ass_time(g_start)},"
                f"{seconds_to_ass_time(g_end)},"
                f"Viral,,0,0,0,,{line_text}"
            )

    if not events:
        logger.warning("[ASS] 0 Dialogue events produced — skipping subtitle burn")
        return output_path

    ass_content = ass_header + "\n".join(events) + "\n"
    with open(ass_path, "w", encoding="utf-8-sig") as f:
        f.write(ass_content)

    logger.info(
        f"[ASS] {len(events)} group events written ({len(all_valid)} words, "
        f"max {WORDS_PER_LINE}/group, gap<{MAX_GAP_S}s, span<{MAX_SPAN_S}s)"
    )

    # Codec con aceleración hardware automática (NVENC/VAAPI/CPU)
    codec_flags = gpu_utils.ffmpeg_codec_flags()
    cmd = [
        get_ffmpeg_exe(), "-y", "-i", video_path,
        "-vf", f"ass={ass_path}:fontsdir=/app/fonts",
        *codec_flags,
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _stdout, _stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(
            f"[ASS] FFmpeg subtitle burn failed (exit {proc.returncode}): "
            f"{_stderr.decode()[:600]}"
        )
    else:
        logger.info(f"[ASS] ✅ Subtitles burned into {Path(output_path).name}")

    Path(ass_path).unlink(missing_ok=True)
    return output_path


async def crop_to_vertical_9_16(video_path: str, output_path: str) -> str:
    """Convierte video a 9:16 centrando horizontalmente (crop + pad)."""
    # Codec con aceleración hardware automática (NVENC/VAAPI/CPU)
    codec_flags = gpu_utils.ffmpeg_codec_flags()
    cmd = [
        get_ffmpeg_exe(), "-y", "-i", video_path,
        "-vf",
        "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        *codec_flags,
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    await proc.wait()
    return output_path
