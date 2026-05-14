"""
Jump-Cut Engine — silence detection + filler word removal.

Uses FFmpeg silencedetect filter to find gaps and transcript word-level
timings to identify filler words, then produces a jump-cut version of the clip.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
from src import gpu_utils

logger = logging.getLogger(__name__)

# Filler words to cut by default
DEFAULT_FILLERS = {
    "um", "uh", "uh-huh", "umm", "uhh", "er", "err", "hmm", "hm",
    "like", "you know", "i mean", "right", "okay so", "so like",
    "basically", "literally", "actually", "honestly", "anyway",
}

# Silence detection defaults
DEFAULT_SILENCE_THRESH_DB = -35   # dB below which audio is considered silent
DEFAULT_SILENCE_MIN_DUR   = 0.4   # seconds; gaps shorter than this are kept
DEFAULT_PAD_SECONDS       = 0.05  # pad each kept segment so cuts aren't jarring


@dataclass
class Segment:
    start: float
    end: float
    reason: str = "keep"   # keep | silence | filler

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class JumpCutResult:
    output_path: str
    original_duration: float
    output_duration: float
    segments_removed: int
    time_saved: float              # seconds
    filler_words_removed: int
    silence_gaps_removed: int
    cut_list: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def compression_ratio(self) -> float:
        if self.original_duration <= 0:
            return 1.0
        return self.output_duration / self.original_duration


async def detect_silence(
    video_path: str,
    threshold_db: float = DEFAULT_SILENCE_THRESH_DB,
    min_duration: float = DEFAULT_SILENCE_MIN_DUR,
) -> List[Tuple[float, float]]:
    """Return list of (start, end) silence intervals via FFmpeg silencedetect."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        info = json.loads(stdout.decode())
        total_dur = float(info.get("format", {}).get("duration", 0))
    except Exception:
        total_dur = 0.0

    detect_cmd = [
        "ffmpeg", "-v", "quiet",
        "-i", video_path,
        "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
        "-f", "null", "-",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *detect_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        output = stderr.decode()
    except Exception as exc:
        logger.debug("silencedetect failed: %s", exc)
        return []

    silences: List[Tuple[float, float]] = []
    starts: List[float] = []
    for line in output.splitlines():
        m = re.search(r"silence_start: ([0-9.]+)", line)
        if m:
            starts.append(float(m.group(1)))
        m = re.search(r"silence_end: ([0-9.]+)", line)
        if m and starts:
            silences.append((starts.pop(), float(m.group(1))))

    # Handle trailing silence (no silence_end)
    if starts and total_dur > 0:
        silences.append((starts[0], total_dur))

    return silences


def find_filler_segments(
    words: List[Dict[str, Any]],
    filler_set: Optional[set] = None,
    pad: float = 0.02,
) -> List[Tuple[float, float]]:
    """Return (start, end) intervals for filler words from word-level transcript."""
    fillers = filler_set if filler_set is not None else DEFAULT_FILLERS
    results: List[Tuple[float, float]] = []
    i = 0
    w = [ww for ww in words if ww.get("word", "").strip()]
    while i < len(w):
        word_text = w[i].get("word", "").strip().lower().rstrip(".,!?")
        # Check 2-word filler phrases
        if i + 1 < len(w):
            two = word_text + " " + w[i + 1].get("word", "").strip().lower().rstrip(".,!?")
            if two in fillers:
                s = float(w[i].get("start", 0)) - pad
                e = float(w[i + 1].get("end", 0)) + pad
                results.append((max(0, s), e))
                i += 2
                continue
        if word_text in fillers:
            s = float(w[i].get("start", 0)) - pad
            e = float(w[i].get("end", 0)) + pad
            results.append((max(0, s), e))
        i += 1
    return results


def build_keep_segments(
    total_duration: float,
    remove_intervals: List[Tuple[float, float]],
    pad: float = DEFAULT_PAD_SECONDS,
) -> List[Tuple[float, float]]:
    """Invert remove_intervals into keep segments, merging overlaps."""
    if not remove_intervals:
        return [(0.0, total_duration)]

    # Sort and merge overlapping remove intervals
    merged: List[Tuple[float, float]] = []
    for s, e in sorted(remove_intervals):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append([s, e])

    keep: List[Tuple[float, float]] = []
    cursor = 0.0
    for s, e in merged:
        seg_start = cursor
        seg_end = s - pad
        if seg_end - seg_start > 0.05:
            keep.append((seg_start, seg_end))
        cursor = e + pad

    if total_duration - cursor > 0.05:
        keep.append((cursor, total_duration))

    return keep


async def _get_duration(video_path: str) -> float:
    """Get video duration via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
    except Exception:
        return 0.0


async def apply_jump_cuts(
    video_path: str,
    output_path: str,
    words: Optional[List[Dict[str, Any]]] = None,
    remove_fillers: bool = True,
    remove_silence: bool = True,
    silence_threshold_db: float = DEFAULT_SILENCE_THRESH_DB,
    silence_min_duration: float = DEFAULT_SILENCE_MIN_DUR,
    custom_fillers: Optional[List[str]] = None,
) -> JumpCutResult:
    """
    Apply jump cuts to a video: remove silence gaps and/or filler words.

    Args:
        video_path: Source clip path
        output_path: Destination path
        words: Word-level transcript (each dict needs start/end/word)
        remove_fillers: Whether to cut filler words from transcript
        remove_silence: Whether to cut silence detected by FFmpeg
        silence_threshold_db: dB threshold for silence
        silence_min_duration: Minimum silence duration to remove
        custom_fillers: Extra filler words beyond defaults
    """
    total_dur = await _get_duration(video_path)
    if total_dur <= 0:
        return JumpCutResult(
            output_path=output_path, original_duration=0,
            output_duration=0, segments_removed=0,
            time_saved=0, filler_words_removed=0,
            silence_gaps_removed=0,
            error="Could not read video duration",
        )

    remove_intervals: List[Tuple[float, float]] = []
    filler_count = 0
    silence_count = 0

    if remove_silence:
        silences = await detect_silence(video_path, silence_threshold_db, silence_min_duration)
        remove_intervals.extend(silences)
        silence_count = len(silences)
        logger.debug("[jump_cut] %d silence gaps detected", silence_count)

    if remove_fillers and words:
        filler_set = set(DEFAULT_FILLERS)
        if custom_fillers:
            filler_set.update(f.lower() for f in custom_fillers)
        filler_segs = find_filler_segments(words, filler_set)
        remove_intervals.extend(filler_segs)
        filler_count = len(filler_segs)
        logger.debug("[jump_cut] %d filler word segments detected", filler_count)

    keep_segs = build_keep_segments(total_dur, remove_intervals)

    if not keep_segs:
        keep_segs = [(0.0, total_dur)]

    if len(keep_segs) == 1 and keep_segs[0] == (0.0, total_dur):
        # Nothing to cut — just copy
        import shutil
        shutil.copy2(video_path, output_path)
        return JumpCutResult(
            output_path=output_path,
            original_duration=total_dur,
            output_duration=total_dur,
            segments_removed=0,
            time_saved=0.0,
            filler_words_removed=filler_count,
            silence_gaps_removed=silence_count,
            cut_list=[{"start": 0.0, "end": total_dur, "kept": True}],
        )

    # Build FFmpeg trim + concat filter
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir="/tmp"
    ) as flist:
        concat_list_path = flist.name
        for seg_start, seg_end in keep_segs:
            with tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False, dir="/tmp"
            ) as tmp:
                tmp_path = tmp.name
            flist.write(f"file '{tmp_path}'\n")

    # Use select/aselect trim approach via concat demuxer
    # Simpler: write a concat filter string
    n = len(keep_segs)
    inputs: List[str] = []
    for i, (seg_start, seg_end) in enumerate(keep_segs):
        inputs += ["-ss", str(seg_start), "-to", str(seg_end), "-i", video_path]

    filter_v = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
    filter_a = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[outa]"

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
        + [
            "-filter_complex", f"{filter_v};{filter_a}",
            "-map", "[outv]", "-map", "[outa]",
            *gpu_utils.ffmpeg_codec_flags("medium"),
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode()[-500:]
            logger.error("[jump_cut] FFmpeg error: %s", err)
            return JumpCutResult(
                output_path=output_path, original_duration=total_dur,
                output_duration=0, segments_removed=0,
                time_saved=0, filler_words_removed=filler_count,
                silence_gaps_removed=silence_count, error=err,
            )
    except Exception as exc:
        return JumpCutResult(
            output_path=output_path, original_duration=total_dur,
            output_duration=0, segments_removed=0,
            time_saved=0, filler_words_removed=filler_count,
            silence_gaps_removed=silence_count, error=str(exc),
        )

    output_dur = await _get_duration(output_path)
    time_saved = total_dur - output_dur
    cut_list = [{"start": s, "end": e, "kept": True} for s, e in keep_segs]

    logger.info(
        "[jump_cut] %s → %.1fs saved (%.0f%% of original), "
        "%d silence gaps, %d fillers removed",
        Path(video_path).name, time_saved,
        (time_saved / total_dur * 100) if total_dur else 0,
        silence_count, filler_count,
    )

    return JumpCutResult(
        output_path=output_path,
        original_duration=total_dur,
        output_duration=output_dur,
        segments_removed=silence_count + filler_count,
        time_saved=time_saved,
        filler_words_removed=filler_count,
        silence_gaps_removed=silence_count,
        cut_list=cut_list,
    )
