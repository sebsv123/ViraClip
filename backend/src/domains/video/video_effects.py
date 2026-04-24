"""
Video Effects — Phase 9.10/9.11 Creative Engine

FFmpeg-based visual effects applied in a single post-render pass:
  - Zoom punch-in at audio peak timestamps (zoompan)
  - Color grade / vignette from template preset (extra_vf_filters)
  - B-roll full-screen overlay at keyword event timestamps
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from ...domains.broll.broll_compositor import compose_overlay_multi

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def _is_image_path(path: str) -> bool:
    from pathlib import Path as _Path
    return _Path(path).suffix.lower() in _IMAGE_EXTS


_PUNCH_ZOOM    = 1.04   # 4% zoom for punch
_PUNCH_DUR_S   = 0.25   # duration of each punch in seconds
_MAX_PUNCHES   = 1      # cap to keep filtergraph readable
_BROLL_MAX     = 3      # max B-roll overlays per clip


# ── Zoom punch + color grade ──────────────────────────────────────────────────

async def apply_preset_effects(
    clip_path: Path,
    preset,                   # RenderPreset (avoid circular import — duck-typed)
    peak_events: list,
    output_path: Path,
) -> "Path | None":
    """
    Apply template visual effects in one FFmpeg pass:
      - extra_vf_filters from preset (vignette, eq, etc.)
      - Zoom punch at audio-peak timestamps (if preset.zoom_punch_enabled)

    Returns output_path on success, None if nothing to apply or on error.
    """
    vf_parts: list[str] = []

    # Zoom punch — insert FIRST so color grade applies on top
    if getattr(preset, "zoom_punch_enabled", False) and peak_events:
        strong_peaks = [e for e in peak_events if e.type == "audio_peak" and e.strength >= 0.65]
        if strong_peaks:
            zoom_vf = _build_zoompan(strong_peaks[:_MAX_PUNCHES], preset)
            vf_parts.append(zoom_vf)

    # Color grade / vignette filters
    vf_parts.extend(getattr(preset, "extra_vf_filters", []))

    if not vf_parts:
        return None  # nothing to apply

    vf_chain = ",".join(vf_parts)
    tmp = Path(tempfile.mktemp(suffix=clip_path.suffix, dir=clip_path.parent))
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "quiet", "-y",
            "-i", str(clip_path),
            "-vf", vf_chain,
            "-c:a", "copy",
            str(tmp),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=300.0)
        if tmp.exists() and tmp.stat().st_size > 0:
            return tmp
        tmp.unlink(missing_ok=True)
        return None
    except (asyncio.TimeoutError, Exception) as exc:
        logger.debug("apply_preset_effects failed: %s", exc)
        tmp.unlink(missing_ok=True)
        return None


def _build_zoompan(peaks: list, preset) -> str:
    """
    Build an FFmpeg zoompan filter expression that briefly zooms to
    _PUNCH_ZOOM at each peak timestamp and returns to 1.0 in between.
    """
    w, h = getattr(preset, "resolution", (1080, 1920))
    fps   = getattr(preset, "fps", 30)
    peaks = peaks[:_MAX_PUNCHES]  # cap regardless of caller

    # between(t, start, end) returns 1 inside the interval, 0 outside
    interval_parts = "+".join(
        f"between(t,{round(e.t, 3)},{round(e.t + _PUNCH_DUR_S, 3)})"
        for e in peaks
    )
    zoom_expr = f"if(gt({interval_parts},0),{_PUNCH_ZOOM},1)"

    return (
        f"zoompan="
        f"zoom='{zoom_expr}':"
        f"x='iw/2-(iw/zoom/2)':"
        f"y='ih/2-(ih/zoom/2)':"
        f"d=1:"
        f"s={w}x{h}:"
        f"fps={fps}"
    )


# ── B-roll overlay ────────────────────────────────────────────────────────────

async def overlay_broll_clips(
    clip_path: Path,
    broll_pairs: "list[tuple]",  # [(TimelineEvent, BrollAsset), ...]
    output_path: Path,
) -> "Path | None":
    """
    Overlay B-roll clips at their keyword event timestamps.
    Each B-roll is shown full-screen for event.duration + 1s seconds.

    Delegates to broll_compositor.compose_overlay_multi for format-adaptive
    scaling, fade-in/out and AV-safe PTS handling.

    Returns output_path on success, None on error or if no pairs.
    """
    if not broll_pairs:
        return None

    pairs = broll_pairs[:_BROLL_MAX]

    # Build (timestamp, path, duration) tuples for the compositor
    compositor_pairs = [
        (round(event.t, 3), asset.path, round(max(3.5, event.duration + 2.0), 3))
        for event, asset in pairs
    ]

    ok = await compose_overlay_multi(
        main_path=clip_path,
        broll_pairs=compositor_pairs,
        output_path=output_path,
        fade=0.6,
    )
    return output_path if ok else None
