"""
TikTok Native Templates Service — Duet, Stitch, and Green-Screen overlays.

All three modes are implemented via FFmpeg filter_complex (CPU-only):

  duet        — split-screen: original left, reaction right (or vertical stack)
  stitch      — play first N seconds of original, then cut to reaction clip
  green_screen — chroma-key subject from reaction, composite over B-roll/background

No external dependencies beyond FFmpeg.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")


@dataclass
class TemplateResult:
    template: str           # duet | stitch | green_screen
    output_path: str
    width: int
    height: int
    duration: float
    success: bool
    error: str = ""


# ── Duet ──────────────────────────────────────────────────────────────────────

async def render_duet(
    original_path: str,
    reaction_path: str,
    output_path: str,
    layout: str = "side_by_side",      # side_by_side | stack
    target_w: int = 1080,
    target_h: int = 1920,
) -> TemplateResult:
    """
    Split-screen duet: original and reaction side-by-side (or stacked).
    Both clips are scaled to fill their half; audio is mixed 50/50.
    """
    half_w = target_w // 2 if layout == "side_by_side" else target_w
    half_h = target_h if layout == "side_by_side" else target_h // 2

    if layout == "side_by_side":
        fc = (
            f"[0:v]scale={half_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={half_w}:{target_h}:(ow-iw)/2:(oh-ih)/2[left];"
            f"[1:v]scale={half_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={half_w}:{target_h}:(ow-iw)/2:(oh-ih)/2[right];"
            f"[left][right]hstack=inputs=2[v];"
            f"[0:a][1:a]amix=inputs=2:duration=first:weights=0.5 0.5[a]"
        )
    else:
        fc = (
            f"[0:v]scale={target_w}:{half_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{half_h}:(ow-iw)/2:(oh-ih)/2[top];"
            f"[1:v]scale={target_w}:{half_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{half_h}:(ow-iw)/2:(oh-ih)/2[bottom];"
            f"[top][bottom]vstack=inputs=2[v];"
            f"[0:a][1:a]amix=inputs=2:duration=first:weights=0.5 0.5[a]"
        )

    cmd = [
        FFMPEG, "-y",
        "-i", original_path,
        "-i", reaction_path,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    return await _run_cmd(cmd, "duet", output_path, target_w, target_h)


# ── Stitch ─────────────────────────────────────────────────────────────────────

async def render_stitch(
    original_path: str,
    reaction_path: str,
    output_path: str,
    stitch_seconds: float = 5.0,
    target_w: int = 1080,
    target_h: int = 1920,
) -> TemplateResult:
    """
    Play first `stitch_seconds` of original (with text overlay), then cut to reaction.
    """
    # Step 1: Trim original to stitch_seconds
    tmp_orig = output_path.replace(".mp4", "_stitch_orig.mp4")
    tmp_react = output_path.replace(".mp4", "_stitch_react.mp4")

    scale_vf = (
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2"
    )

    # Scale + trim original
    cmd1 = [
        FFMPEG, "-y", "-i", original_path,
        "-t", str(stitch_seconds),
        "-vf", scale_vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        tmp_orig,
    ]
    # Scale reaction
    cmd2 = [
        FFMPEG, "-y", "-i", reaction_path,
        "-vf", scale_vf,
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        tmp_react,
    ]

    for cmd in (cmd1, cmd2):
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Stitch pre-process failed: %s", stderr.decode()[-300:])
            return TemplateResult("stitch", output_path, target_w, target_h, 0.0, False,
                                  "Pre-processing failed")

    # Concat: stitch clip + reaction
    list_file = Path(output_path).parent / "stitch_list.txt"
    list_file.write_text(f"file '{tmp_orig}'\nfile '{tmp_react}'\n")
    cmd3 = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        output_path,
    ]
    result = await _run_cmd(cmd3, "stitch", output_path, target_w, target_h)

    for tmp in (tmp_orig, tmp_react, str(list_file)):
        try:
            Path(tmp).unlink()
        except Exception:
            pass

    return result


# ── Green Screen ───────────────────────────────────────────────────────────────

async def render_green_screen(
    subject_path: str,
    background_path: str,
    output_path: str,
    chroma_color: str = "0x00FF00",    # hex green: 0x00FF00 | blue: 0x0000FF
    similarity: float = 0.30,
    blend: float = 0.05,
    target_w: int = 1080,
    target_h: int = 1920,
) -> TemplateResult:
    """
    Chroma-key the subject clip over the background clip.
    similarity: how close a colour must be to match (0-1, lower = stricter).
    blend: soft edge blend amount.
    """
    fc = (
        f"[1:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}[bg];"
        f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
        f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
        f"chromakey=color={chroma_color}:similarity={similarity}:blend={blend}[fg];"
        f"[bg][fg]overlay=0:0[v]"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", subject_path,
        "-i", background_path,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    return await _run_cmd(cmd, "green_screen", output_path, target_w, target_h)


# ── Subject-in-foreground (non-chroma, scale+overlay) ─────────────────────────

async def render_subject_over_broll(
    subject_path: str,
    background_path: str,
    output_path: str,
    subject_scale: float = 0.5,        # fraction of frame width
    position: str = "bottom_right",
    target_w: int = 1080,
    target_h: int = 1920,
) -> TemplateResult:
    """
    Scale subject to `subject_scale` of frame and overlay on background (no chroma key).
    Useful when background removal is not available.
    """
    sub_w = int(target_w * subject_scale)
    positions = {
        "bottom_right": (f"W-{sub_w}-20", f"H-h-20"),
        "bottom_left":  ("20", f"H-h-20"),
        "top_right":    (f"W-{sub_w}-20", "20"),
        "top_left":     ("20", "20"),
        "center":       ("(W-w)/2", "(H-h)/2"),
    }
    ox, oy = positions.get(position, positions["bottom_right"])

    fc = (
        f"[1:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
        f"crop={target_w}:{target_h}[bg];"
        f"[0:v]scale={sub_w}:-1[sub];"
        f"[bg][sub]overlay={ox}:{oy}[v]"
    )
    cmd = [
        FFMPEG, "-y",
        "-i", subject_path,
        "-i", background_path,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        output_path,
    ]
    return await _run_cmd(cmd, "subject_over_broll", output_path, target_w, target_h)


# ── Helper ────────────────────────────────────────────────────────────────────

async def _run_cmd(
    cmd: list[str],
    template: str,
    output_path: str,
    w: int,
    h: int,
) -> TemplateResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode()[-500:]
            logger.warning("%s template failed: %s", template, err)
            return TemplateResult(template, output_path, w, h, 0.0, False, err)

        # Probe duration
        dur = await _probe_duration(output_path)
        return TemplateResult(template, output_path, w, h, dur, True)
    except Exception as e:
        logger.warning("%s template error: %s", template, e)
        return TemplateResult(template, output_path, w, h, 0.0, False, str(e))


async def _probe_duration(path: str) -> float:
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return 0.0
