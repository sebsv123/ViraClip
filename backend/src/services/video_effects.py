"""
Video Effects — Phase 9.10/9.11 Creative Engine

FFmpeg-based visual effects applied in a single post-render pass:
  - Zoom punch-in at audio peak timestamps (scale+crop, NOT zoompan)
  - Color grade / vignette from template preset (extra_vf_filters)
  - B-roll full-screen overlay at keyword event timestamps

NOTE: zoompan with d=1 was replaced by scale+crop to avoid the known FFmpeg bug
where d=1 forces frame-by-frame re-encoding, making the entire clip 10x slower.
The scale+crop approach evaluates between(t,...) inline and processes in one pass.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from .broll_compositor import compose_overlay_multi, probe_duration

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


def _is_image_path(path: str) -> bool:
    from pathlib import Path as _Path
    return _Path(path).suffix.lower() in _IMAGE_EXTS


_PUNCH_ZOOM    = 1.08   # 8% zoom for punch (was 1.04)
_PUNCH_DUR_S   = 0.18   # duration of each punch in seconds (was 0.25)
_MAX_PUNCHES   = 3      # cap (was 1)
_BROLL_MAX     = 8      # max B-roll overlays per clip (was 3)
_PUNCH_SAT     = 1.35   # saturation boost during punch


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
            zoom_vf = _build_zoom_punch(strong_peaks[:_MAX_PUNCHES], preset)
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


def _build_zoom_punch(peaks: list, preset) -> str:
    """
    Build FFmpeg scale+crop filters for zoom punch at audio peak timestamps.

    Replaces the old zoompan d=1 approach which caused a known FFmpeg bug:
    zoompan with d=1 forces per-frame re-encoding, making the whole clip 10x
    slower. This scale+crop method evaluates between(t,...) inline and runs
    in a single streaming pass with no frame buffering.

    Strategy: scale up by _PUNCH_ZOOM during punch interval → crop back to
    original resolution centered. Also applies a saturation boost during punch.
    """
    w, h   = getattr(preset, "resolution", (1080, 1920))
    peaks  = peaks[:_MAX_PUNCHES]

    z      = _PUNCH_ZOOM
    sw     = round(w * z)   # scaled width
    sh     = round(h * z)   # scaled height
    cx     = (sw - w) // 2  # crop x offset
    cy     = (sh - h) // 2  # crop y offset

    # Build one between() expression per punch interval
    in_punch = "+".join(
        f"between(t,{round(e.t, 3)},{round(e.t + _PUNCH_DUR_S, 3)})"
        for e in peaks
    )
    in_punch_expr = f"gt({in_punch},0)"   # 1 during any punch, 0 otherwise

    # scale: full size when punching, original size otherwise (then crop is a no-op)
    scale_w = f"if({in_punch_expr},{sw},{w})"
    scale_h = f"if({in_punch_expr},{sh},{h})"
    # crop x/y: offset during punch, 0 otherwise
    crop_x  = f"if({in_punch_expr},{cx},0)"
    crop_y  = f"if({in_punch_expr},{cy},0)"

    # saturation boost during punch via eq filter
    sat_expr = f"if({in_punch_expr},{_PUNCH_SAT},1)"

    return (
        f"scale='{scale_w}':'{scale_h}',"
        f"crop={w}:{h}:'{crop_x}':'{crop_y}',"
        f"eq=saturation='{sat_expr}'"
    )


# ── B-roll overlay ────────────────────────────────────────────────────────────

async def overlay_broll_clips(
    clip_path: Path,
    broll_pairs: "list[tuple]",  # [(TimelineEvent, BrollAsset), ...]
    output_path: Path,
    clip_duration: float = 0.0,
) -> "Path | None":
    """
    Overlay B-roll clips at their keyword event timestamps.
    Each B-roll is shown full-screen for event.duration + 1s seconds.

    Delegates to broll_compositor.compose_overlay_multi for format-adaptive
    scaling, fade-in/out and AV-safe PTS handling.

    Overlap protection: skips B-roll that overlaps hook (first 1.5s) or CTA (last 2s),
    and ensures B-roll slots don't overlap each other.

    Returns output_path on success, None on error or if no pairs.
    """
    if not broll_pairs:
        return None

    # Probe clip duration if not provided
    _dur = clip_duration or probe_duration(clip_path)
    _hook_guard = 1.5   # don't overlay B-roll in first 1.5s (hook protection)
    _cta_guard = 2.0    # don't overlay B-roll in last 2s (CTA protection)

    # Sort by timestamp and filter overlapping/protected slots
    sorted_pairs = sorted(broll_pairs, key=lambda x: x[0].t)
    filtered_pairs = []
    last_end = 0.0

    for event, asset in sorted_pairs[:_BROLL_MAX]:
        _start = event.t
        _dur_slot = min(3.0, max(1.5, event.duration))
        _end = _start + _dur_slot

        # Skip if overlaps hook guard (first 1.5s)
        if _start < _hook_guard:
            logger.debug("[BrollOverlay] Skipping slot at %.2fs (overlaps hook guard)", _start)
            continue

        # Skip if overlaps CTA guard (last 2s)
        if _start > (_dur - _cta_guard):
            logger.debug("[BrollOverlay] Skipping slot at %.2fs (overlaps CTA guard)", _start)
            continue

        # Skip if overlaps previous B-roll (min 0.5s gap)
        if _start < last_end + 0.5:
            logger.debug("[BrollOverlay] Skipping slot at %.2fs (overlaps previous B-roll)", _start)
            continue

        filtered_pairs.append((event, asset))
        last_end = _end

    if not filtered_pairs:
        logger.info("[BrollOverlay] No valid B-roll slots after overlap filtering")
        return None

    # Build (timestamp, path, duration) tuples for the compositor
    # Cap duration to 1.5-3.0s for TikTok/Reels standard (was 5-8s, too long)
    compositor_pairs = [
        (round(event.t, 3), asset.path, round(min(3.0, max(1.5, event.duration)), 3))
        for event, asset in filtered_pairs
    ]

    ok = await compose_overlay_multi(
        main_path=clip_path,
        broll_pairs=compositor_pairs,
        output_path=output_path,
        fade=0.6,
    )
    return output_path if ok else None
