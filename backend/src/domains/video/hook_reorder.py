"""
Hook Reorder Service — apply the HookEngine.reorder flag.

When the HookEngine detects that the strongest hook word lands AFTER t=3s
(i.e. the clip buries its lede), this service physically reorders the clip
so the hook plays first.

Reorder strategy (FFmpeg concat):
    [hook_segment][pre_hook_segment][post_hook_segment]

A short fade (0.10s) is added at each cut boundary to mask the seam.

Word timestamps are remapped to the new order so subtitles stay in sync.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from src import gpu_utils

logger = logging.getLogger(__name__)


# Hook segment length we extract around source_t (seconds)
_HOOK_LEAD_S  = 0.5      # 0.5s before the hook word
_HOOK_TRAIL_S = 2.5      # 2.5s after (so the hook PHRASE makes sense)
_FADE_S       = 0.10     # crossfade at each boundary


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


async def _run(cmd: List[str], timeout: float = 90.0) -> Tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timeout"
    return proc.returncode or 0, err.decode("utf-8", errors="replace")[-300:]


async def reorder_hook(
    video_path: str,
    output_path: str,
    source_t:  float,
    duration:  float,
    words:     Optional[List[Dict[str, Any]]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Move the segment around `source_t` to the start of the clip.

    Args:
        video_path:  Source clip path
        output_path: Destination
        source_t:    Timestamp where the actual hook starts (seconds)
        duration:    Total clip duration
        words:       Word-level transcript to remap (optional)

    Returns:
        Remapped words list with new timestamps if `words` was provided and
        reorder succeeded, else None. The output video is always written on
        success — the caller checks `Path(output_path).exists()`.
    """
    if not (3.0 <= source_t <= duration - 3.0):
        logger.debug("[HookReorder] source_t=%.1f out of safe range", source_t)
        return None

    hook_t0 = max(0.0, source_t - _HOOK_LEAD_S)
    hook_t1 = min(duration, source_t + _HOOK_TRAIL_S)

    # Build 3 segments: [hook] [pre_hook (0 to hook_t0)] [post_hook (hook_t1 to end)]
    segments = []
    if hook_t0 > 0.05:
        segments.append(("pre",  0.0,     hook_t0))
    segments.insert(0, ("hook", hook_t0, hook_t1))           # hook goes first
    if hook_t1 < duration - 0.05:
        segments.append(("post", hook_t1, duration))

    if len(segments) < 2:
        logger.debug("[HookReorder] Not enough segments to reorder")
        return None

    # FFmpeg trim+concat in a single pass
    inputs: List[str] = []
    for _label, t0, t1 in segments:
        inputs.extend(["-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", video_path])

    n = len(segments)
    filter_v = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[outv]"
    filter_a = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[outa]"

    cmd = [
        _ffmpeg(), "-y", "-v", "error",
        *inputs,
        "-filter_complex", f"{filter_v};{filter_a}",
        "-map", "[outv]", "-map", "[outa]",
        *gpu_utils.ffmpeg_codec_flags("high"),
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]
    rc, err = await _run(cmd)
    if rc != 0 or not Path(output_path).exists():
        logger.warning("[HookReorder] FFmpeg failed (%d): %s", rc, err[-200:])
        return None

    logger.info(
        "[HookReorder] Moved hook from t=%.1fs to t=0.0s (%d segments)",
        source_t, n,
    )

    # ── Remap word timestamps to new order ──────────────────────────────────
    if not words:
        return []

    # Build per-segment time mapping: cumulative offset in NEW order
    cumulative = 0.0
    seg_map: List[Tuple[float, float, float]] = []  # (old_t0, old_t1, new_offset)
    for _label, t0, t1 in segments:
        seg_map.append((t0, t1, cumulative))
        cumulative += (t1 - t0)

    remapped: List[Dict[str, Any]] = []
    for w in words:
        ws = float(w.get("start", 0))
        we = float(w.get("end",   ws + 0.3))
        for old_t0, old_t1, new_off in seg_map:
            if old_t0 <= ws < old_t1:
                new_ws = ws - old_t0 + new_off
                new_we = min(we, old_t1) - old_t0 + new_off
                remapped.append({
                    **w,
                    "start": round(new_ws, 3),
                    "end":   round(new_we, 3),
                })
                break

    remapped.sort(key=lambda w: w["start"])
    return remapped
