"""
Silence detection and auto-removal using FFmpeg silencedetect.
"""
import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SILENCE_THRESHOLD_DB = float(os.getenv("SILENCE_THRESHOLD_DB", "-35"))
SILENCE_MIN_DURATION = float(os.getenv("SILENCE_MIN_DURATION_S", "1.5"))
SILENCE_PADDING_S = float(os.getenv("SILENCE_PADDING_S", "0.15"))


async def _get_duration(path: Path) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", str(path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        return float(json.loads(stdout)["format"]["duration"])
    except Exception:
        return 60.0


async def detect_silences(audio_path: str) -> list[dict]:
    """Detect silences using FFmpeg silencedetect filter."""
    cmd = [
        "ffmpeg", "-y",
        "-i", audio_path,
        "-af", f"silencedetect=noise={SILENCE_THRESHOLD_DB}dB:d={SILENCE_MIN_DURATION}",
        "-f", "null", "-",
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    except asyncio.TimeoutError:
        logger.warning("[Silence] Detection timed out")
        return []

    output = stderr.decode("utf-8", errors="replace")
    silences = []
    current_start = None

    for line in output.splitlines():
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[-1].strip())
            except ValueError:
                pass
        elif "silence_end:" in line and current_start is not None:
            try:
                parts = line.split("|")
                end = float(parts[0].split("silence_end:")[-1].strip())
                duration = float(parts[1].split("silence_duration:")[-1].strip())
                silences.append({"start": current_start, "end": end, "duration": duration})
                current_start = None
            except (ValueError, IndexError):
                pass

    logger.info("[Silence] Found %d silences", len(silences))
    return silences


async def remove_silences_from_clip(
    clip_path: Path,
    output_path: Path,
    silences: list[dict],
) -> bool:
    """Remove silences from clip using concat demuxer."""
    if not silences:
        return False

    clip_duration = await _get_duration(clip_path)
    keep_segments = []
    cursor = 0.0

    for silence in sorted(silences, key=lambda s: s["start"]):
        seg_end = max(0.0, silence["start"] - SILENCE_PADDING_S)
        if seg_end > cursor + 0.1:
            keep_segments.append({"start": cursor, "end": seg_end})
        cursor = min(clip_duration, silence["end"] + SILENCE_PADDING_S)

    if cursor < clip_duration - 0.1:
        keep_segments.append({"start": cursor, "end": clip_duration})

    if not keep_segments:
        return False

    concat_file = Path(tempfile.mktemp(suffix=".txt"))
    tmp_segments = []

    try:
        with open(concat_file, "w") as f:
            for i, seg in enumerate(keep_segments):
                seg_path = clip_path.parent / f"_seg_{i}_{clip_path.stem}.mp4"
                tmp_segments.append(seg_path)
                cmd_seg = [
                    "ffmpeg", "-y",
                    "-ss", str(seg["start"]), "-to", str(seg["end"]),
                    "-i", str(clip_path), "-c", "copy", str(seg_path),
                ]
                proc = await asyncio.create_subprocess_exec(
                    *cmd_seg, stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.wait_for(proc.communicate(), timeout=30.0)
                if seg_path.exists():
                    f.write(f"file '{seg_path}'\n")

        cmd_concat = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_file), "-c", "copy", str(output_path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd_concat, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=60.0)

        removed_s = sum(s["duration"] for s in silences)
        logger.info("[Silence] Removed %.1fs (%d cuts)", removed_s, len(silences))
        return output_path.exists()

    except Exception as exc:
        logger.warning("[Silence] Removal failed: %s", exc)
        return False
    finally:
        concat_file.unlink(missing_ok=True)
        for p in tmp_segments:
            p.unlink(missing_ok=True)
