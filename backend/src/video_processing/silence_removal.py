"""
Silence and filler-word removal via FFmpeg select/aselect filters.
Produces tighter jump-cut clips — silences > SILENCE_THRESHOLD are removed
and common filler words ("um", "uh", etc.) are cut out.

SILENCE_MODE env var controls behaviour:
  "cut"  (default) — hard-cut silences via select/aselect
  "ramp" — speed up silences 2x via setpts/atempo (smoother, less jarring)
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

SILENCE_THRESHOLD: float = 0.4   # seconds — gaps longer than this are removed
MIN_SILENCE_SAVINGS: float = 1.5  # only apply filter if we save at least this many seconds
SILENCE_MODE: str = os.environ.get("SILENCE_MODE", "cut").lower()  # "cut" | "ramp"
RAMP_SPEED: float = float(os.environ.get("SILENCE_RAMP_SPEED", "2.0"))  # 2x default

FILLER_WORDS = {
    "um", "uh", "er", "erm", "hmm", "hm", "mhm", "ah", "oh",
    "like", "basically", "literally", "actually", "right", "okay",
    "so", "well", "you know", "i mean", "i guess", "sort of", "kind of",
}


def build_keep_intervals(
    words: List[Dict[str, Any]],
    clip_duration: float,
    silence_threshold: float = SILENCE_THRESHOLD,
    pad_before: float = 0.05,
    pad_after: float = 0.08,
) -> Tuple[List[Tuple[float, float]], float]:
    """
    Given word-level timestamps build a list of (start, end) intervals to KEEP.
    Gaps > silence_threshold between consecutive keep-intervals are dropped.

    Returns:
        (intervals_to_keep, total_seconds_removed)
    """
    if not words:
        return [(0.0, clip_duration)], 0.0

    raw: List[Tuple[float, float]] = []
    for w in words:
        text = (w.get("word") or "").strip().lower().strip(",.!?;:")
        if text in FILLER_WORDS:
            continue
        w_start = max(0.0, float(w.get("start", 0.0)) - pad_before)
        w_end   = min(clip_duration, float(w.get("end",   0.0)) + pad_after)
        if w_end > w_start:
            raw.append((w_start, w_end))

    if not raw:
        return [(0.0, clip_duration)], 0.0

    raw.sort()

    # Merge intervals whose gap is below silence_threshold
    merged: List[List[float]] = [[raw[0][0], raw[0][1]]]
    for s, e in raw[1:]:
        gap = s - merged[-1][1]
        if gap <= silence_threshold:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    result = [
        (max(0.0, s), min(clip_duration, e))
        for s, e in merged
        if e > s
    ]

    total_kept    = sum(e - s for s, e in result)
    silence_saved = max(0.0, clip_duration - total_kept)
    return result, silence_saved


async def remove_silences(
    video_path: str,
    output_path: str,
    words: List[Dict[str, Any]],
    clip_duration: float,
    silence_threshold: float = SILENCE_THRESHOLD,
) -> bool:
    """
    Remove silences and filler words from a video via FFmpeg select/aselect.

    Returns True if the filter was applied and the output file created,
    False if skipped (not enough silence) or if FFmpeg failed.
    """
    intervals, silence_saved = build_keep_intervals(
        words, clip_duration, silence_threshold
    )

    if silence_saved < MIN_SILENCE_SAVINGS:
        logger.debug(
            f"[silence] {silence_saved:.1f}s removable — below {MIN_SILENCE_SAVINGS}s threshold, skipping"
        )
        return False

    if len(intervals) < 2:
        return False

    logger.info(
        f"[silence] Removing {silence_saved:.1f}s — {len(intervals)} keep-intervals "
        f"from {clip_duration:.1f}s clip"
    )

    select_parts = [f"between(t,{s:.4f},{e:.4f})" for s, e in intervals]
    select_expr  = "+".join(select_parts)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"select='{select_expr}',setpts=N/FRAME_RATE/TB",
        "-af", f"aselect='{select_expr}',asetpts=N/SR/TB",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
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
            logger.warning(f"[silence] FFmpeg select failed: {stderr.decode()[:400]}")
            return False
        if not Path(output_path).exists():
            return False
        logger.info(f"[silence] ✅ Jump-cut clip saved: {Path(output_path).name}")
        return True
    except Exception as exc:
        logger.warning(f"[silence] Exception: {exc}")
        return False


async def speed_ramp_silences(
    video_path: str,
    output_path: str,
    words: List[Dict[str, Any]],
    clip_duration: float,
    silence_threshold: float = SILENCE_THRESHOLD,
    ramp_speed: float = RAMP_SPEED,
) -> bool:
    """
    Speed-ramp silence sections instead of hard-cutting them.

    Speech segments play at 1x speed; gaps > silence_threshold play at
    ramp_speed (default 2x). Result is smoother than jump-cuts while still
    tightening the pacing.

    Uses FFmpeg complex filter with per-segment trim+setpts concat approach.
    Returns True on success, False if skipped or failed.
    """
    intervals, silence_saved = build_keep_intervals(
        words, clip_duration, silence_threshold
    )

    if silence_saved < MIN_SILENCE_SAVINGS or len(intervals) < 2:
        logger.debug(f"[ramp] {silence_saved:.1f}s removable — skipping speed ramp")
        return False

    logger.info(
        f"[ramp] Speed-ramping {silence_saved:.1f}s of silence at {ramp_speed}x "
        f"across {len(intervals)} speech segments"
    )

    # Build filter_complex: trim each interval + setpts for speech; for gaps use setpts speed
    # Strategy: trim each speech segment + speed-ramp each gap, then concat all
    filter_parts: List[str] = []
    segment_labels: List[str] = []

    total_segs = 0

    for i, (s, e) in enumerate(intervals):
        # Speech segment at 1x
        v_lbl = f"[vseg{i}]"
        a_lbl = f"[aseg{i}]"
        filter_parts.append(
            f"[0:v]trim=start={s:.4f}:end={e:.4f},setpts=PTS-STARTPTS{v_lbl}"
        )
        filter_parts.append(
            f"[0:a]atrim=start={s:.4f}:end={e:.4f},asetpts=PTS-STARTPTS{a_lbl}"
        )
        segment_labels.append((v_lbl, a_lbl))
        total_segs += 1

        # Gap after this segment (if not last)
        if i < len(intervals) - 1:
            gap_s = e
            gap_e = intervals[i + 1][0]
            if gap_e - gap_s > 0.05:
                vg_lbl = f"[vgap{i}]"
                ag_lbl = f"[agap{i}]"
                pts_factor = 1.0 / ramp_speed
                filter_parts.append(
                    f"[0:v]trim=start={gap_s:.4f}:end={gap_e:.4f},"
                    f"setpts={pts_factor:.4f}*(PTS-STARTPTS){vg_lbl}"
                )
                # atempo must be between 0.5 and 100; chain for extremes
                atempo_chain = _build_atempo_chain(ramp_speed)
                filter_parts.append(
                    f"[0:a]atrim=start={gap_s:.4f}:end={gap_e:.4f},"
                    f"asetpts=PTS-STARTPTS,{atempo_chain}{ag_lbl}"
                )
                segment_labels.append((vg_lbl, ag_lbl))
                total_segs += 1

    if total_segs < 2:
        return False

    # Concat: inputs must be interleaved [v0][a0][v1][a1]...
    interleaved = "".join(f"{v}{a}" for v, a in segment_labels)
    filter_parts.append(
        f"{interleaved}concat=n={total_segs}:v=1:a=1[vout][aout]"
    )

    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
        if proc.returncode != 0:
            logger.warning(f"[ramp] FFmpeg failed: {stderr.decode()[:400]}")
            return False
        if not Path(output_path).exists():
            return False
        logger.info(f"[ramp] ✅ Speed-ramped clip: {Path(output_path).name}")
        return True
    except Exception as exc:
        logger.warning(f"[ramp] Exception: {exc}")
        return False


def _build_atempo_chain(speed: float) -> str:
    """
    Build an atempo filter chain for the given speed multiplier.
    atempo only accepts 0.5–100; chain multiple for extremes.
    """
    # For speed > 2: chain atempo=2.0 filters
    # For speed < 0.5: chain atempo=0.5 filters
    parts = []
    remaining = speed
    if remaining > 1.0:
        while remaining > 2.0:
            parts.append("atempo=2.0")
            remaining /= 2.0
        parts.append(f"atempo={remaining:.4f}")
    elif remaining < 1.0:
        while remaining < 0.5:
            parts.append("atempo=0.5")
            remaining *= 2.0
        parts.append(f"atempo={remaining:.4f}")
    else:
        parts.append("atempo=1.0")
    return ",".join(parts)
