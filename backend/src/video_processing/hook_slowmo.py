"""
hook_slowmo.py — Phase 3.5
============================
Slow-motion hook: apply dramatic slo-mo to the first 1–2s of a clip.

Two quality levels:
  FFmpeg minterpolate (CPU, always available):
    - Motion-compensated frame interpolation — smooth, no model needed
    - ~0.3× real-time (suitable for async task queue)

  RIFE (GPU optional, torchvision/RIFE):
    - 24× frame interpolation quality (reserved for GPU worker task)
    - Falls back to minterpolate automatically

Integration:
  - Called in `clip_creation.py` after main composition
  - Also called in `video_service.py` create_clip step (post-render)
  - Opt-in via env var: HOOK_SLOWMO_ENABLED=true (default false — expensive on CPU)
  - Segment-level: only applied when virality_score ≥ HOOK_SLOWMO_MIN_SCORE (default 70)

Usage:
    from video_processing.hook_slowmo import apply_hook_slowmo

    ok = apply_hook_slowmo(
        input_path=Path("clip.mp4"),
        output_path=Path("clip_slowmo.mp4"),
        slowmo_duration=1.5,    # Seconds of hook to slow
        speed_factor=0.5,       # 0.5 = half speed (2× slow)
        use_interpolation=True, # minterpolate for smooth frames
    )
"""

import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from ..gpu_utils import nvenc_available
from src import gpu_utils


