"""
Multi-Format Renderer — Genera automáticamente variantes para cada plataforma.

Por cada clip procesado, crea N variantes adaptadas a:
  - TikTok / Reels: 9:16, 60s máx, subtítulos grandes centered
  - YouTube Shorts: 9:16, hasta 60s, end screen últimos 5s
  - LinkedIn: 1:1, sin música agresiva, subtítulos profesionales
  - Twitter/X: 16:9 o 1:1, primeros 2s con hook muy fuerte
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src import gpu_utils

logger = logging.getLogger(__name__)


# ── Configuración por plataforma ──────────────────────────────────────────────

PLATFORM_CONFIG = {
    "tiktok": {
        "width": 1080,
        "height": 1920,
        "max_duration": 60,
        "caption_style": "big_center",
        "effects_intensity": "high",
        "end_screen": 0,
        "description": "TikTok — vertical 9:16, subtítulos grandes, ritmo rápido",
    },
    "reels": {
        "width": 1080,
        "height": 1920,
        "max_duration": 90,
        "caption_style": "elegant",
        "effects_intensity": "medium",
        "end_screen": 0,
        "description": "Instagram Reels — vertical 9:16, elegante, ritmo medio",
    },
    "shorts": {
        "width": 1080,
        "height": 1920,
        "max_duration": 60,
        "caption_style": "minimal",
        "effects_intensity": "low",
        "end_screen": 5,
        "description": "YouTube Shorts — vertical 9:16, minimal, end screen",
    },
    "linkedin": {
        "width": 1080,
        "height": 1080,
        "max_duration": 300,
        "caption_style": "professional",
        "effects_intensity": "minimal",
        "end_screen": 0,
        "description": "LinkedIn — cuadrado 1:1, profesional, sin música agresiva",
    },
    "twitter": {
        "width": 1920,
        "height": 1080,
        "max_duration": 140,
        "caption_style": "hook_first_2_20",
        "effects_intensity": "medium",
        "end_screen": 0,
        "description": "Twitter/X — horizontal 16:9, hook fuerte primeros segundos",
    },
}

# Mapa de estilos de caption por plataforma
CAPTION_STYLE_MAP = {
    "big_center": {
        "fontsize": 64,
        "x": "(w-text_w)/2",
        "y": "h-text_h-150",
        "box": 1,
        "boxcolor": "black@0.6",
    },
    "elegant": {
        "fontsize": 48,
        "x": "(w-text_w)/2",
        "y": "h-text_h-200",
        "box": 1,
        "boxcolor": "black@0.4",
    },
    "minimal": {
        "fontsize": 42,
        "x": "(w-text_w)/2",
        "y": "h-text_h-180",
        "box": 0,
        "boxcolor": "black@0",
    },
    "professional": {
        "fontsize": 36,
        "x": "60",
        "y": "h-text_h-120",
        "box": 1,
        "boxcolor": "black@0.3",
    },
    "hook_first_2_20": {
        "fontsize": 56,
        "x": "(w-text_w)/2",
        "y": "h/3",
        "box": 1,
        "boxcolor": "black@0.7",
    },
}


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _probe_duration(video_path: Path) -> float:
    """Return duration in seconds."""
    try:
        result = subprocess.run(
            [_get_ffmpeg_exe(), "-v", "error",
             "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(video_path)],
            capture_output=True, text=True, timeout=15,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _build_caption_filter(
    text: str,
    style: str,
    start: float = 0.0,
    end: float = 60.0,
    font_path: str = "/app/fonts/TikTokSans-Regular.ttf",
) -> str:
    """Build FFmpeg drawtext filter for given caption style."""
    cfg = CAPTION_STYLE_MAP.get(style, CAPTION_STYLE_MAP["minimal"])
    safe_text = text.replace("'", "'\\''").replace(":", "\\:")
    return (
        f"drawtext=fontfile={font_path}:"
        f"text='{safe_text}':"
        f"fontsize={cfg['fontsize']}:"
        f"fontcolor=white:"
        f"box={cfg['box']}:boxcolor={cfg['boxcolor']}:"
        f"x={cfg['x']}:y={cfg['y']}:"
        f"enable='between(t,{start},{end})'"
    )


def _build_end_screen_filter(
    duration: float,
    end_screen_dur: float = 5.0,
    text: str = "Follow for more!",
    font_path: str = "/app/fonts/TikTokSans-Regular.ttf",
) -> str:
    """Build end screen overlay (CTA + subscribe)."""
    start = max(0.0, duration - end_screen_dur)
    safe_text = text.replace("'", "'\\''")
    return (
        f"drawtext=fontfile={font_path}:"
        f"text='{safe_text}':fontsize=54:fontcolor=yellow:"
        f"box=1:boxcolor=black@0.8:boxborderw=20:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:"
        f"enable='between(t,{start},{duration})'"
    )


async def render_for_platform(
    input_path: Path,
    output_path: Path,
    platform: str,
    clip_text: str = "",
    hook_text: str = "",
    duration: Optional[float] = None,
) -> bool:
    """
    Render a clip variant for a specific platform.

    Args:
        input_path: Source clip
        output_path: Output path for the variant
        platform: One of "tiktok", "reels", "shorts", "linkedin", "twitter"
        clip_text: Full clip text for captions
        hook_text: First 2s hook text (for Twitter/X)
        duration: Override duration (capped by platform max)

    Returns:
        True on success
    """
    cfg = PLATFORM_CONFIG.get(platform)
    if not cfg:
        logger.error(f"[MultiFormat] Unknown platform: {platform}")
        return False

    probe_dur = _probe_duration(input_path) if duration is None else duration
    target_dur = min(probe_dur, cfg["max_duration"])

    w, h = cfg["width"], cfg["height"]
    filters: List[str] = []

    # Step 1: Scale/crop to platform aspect ratio (face-centered)
    if platform in ("tiktok", "reels", "shorts"):
        # 9:16 vertical — crop from center
        filters.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                       f"crop={w}:{h}[vcrop]")
    elif platform == "linkedin":
        # 1:1 square — crop from center
        size = min(w, h)
        filters.append(f"[0:v]scale={size}:{size}:force_original_aspect_ratio=increase,"
                       f"crop={size}:{size}[vcrop]")
    elif platform == "twitter":
        # 16:9 horizontal — crop from center
        filters.append(f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
                       f"crop={w}:{h}[vcrop]")
    else:
        filters.append(f"[0:v]null[vcrop]")

    prev_v = "[vcrop]"

    # Step 2: Captions per platform style
    if clip_text and cfg["caption_style"] != "hook_first_2_20":
        cf = _build_caption_filter(clip_text, cfg["caption_style"],
                                   start=0, end=target_dur)
        filters.append(f"{prev_v}{cf}[vcap]")
        prev_v = "[vcap]"
    elif clip_text and cfg["caption_style"] == "hook_first_2_20":
        # Twitter: hook text prominent in first 2:20
        hook_cf = _build_caption_filter(
            hook_text or clip_text[:100],
            "hook_first_2_20",
            start=0, end=min(2.5, target_dur),
        )
        filters.append(f"{prev_v}{hook_cf}[vcap]")
        prev_v = "[vcap]"

    # Step 3: End screen (Shorts only)
    if cfg["end_screen"] > 0 and target_dur > cfg["end_screen"] + 2:
        es = _build_end_screen_filter(target_dur, float(cfg["end_screen"]))
        filters.append(f"{prev_v}{es}[ves]")
        prev_v = "[ves]"

    # Step 4: Trim to max duration
    if probe_dur > target_dur:
        filters.append(f"{prev_v}trim=duration={target_dur}[vout]")
        prev_v = "[vout]"
    else:
        filters.append(f"{prev_v}null[vout]")
        prev_v = "[vout]"

    filter_complex = ";".join(filters)

    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-i", str(input_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", "0:a?",
        *gpu_utils.ffmpeg_codec_flags("high"),
        "-c:a", "aac", "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

        if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
            logger.info(f"[MultiFormat] ✅ {platform}: {output_path.name} "
                        f"({output_path.stat().st_size // 1024}KB, {target_dur:.0f}s)")
            return True
        else:
            logger.error(f"[MultiFormat] ❌ {platform} failed: {stderr.decode()[-500:]}")
            return False
    except asyncio.TimeoutError:
        logger.error(f"[MultiFormat] ⏱️ {platform} timed out")
        return False
    except Exception as e:
        logger.error(f"[MultiFormat] {platform} error: {e}")
        return False


async def render_all_platforms(
    input_path: Path,
    output_dir: Path,
    platforms: List[str],
    clip_text: str = "",
    hook_text: str = "",
    base_filename: str = "clip",
) -> Dict[str, Path]:
    """
    Render a clip for all specified platforms.

    Args:
        input_path: Source clip
        output_dir: Output directory
        platforms: List of platforms (e.g. ["tiktok", "reels", "shorts"])
        clip_text: Full clip text for captions
        hook_text: First 2s hook text
        base_filename: Base name for output files

    Returns:
        Dict of {platform: output_path} for successful renders
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results: Dict[str, Path] = {}

    tasks = []
    for platform in platforms:
        if platform not in PLATFORM_CONFIG:
            logger.warning(f"[MultiFormat] Skipping unknown platform: {platform}")
            continue
        suffix = PLATFORM_CONFIG[platform]["caption_style"]
        out_path = output_dir / f"{base_filename}_{platform}.mp4"
        tasks.append((
            platform,
            render_for_platform(
                input_path=input_path,
                output_path=out_path,
                platform=platform,
                clip_text=clip_text,
                hook_text=hook_text,
            ),
            out_path,
        ))

    for platform, coro, out_path in tasks:
        success = await coro
        if success:
            results[platform] = out_path

    logger.info(f"[MultiFormat] Complete: {len(results)}/{len(platforms)} platforms rendered")
    return results
