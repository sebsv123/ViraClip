"""
Narrative Arc Service — multi-clip series strategy.

Given a list of clips from the same source video, produces:
  1. Part-N sequencing  (Part 1/2/3 arc with optimal part boundaries)
  2. "Best-of" compilation (top-N clips by virality into single highlights reel)
  3. Teaser cut          (15s hook from the highest-virality moment)

All video operations use FFmpeg subprocess (CPU-only).
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
FFMPEG = os.getenv("FFMPEG_PATH", "ffmpeg")


@dataclass
class ClipMeta:
    clip_id: str
    file_path: str
    duration: float
    virality_score: float
    start_time: float = 0.0
    transcript: str = ""
    order: int = 0


@dataclass
class SeriesPart:
    part_number: int
    clips: list[ClipMeta]
    total_duration: float
    title: str = ""
    hook_text: str = ""


@dataclass
class NarrativeArcResult:
    strategy: str           # "series" | "best_of" | "teaser"
    parts: list[SeriesPart] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    description: str = ""


# ── Clip grouping logic ────────────────────────────────────────────────────────

def _assign_parts(
    clips: list[ClipMeta],
    max_part_duration: float = 60.0,
    max_parts: int = 5,
) -> list[SeriesPart]:
    """
    Greedily pack clips into parts not exceeding max_part_duration.
    Clips are ordered by their original `order` field.
    """
    sorted_clips = sorted(clips, key=lambda c: c.order)
    parts: list[SeriesPart] = []
    current_clips: list[ClipMeta] = []
    current_dur = 0.0

    for clip in sorted_clips:
        if current_dur + clip.duration > max_part_duration and current_clips:
            parts.append(SeriesPart(
                part_number=len(parts) + 1,
                clips=list(current_clips),
                total_duration=current_dur,
            ))
            current_clips = []
            current_dur = 0.0
        current_clips.append(clip)
        current_dur += clip.duration

    if current_clips:
        parts.append(SeriesPart(
            part_number=len(parts) + 1,
            clips=current_clips,
            total_duration=current_dur,
        ))

    # Cap at max_parts
    return parts[:max_parts]


def _select_best_of(
    clips: list[ClipMeta],
    n: int = 5,
    max_total_duration: float = 90.0,
) -> list[ClipMeta]:
    """Return top-N clips by virality_score that fit within max_total_duration."""
    ranked = sorted(clips, key=lambda c: -c.virality_score)
    selected: list[ClipMeta] = []
    total = 0.0
    for c in ranked:
        if total + c.duration <= max_total_duration:
            selected.append(c)
            total += c.duration
        if len(selected) >= n:
            break
    return sorted(selected, key=lambda c: c.order)


def _find_teaser_clip(clips: list[ClipMeta]) -> Optional[ClipMeta]:
    if not clips:
        return None
    return max(clips, key=lambda c: c.virality_score)


# ── FFmpeg concat helpers ──────────────────────────────────────────────────────

async def _concat_clips(
    clip_paths: list[str],
    output_path: str,
    tmp_dir: str = "/tmp",
) -> bool:
    """Concatenate video files using FFmpeg concat demuxer."""
    if not clip_paths:
        return False

    list_file = Path(tmp_dir) / f"concat_{Path(output_path).stem}.txt"
    list_file.write_text(
        "\n".join(f"file '{p}'" for p in clip_paths),
        encoding="utf-8",
    )
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("Concat failed: %s", stderr.decode()[-400:])
            return False
        return True
    except Exception as e:
        logger.warning("Concat error: %s", e)
        return False
    finally:
        try:
            list_file.unlink()
        except Exception:
            pass


async def _trim_clip(
    clip_path: str,
    output_path: str,
    duration: float = 15.0,
) -> bool:
    """Trim clip to `duration` seconds."""
    cmd = [
        FFMPEG, "-y", "-i", clip_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        return proc.returncode == 0
    except Exception as e:
        logger.warning("Trim error: %s", e)
        return False


# ── Main entry ────────────────────────────────────────────────────────────────

async def build_series(
    clips: list[ClipMeta],
    output_dir: str,
    title_prefix: str = "Part",
    max_part_duration: float = 60.0,
) -> NarrativeArcResult:
    """
    Pack clips into TikTok-length parts (≤60s) and concatenate each.
    Returns NarrativeArcResult with per-part output paths.
    """
    parts = _assign_parts(clips, max_part_duration=max_part_duration)
    output_paths: list[str] = []

    for part in parts:
        out = str(Path(output_dir) / f"series_part{part.part_number}.mp4")
        clip_paths = [c.file_path for c in part.clips if Path(c.file_path).exists()]
        if not clip_paths:
            continue
        success = await _concat_clips(clip_paths, out)
        if success:
            part.title = f"{title_prefix} {part.part_number}/{len(parts)}"
            part.hook_text = (
                part.clips[0].transcript[:80].strip() + "…"
                if part.clips and part.clips[0].transcript else ""
            )
            output_paths.append(out)

    return NarrativeArcResult(
        strategy="series",
        parts=parts,
        output_paths=output_paths,
        description=f"{len(parts)}-part series from {len(clips)} clips",
    )


async def build_best_of(
    clips: list[ClipMeta],
    output_dir: str,
    n: int = 5,
    max_total_duration: float = 90.0,
) -> NarrativeArcResult:
    """Concatenate top-N highest-virality clips into a single highlights reel."""
    selected = _select_best_of(clips, n=n, max_total_duration=max_total_duration)
    if not selected:
        return NarrativeArcResult(strategy="best_of", description="No clips available")

    out = str(Path(output_dir) / "best_of.mp4")
    clip_paths = [c.file_path for c in selected if Path(c.file_path).exists()]
    success = await _concat_clips(clip_paths, out)

    part = SeriesPart(
        part_number=1,
        clips=selected,
        total_duration=sum(c.duration for c in selected),
        title=f"Best of {len(selected)} clips",
    )
    return NarrativeArcResult(
        strategy="best_of",
        parts=[part],
        output_paths=[out] if success else [],
        description=f"Top-{len(selected)} clips by virality score",
    )


async def build_teaser(
    clips: list[ClipMeta],
    output_dir: str,
    teaser_duration: float = 15.0,
) -> NarrativeArcResult:
    """Extract a 15s teaser from the highest-virality clip."""
    best = _find_teaser_clip(clips)
    if not best or not Path(best.file_path).exists():
        return NarrativeArcResult(strategy="teaser", description="No valid clip found")

    out = str(Path(output_dir) / "teaser_15s.mp4")
    success = await _trim_clip(best.file_path, out, duration=teaser_duration)

    part = SeriesPart(
        part_number=1,
        clips=[best],
        total_duration=min(best.duration, teaser_duration),
        title=f"{int(teaser_duration)}s Teaser",
    )
    return NarrativeArcResult(
        strategy="teaser",
        parts=[part],
        output_paths=[out] if success else [],
        description=f"{int(teaser_duration)}s teaser from highest-virality clip (score={best.virality_score:.1f})",
    )