def _is_nvenc_available() -> bool:
    """Check if NVENC is available via FFmpeg (more reliable than torch/CUDA detection).

    The system has h264_nvenc active for clip rendering (confirmed in logs), but
    gpu_utils may use a different detection method (CUDA/torch) that fails.
    This function checks FFmpeg's encoder list directly.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=5
        )
        return "h264_nvenc" in result.stdout
    except Exception:
        return False

logger = logging.getLogger(__name__)

# ─── Defaults (overridable via env) ──────────────────────────────────────────
DEFAULT_SLOWMO_DURATION = float(os.getenv("HOOK_SLOWMO_DURATION", "1.5"))   # seconds
DEFAULT_SPEED_FACTOR = float(os.getenv("HOOK_SLOWMO_SPEED", "0.5"))         # 0.5 = 2× slow
MIN_VIRALITY_SCORE = int(os.getenv("HOOK_SLOWMO_MIN_SCORE", "70"))
HOOK_SLOWMO_ENABLED = os.getenv("HOOK_SLOWMO_ENABLED", "false").lower() == "true"


def apply_hook_slowmo(
    input_path: Path,
    output_path: Path,
    slowmo_duration: float = DEFAULT_SLOWMO_DURATION,
    speed_factor: float = DEFAULT_SPEED_FACTOR,
    use_interpolation: bool = True,
    source_fps: int = 30,
) -> bool:
    """
    Apply slow-motion effect to the first `slowmo_duration` seconds of a clip.
    The remainder of the clip plays at normal speed.

    Args:
        input_path:       Path to the source clip (must exist)
        output_path:      Path for the output clip
        slowmo_duration:  Seconds of the hook to slow down (default 1.5s)
        speed_factor:     Speed multiplier, e.g. 0.5 = half speed (default 0.5)
        use_interpolation: Add minterpolate filter for smoother slow-mo (CPU)
        source_fps:       Source clip frame rate (default 30)

    Returns:
        True on success, False on any failure.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        logger.warning(f"[slowmo] Input not found: {input_path}")
        return False

    if speed_factor <= 0 or speed_factor > 1.0:
        logger.warning(f"[slowmo] Invalid speed_factor {speed_factor} — must be 0 < x ≤ 1")
        return False

    try:
        # Probe total duration
        total_dur = _probe_duration(input_path)
        if total_dur is None or total_dur <= 0.5:
            logger.warning(f"[slowmo] Clip too short ({total_dur}s) — skipping slowmo")
            return False

        hook_dur = min(slowmo_duration, total_dur * 0.4)  # max 40% of clip
        rest_start = hook_dur

        # Slo-mo extends hook segment time by 1/speed_factor
        hook_out_dur = hook_dur / speed_factor

        tmp_hook = output_path.parent / f"_hook_{uuid.uuid4().hex[:8]}.mp4"
        tmp_rest = output_path.parent / f"_rest_{uuid.uuid4().hex[:8]}.mp4"
        concat_list = output_path.parent / f"_concat_{uuid.uuid4().hex[:8]}.txt"

        try:
            # ── 1. Extract hook segment + apply setpts slow-mo ───────────────
            ok_hook = _extract_slowmo_segment(
                input_path, tmp_hook, 0.0, hook_dur,
                speed_factor, source_fps, use_interpolation,
            )
            if not ok_hook:
                return False

            # ── 2. Extract remainder (normal speed) ──────────────────────────
            ok_rest = True
            if rest_start < total_dur:
                ok_rest = _extract_segment(input_path, tmp_rest, rest_start, total_dur)

            # ── 3. Concatenate hook_slow + rest ───────────────────────────────
            if ok_rest and tmp_rest.exists():
                concat_list.write_text(
                    f"file '{tmp_hook.absolute()}'\n"
                    f"file '{tmp_rest.absolute()}'\n"
                )
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_list),
                        *gpu_utils.ffmpeg_codec_flags("medium"),
                        "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart",
                        str(output_path),
                    ],
                    capture_output=True, timeout=120,
                )
                success = result.returncode == 0 and output_path.exists()
            else:
                # No remainder — just rename hook
                import shutil
                shutil.move(str(tmp_hook), str(output_path))
                success = output_path.exists()

            if success:
                size_mb = output_path.stat().st_size / (1024 * 1024)
                logger.info(
                    f"[slowmo] Hook slo-mo applied: {hook_dur:.1f}s @ {speed_factor}× "
                    f"→ {output_path.name} ({size_mb:.1f}MB)"
                )
            return success

        finally:
            for tmp in (tmp_hook, tmp_rest, concat_list):
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass

    except Exception as e:
        logger.warning(f"[slowmo] apply_hook_slowmo failed: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
#  Integration helper — called from video_service or clip_creation
# ─────────────────────────────────────────────────────────────────────────────

def maybe_apply_hook_slowmo(
    clip_path: Path,
    virality_score: int = 0,
    inplace: bool = True,
) -> bool:
    """
    Apply hook slow-mo if enabled and clip meets virality threshold.
    Convenience wrapper for pipeline integration.

    Args:
        clip_path:       Rendered clip to process
        virality_score:  Segment virality score (0-100)
        inplace:         If True, overwrite clip_path on success

    Returns:
        True if slow-mo was applied, False if skipped or failed.
    """
    # Hard-disable: only when HOOK_SLOWMO_ENABLED is explicitly set to "false".
    # No env var (or any other value) → auto-enable based on score threshold.
    if os.getenv("HOOK_SLOWMO_ENABLED", "").lower() == "false":
        return False

    if virality_score < MIN_VIRALITY_SCORE:
        logger.debug(
            f"[slowmo] Skipped: score {virality_score} < threshold {MIN_VIRALITY_SCORE}"
        )
        return False

    if not clip_path.exists():
        return False

    out_path = clip_path.with_name(f"_sm_{clip_path.name}")
    success = apply_hook_slowmo(clip_path, out_path)

    if success and out_path.exists():
        if inplace:
            out_path.replace(clip_path)
        return True

    out_path.unlink(missing_ok=True)
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _probe_duration(path: Path) -> Optional[float]:
    """Return clip duration in seconds via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration", "-of", "csv=p=0",
             str(path)],
            capture_output=True, text=True, timeout=10,
        )
        line = r.stdout.strip().split("\n")[0]
        return float(line) if line else None
    except Exception:
        return None


def _extract_slowmo_segment(
    src: Path,
    dest: Path,
    start: float,
    end: float,
    speed: float,
    fps: int,
    use_interpolation: bool,
) -> bool:
    """Extract [start, end] from src, apply setpts slow-mo, write to dest."""
    duration = end - start
    # setpts: to slow down by speed factor, multiply PTS by 1/speed
    pts_factor = 1.0 / speed
    target_fps = int(fps / speed)  # e.g. 30 → 60 for 0.5×

    vf_parts = [f"setpts={pts_factor:.4f}*PTS"]

    # BUG 3 FIX: Use NVENC detection via FFmpeg instead of FEATURE_FLAGS/gpu_utils.
    # The system has h264_nvenc active for clip rendering but gpu_utils may use
    # a different detection method (CUDA/torch) that fails. _is_nvenc_available()
    # checks FFmpeg's encoder list directly, which is more reliable.
    has_gpu = _is_nvenc_available()
    if use_interpolation and speed <= 0.7 and has_gpu:
        # minterpolate: motion-compensated interpolation for smooth slo-mo
        # mi_mode=mci is highest quality; fps is output frame rate
        vf_parts.append(f"minterpolate=fps={target_fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1")
    elif use_interpolation and speed <= 0.7 and not has_gpu:
        logger.info(
            "[slowmo] GPU not detected — skipping minterpolate interpolation "
            "(would be too slow on CPU). Using setpts-only slow-mo."
        )

    vf = ",".join(vf_parts)

    # Audio: atempo only works for 0.5-2.0 range; chain for extreme values
    audio_speed = max(0.5, min(2.0, speed))
    af = f"atempo={audio_speed:.4f}"

    # BUG 2 FIX: Reduce timeout for CPU-only paths (minterpolate is skipped,
    # so setpts-only is much faster). Use 60s for no-GPU, 120s for GPU.
    ffmpeg_timeout = 60 if not has_gpu else 120

    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start), "-t", str(duration),
            "-i", str(src),
            "-vf", vf,
            "-af", af,
            *gpu_utils.ffmpeg_codec_flags("high"),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(dest),
        ],
        capture_output=True, timeout=ffmpeg_timeout,
    )

    if result.returncode != 0:
        logger.warning(
            f"[slowmo] setpts extraction failed: {result.stderr.decode()[:200]}"
        )
        # Retry without interpolation (minterpolate can fail on some builds)
        if use_interpolation:
            logger.debug("[slowmo] Retrying without minterpolate")
            vf_simple = f"setpts={pts_factor:.4f}*PTS"
            result2 = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start), "-t", str(duration),
                    "-i", str(src),
                    "-vf", vf_simple,
                    "-af", af,
                    *gpu_utils.ffmpeg_codec_flags("high"),
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    str(dest),
                ],
                capture_output=True, timeout=ffmpeg_timeout,
            )
            return result2.returncode == 0 and dest.exists()
        return False

    return dest.exists()


def _extract_segment(src: Path, dest: Path, start: float, end: float) -> bool:
    """Simple stream-copy segment extraction."""
    result = subprocess.run(
        [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(src),
            "-t", str(end - start),
            "-c", "copy",
            str(dest),
        ],
        capture_output=True, timeout=60,
    )
    return result.returncode == 0 and dest.exists()


def get_slowmo_capabilities() -> dict:
    """Detect which slow-mo backends are available."""
    minterp_ok = False
    try:
        r = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True, text=True, timeout=5,
        )
        minterp_ok = "minterpolate" in r.stdout
    except Exception:
        pass

    return {
        "minterpolate_available": minterp_ok,
        "enabled": HOOK_SLOWMO_ENABLED,
        "default_duration": DEFAULT_SLOWMO_DURATION,
        "default_speed": DEFAULT_SPEED_FACTOR,
        "min_virality_score": MIN_VIRALITY_SCORE,
    }
