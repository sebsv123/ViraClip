"""
B-Roll Compositor — Format-Adaptive Overlay Engine con Efectos Inteligentes

Single source of truth for all B-roll compositing in ViraClip.
Integra sistema de efectos variados para evitar repetición.

Supported output formats (auto-probed from main clip):
  9:16  portrait  — 1080×1920, 720×1280
  1:1   square    — 1080×1080
  16:9  landscape — 1920×1080  (rare, kept for completeness)

Efectos inteligentes:
  - 13 tipos de efectos diferentes (Ken Burns, Pan, Rotate, Pulse, etc.)
  - Selección automática basada en contexto
  - Rotación para evitar repetición
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
sys.path.insert(0, "/app/src") if "/app/src" not in sys.path else None

logger = logging.getLogger(__name__)


def _sw_fallback(quality="high"):
    return ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22" if quality == "high" else "24"]


def _resolve_codec() -> callable:
    """
    Resolve the codec function based on environment flags:
      - If BROLL_FORCE_CPU=true → always use libx264
      - If VIRACLIP_ENABLE_NVENC=false → always use libx264
      - Otherwise → try NVENC via gpu_utils, fall back to libx264
    """
    _force_cpu = os.environ.get("BROLL_FORCE_CPU", "").lower() in ("1", "true", "yes")
    _beta_clean = os.environ.get("VIRACLIP_BETA_CLEAN", "").lower() in ("1", "true", "yes")
    _enable_nvenc = os.environ.get("VIRACLIP_ENABLE_NVENC", "false").lower() in ("1", "true", "yes")

    if _force_cpu:
        logger.info("[BrollCompositor] BROLL_FORCE_CPU=true — using libx264")
        return _sw_fallback
    if _beta_clean:
        logger.info("[BrollCompositor] VIRACLIP_BETA_CLEAN=true — using libx264")
        return _sw_fallback
    if not _enable_nvenc:
        logger.info("[BrollCompositor] VIRACLIP_ENABLE_NVENC=false — using libx264")
        return _sw_fallback

    try:
        from gpu_utils import ffmpeg_codec_flags as _raw_gpu_codec
        # Validate NVENC flags — if they contain -rc (unsupported in some FFmpeg builds),
        # fall back to software encoder for the entire broll_compositor module.
        _test = _raw_gpu_codec("medium")
        if "-rc" in _test:
            # Quick probe: does FFmpeg actually accept -rc?
            _probe = subprocess.run(
                ["ffmpeg", "-hide_banner", "-f", "lavfi", "-i", "nullsrc=s=16x16:d=0.1",
                 "-frames:v", "1", *_test, "-f", "null", "-"],
                capture_output=True, timeout=5,
            )
            if _probe.returncode != 0:
                logger.info("[BrollCompositor] NVENC -rc flag rejected — falling back to libx264")
                return _sw_fallback
        return _raw_gpu_codec
    except (ImportError, Exception) as exc:
        logger.info("[BrollCompositor] NVENC unavailable (%s) — using libx264", exc)
        return _sw_fallback


_gpu_codec = _resolve_codec()

import tempfile
from pathlib import Path
from typing import Optional, Tuple


def _get_ffmpeg_exe() -> str:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _uses_nvenc(codec_flags: list[str]) -> bool:
    return "h264_nvenc" in codec_flags


def _run_ffmpeg_sync_with_fallback(
    cmd: list[str],
    fallback_cmd: list[str],
    output_path: Path,
    log_prefix: str,
    timeout: int,
):
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if result.returncode == 0:
        return result
    if "h264_nvenc" not in cmd:
        return result

    logger.warning("[gpu] NVENC failed; retrying with libx264")
    logger.debug("%s NVENC stderr: %s", log_prefix, result.stderr.decode(errors="replace")[-400:])
    output_path.unlink(missing_ok=True)
    return subprocess.run(fallback_cmd, capture_output=True, timeout=timeout)


# Importar motor de efectos inteligentes
try:
    from .broll_effects_engine import get_smart_broll_effect, build_broll_effect_filter
    SMART_EFFECTS_AVAILABLE = True
except ImportError:
    SMART_EFFECTS_AVAILABLE = False
    logger.warning("Smart effects engine not available, using classic Ken Burns")

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}
_FFPROBE_TIMEOUT = 15   # seconds
_FFMPEG_TIMEOUT  = 180  # seconds per overlay


# ── Dimension probing ─────────────────────────────────────────────────────────

from dataclasses import dataclass


@dataclass(frozen=True)
class VideoGeometry:
    width: int
    height: int
    fps: float
    sar: "str | None" = None
    dar: "str | None" = None
    rotation: int = 0

    @property
    def effective_size(self) -> "Tuple[int, int]":
        """(w, h) after applying a 90/270 rotation (swap)."""
        if self.rotation in (90, 270, -90, -270):
            return self.height, self.width
        return self.width, self.height


def _parse_rate(rate: str) -> float:
    """Parse an ffprobe frame-rate string like '30000/1001' or '25/1'. 0.0 if invalid."""
    try:
        s = (rate or "").strip()
        if not s or s in ("0/0", "N/A"):
            return 0.0
        if "/" in s:
            num, den = s.split("/", 1)
            den_f = float(den)
            return round(float(num) / den_f, 3) if den_f else 0.0
        return round(float(s), 3)
    except Exception:
        return 0.0


def probe_video_geometry(
    path: "Path | str",
    *,
    retries: int = 3,
    timeout_s: float = 3.0,
) -> "VideoGeometry | None":
    """TIMING-39: canonical video-geometry probe. Returns VideoGeometry, or None if unknown.

    Uses ffprobe (NOT ffmpeg with ffprobe-only options like the old probe_dimensions, which
    always returned a hardcoded 1080x1920x30). Reads the video stream's width/height,
    avg_frame_rate (→ r_frame_rate fallback), sample/display aspect ratios and rotation. Never
    fabricates a fallback — callers must treat None as 'unknown'.
    """
    import time as _t
    p = str(path)
    exe = _get_ffprobe_exe()
    for attempt in range(max(1, retries)):
        try:
            r = subprocess.run(
                [exe, "-v", "error", "-select_streams", "v:0",
                 "-show_streams", "-of", "json", p],
                capture_output=True, text=True, timeout=timeout_s,
            )
            data = json.loads(r.stdout or "{}")
            streams = data.get("streams") or []
            if streams:
                s = streams[0]
                w = int(s.get("width") or 0)
                h = int(s.get("height") or 0)
                fps = _parse_rate(str(s.get("avg_frame_rate") or "")) or _parse_rate(str(s.get("r_frame_rate") or ""))
                rotation = 0
                tags = s.get("tags") or {}
                if tags.get("rotate"):
                    try:
                        rotation = int(float(tags.get("rotate")))
                    except Exception:
                        rotation = 0
                for sd in (s.get("side_data_list") or []):
                    if "rotation" in sd:
                        try:
                            rotation = int(float(sd.get("rotation")))
                        except Exception:
                            pass
                if w > 0 and h > 0 and fps > 0.0:
                    logger.debug("VPI_GEOMETRY_PROBE_OK path=%s %dx%d fps=%.3f rot=%d", p, w, h, fps, rotation)
                    return VideoGeometry(
                        width=w, height=h, fps=fps,
                        sar=(str(s.get("sample_aspect_ratio")) if s.get("sample_aspect_ratio") else None),
                        dar=(str(s.get("display_aspect_ratio")) if s.get("display_aspect_ratio") else None),
                        rotation=rotation % 360,
                    )
        except Exception:
            pass
        if attempt + 1 < max(1, retries):
            logger.debug("VPI_GEOMETRY_PROBE_RETRY path=%s attempt=%d", p, attempt + 1)
            _t.sleep(0.15)
    logger.warning("VPI_GEOMETRY_PROBE_FAILED path=%s reason=unreadable_or_no_geometry", p)
    return None


def probe_dimensions(video_path: Path | str) -> Tuple[int, int, float]:
    """Return (width, height, fps), or (0, 0, 0.0) if unknown (NEVER 1080x1920x30).

    Thin tuple wrapper over probe_video_geometry for legacy callers. Width/height are the
    rotation-corrected effective size. Callers must treat a 0 dimension as 'unknown' and skip
    rather than compose against a fabricated canvas (the old code ran ffmpeg with ffprobe-only
    options and always returned a hardcoded 1080x1920x30).
    """
    g = probe_video_geometry(video_path)
    if g is None:
        logger.debug("VPI_GEOMETRY_UNKNOWN path=%s value=(0,0,0.0)", str(video_path))
        return 0, 0, 0.0
    ew, eh = g.effective_size
    return ew, eh, g.fps


def _get_ffprobe_exe() -> str:
    """Return an ffprobe binary. ffprobe (NOT ffmpeg) is required for -show_entries."""
    p = shutil.which("ffprobe")
    if p:
        return p
    try:
        import imageio_ffmpeg as _iio  # imageio ships ffmpeg; try sibling ffprobe
        ff = _iio.get_ffmpeg_exe()
        cand = ff.replace("ffmpeg", "ffprobe")
        if cand != ff and os.path.exists(cand):
            return cand
    except Exception:
        pass
    return "ffprobe"


def probe_media_duration(
    path: "Path | str",
    *,
    retries: int = 3,
    timeout_s: float = 3.0,
) -> "float | None":
    """TIMING-38: canonical media-duration probe. Returns seconds, or None if unknown.

    Uses ffprobe (the video stream first, then the container format) — never ffmpeg with
    ffprobe-only options, and NEVER fabricates a constant (the old probe_duration ran
    `ffmpeg -show_entries ...` which always failed and returned a hardcoded 30.0). Callers
    must treat None as 'unknown' and apply an explicit per-caller fallback, not a guess.
    """
    import time as _t
    p = str(path)
    exe = _get_ffprobe_exe()
    for attempt in range(max(1, retries)):
        for selector in (("-select_streams", "v:0", "-show_entries", "stream=duration"),
                         ("-show_entries", "format=duration")):
            try:
                cmd = [exe, "-v", "error", *selector,
                       "-of", "default=noprint_wrappers=1:nokey=1", p]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
                val = (r.stdout or "").strip().splitlines()[0].strip() if (r.stdout or "").strip() else ""
                if val and val.upper() != "N/A":
                    d = float(val)
                    if d > 0.0:
                        logger.debug("VPI_DURATION_PROBE_OK path=%s dur=%.3f via=%s", p, d, selector[-1])
                        return round(d, 3)
            except Exception:
                continue
        if attempt + 1 < max(1, retries):
            logger.debug("VPI_DURATION_PROBE_RETRY path=%s attempt=%d", p, attempt + 1)
            _t.sleep(0.15)
    logger.warning("VPI_DURATION_PROBE_FAILED path=%s reason=unreadable_or_no_duration", p)
    return None


def probe_duration(video_path: Path | str) -> float:
    """Return duration in seconds, or 0.0 if unknown (NEVER a fabricated 30.0).

    Thin float-typed wrapper over probe_media_duration for legacy callers. Callers that use
    `probe_duration(x) or <fallback>` now get correct behaviour (0.0 is falsy → their explicit
    fallback fires) instead of the old phantom 30.0 that silently masqueraded as a real value.
    """
    d = probe_media_duration(video_path)
    if d is None:
        logger.debug("VPI_DURATION_FALLBACK_USED path=%s value=0.0 reason=unknown", str(video_path))
        return 0.0
    return float(d)


# ── B-roll normalisation ──────────────────────────────────────────────────────

def normalize_broll(
    broll_path: Path | str,
    target_w: int,
    target_h: int,
    duration: float,
    fade: float = 0.15,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Produce a normalised B-roll clip:
      - Scaled and center-cropped to target_w × target_h
      - Trimmed to *duration* seconds
      - Fade-in and fade-out of *fade* seconds (default 0.15s for brand-safe transitions)
      - Audio muted (B-roll is silent by design)
      - Ken Burns effect for static images (subtle zoom + pan)

    Works for both video files and static images (image → looped video).
    Returns the output Path on success, None on failure.
    """
    broll_path = Path(broll_path)
    is_image = broll_path.suffix.lower() in _IMAGE_EXTS
    source_duration = duration if is_image else probe_duration(broll_path)
    should_loop_video = (not is_image) and source_duration > 0.2 and source_duration < duration

    if output_path is None:
        suffix = ".mp4"
        # /app/assets is mounted read-only in Docker — fall back to the system
        # temp dir when the asset's directory is not writable.
        _tmp_dir = str(broll_path.parent) if os.access(broll_path.parent, os.W_OK) else None
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False,
                                          dir=_tmp_dir)
        output_path = Path(tmp.name)
        tmp.close()

    fade_out_start = max(0.0, duration - fade)

    # Sistema de efectos inteligentes - varía automáticamente
    if is_image and SMART_EFFECTS_AVAILABLE:
        # Seleccionar efecto inteligente
        effect_type = get_smart_broll_effect(is_image=True, context=None)
        effect_filter = build_broll_effect_filter(
            effect_type=effect_type,
            width=target_w,
            height=target_h,
            duration=duration,
            fps=30
        )
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1,"
            f"{effect_filter}"
        )
        logger.info(f"🎨 B-roll effect applied: {effect_type.value}")
        logger.info("[broll-kenburns] applied=true")
        logger.info("[broll-transition] applied=true type=short_fade")
    elif is_image:
        # Fallback: Ken Burns clásico sin fade negro
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1,"
            f"zoompan=z='min(zoom+0.0008,1.08)':d={int(duration*30)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={target_w}x{target_h}"
        )
        logger.info("[broll-kenburns] applied=true asset=%s", broll_path)
        logger.info("[broll-transition] applied=true type=short_fade")
    else:
        # Videos: sin fade negro, imagen limpia
        vf = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},"
            f"setsar=1"
        )
        logger.info("[broll-transition] applied=true type=clean_cut")

    # Build codec flags (ensure they come after input/output mapping options)
    _codec_flags = _gpu_codec("medium")
    _fallback_flags = _sw_fallback("medium")
    
    if is_image:
        # Include silent audio (-f lavfi -i anullsrc) so the B-roll video
        # has a valid audio stream. Without this, compose_overlay_multi fails
        # when mixing AV streams because the overlay input lacks audio.
        def _build_cmd(codec_flags: list[str]) -> list[str]:
            return [
            _get_ffmpeg_exe(), "-y",
            "-loop", "1", "-i", str(broll_path),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", str(duration),
            "-vf", vf,
            "-shortest",
            *codec_flags,
            "-c:a", "aac", "-ar", "44100",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
            ]
    else:
        def _build_cmd(codec_flags: list[str]) -> list[str]:
            loop_args = ["-stream_loop", "-1"] if should_loop_video else []
            if should_loop_video:
                logger.info("[broll-duration] extended/looped to effective=%.2f", duration)
            return [
            _get_ffmpeg_exe(), "-y",
            *loop_args,
            "-i", str(broll_path),
            "-t", str(duration),
            "-vf", vf,
            "-an",
            *codec_flags,
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
            ]

    cmd = _build_cmd(_codec_flags)
    fallback_cmd = _build_cmd(_fallback_flags)

    try:
        result = _run_ffmpeg_sync_with_fallback(
            cmd,
            fallback_cmd,
            output_path,
            "[BrollCompositor] normalize_broll",
            _FFMPEG_TIMEOUT,
        )
        if result.returncode != 0:
            logger.error("[BrollCompositor] normalize_broll failed: %s",
                         result.stderr.decode()[-400:])
            output_path.unlink(missing_ok=True)
            return None
        if not output_path.exists() or output_path.stat().st_size < 1000:
            output_path.unlink(missing_ok=True)
            return None
        return output_path
    except subprocess.TimeoutExpired:
        logger.error("[BrollCompositor] normalize_broll timed out")
        output_path.unlink(missing_ok=True)
        return None
    except Exception as exc:
        logger.error("[BrollCompositor] normalize_broll exception: %s", exc)
        output_path.unlink(missing_ok=True)
        return None


# ── Single overlay composition ────────────────────────────────────────────────

def compose_overlay(
    main_path: Path | str,
    broll_path: Path | str,
    output_path: Path | str,
    timestamp: float,
    duration: float = 2.5,
    fade: float = 0.6,
) -> bool:
    """
    Overlay *broll_path* on *main_path* starting at *timestamp* for *duration* seconds.

    Steps:
      1. Probe main clip dimensions
      2. Normalise B-roll to those exact dimensions
      3. Composite with FFmpeg overlay filter

    Returns True on success.
    """
    main_path   = Path(main_path)
    broll_path  = Path(broll_path)
    output_path = Path(output_path)

    # TIMING-39: never compose against a fabricated canvas. If the main clip geometry is
    # unknown (0), skip the overlay rather than normalise B-roll to a phantom 1080x1920.
    w, h, _fps = probe_dimensions(main_path)
    if w <= 0 or h <= 0:
        logger.warning("[BrollCompositor] compose_overlay skipped reason=geometry_unknown main=%s", main_path)
        return False

    # Normalise B-roll — sin fade negro para no oscurecer la imagen
    norm_path = normalize_broll(broll_path, w, h, duration=duration, fade=fade)
    if norm_path is None:
        logger.error("[BrollCompositor] compose_overlay: normalise step failed")
        return False

    end_ts = timestamp + duration
    visual_fade = max(0.0, min(0.20, float(fade or 0.0), duration / 3.0))
    if visual_fade > 0.0:
        fade_out_start = max(0.0, duration - visual_fade)
        broll_chain = (
            "[1:v]setpts=PTS-STARTPTS,"
            "format=rgba,"
            f"fade=t=in:st=0:d={visual_fade:.3f}:alpha=1,"
            f"fade=t=out:st={fade_out_start:.3f}:d={visual_fade:.3f}:alpha=1,"
            f"setpts=PTS+{timestamp:.3f}/TB[bv];"
        )
        logger.info("[broll-transition] fade_in=%.2f fade_out=%.2f applied=true", visual_fade, visual_fade)
        logger.info(
            "VPI_OUTPUT_QUALITY_TRANSITION_VISIBLE type=broll_cutaway_crossfade fade=%.2f at=%.2f-%.2f",
            visual_fade, timestamp, end_ts,
        )
    else:
        broll_chain = f"[1:v]setpts=PTS-STARTPTS+{timestamp:.3f}/TB[bv];"
    filter_complex = (
        broll_chain
        + f"[0:v][bv]overlay=enable='between(t\\,{timestamp:.3f}\\,{end_ts:.3f})':x=0:y=0[out]"
    )

    _codec_flags = _gpu_codec("high")
    _fallback_flags = _sw_fallback("high")

    def _build_cmd(codec_flags: list[str]) -> list[str]:
        return [
        _get_ffmpeg_exe(), "-y",
        "-i", str(main_path),
        "-i", str(norm_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "0:a?",
        *codec_flags,
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
        ]

    cmd = _build_cmd(_codec_flags)
    fallback_cmd = _build_cmd(_fallback_flags)

    try:
        result = _run_ffmpeg_sync_with_fallback(
            cmd,
            fallback_cmd,
            output_path,
            "[BrollCompositor] compose_overlay",
            _FFMPEG_TIMEOUT,
        )
        norm_path.unlink(missing_ok=True)
        if result.returncode != 0:
            logger.error("[BrollCompositor] compose_overlay FFmpeg failed: %s",
                         result.stderr.decode()[-400:])
            return False
        return output_path.exists() and output_path.stat().st_size > 0
    except subprocess.TimeoutExpired:
        logger.error("[BrollCompositor] compose_overlay timed out")
        norm_path.unlink(missing_ok=True)
        return False
    except Exception as exc:
        logger.error("[BrollCompositor] compose_overlay exception: %s", exc)
        norm_path.unlink(missing_ok=True)
        return False


# ── Async multi-overlay (used by video_effects.py) ────────────────────────────

async def compose_overlay_multi(
    main_path: Path | str,
    broll_pairs: list,          # [(timestamp, broll_path, duration), ...]
    output_path: Path | str,
    fade: float = 0.6,
) -> bool:
    """
    Apply multiple B-roll overlays in a single FFmpeg pass.

    *broll_pairs* is a list of (timestamp_s, broll_path, duration_s).
    Probes main clip dimensions once, normalises each B-roll, then
    chains overlays in one filter_complex.

    Returns True on success.
    """
    if not broll_pairs:
        return False

    main_path   = Path(main_path)
    output_path = Path(output_path)

    # TIMING-39: skip composition if the main clip geometry is unknown (no phantom canvas).
    w, h, _fps = probe_dimensions(main_path)
    if w <= 0 or h <= 0:
        logger.warning("[BrollCompositor] compose_overlay_multi skipped reason=geometry_unknown main=%s", main_path)
        return False

    # Normalise each B-roll clip
    norm_paths: list[Path] = []
    valid_pairs: list[tuple] = []
    for ts, bp, dur in broll_pairs:
        np_ = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda bp=bp, dur=dur: normalize_broll(Path(bp), w, h, duration=dur, fade=fade),
        )
        if np_:
            norm_paths.append(np_)
            valid_pairs.append((ts, np_, dur))

    if not valid_pairs:
        logger.warning("[BrollCompositor] compose_overlay_multi: no valid B-rolls after normalise")
        return False

    inputs: list[str] = ["-i", str(main_path)]
    for _, np_, _ in valid_pairs:
        inputs += ["-i", str(np_)]

    filter_parts: list[str] = []
    prev = "0:v"
    for idx, (ts, _, dur) in enumerate(valid_pairs):
        end_ts = ts + dur
        out_tag = f"vout{idx}"
        visual_fade = max(0.0, min(0.20, float(fade or 0.0), dur / 3.0))
        input_tag = f"bo{idx}"
        if visual_fade > 0.0:
            fade_out_start = max(0.0, dur - visual_fade)
            filter_parts.append(
                f"[{idx + 1}:v]setpts=PTS-STARTPTS,format=rgba,"
                f"fade=t=in:st=0:d={visual_fade:.3f}:alpha=1,"
                f"fade=t=out:st={fade_out_start:.3f}:d={visual_fade:.3f}:alpha=1,"
                f"setpts=PTS+{ts:.3f}/TB[{input_tag}]"
            )
            logger.info("[broll-transition] fade_in=%.2f fade_out=%.2f applied=true", visual_fade, visual_fade)
        else:
            filter_parts.append(f"[{idx + 1}:v]setpts=PTS-STARTPTS+{ts:.3f}/TB[{input_tag}]")
        filter_parts.append(
            f"[{prev}][{input_tag}]"
            f"overlay=enable='between(t\\,{ts:.3f}\\,{end_ts:.3f})':x=0:y=0"
            f"[{out_tag}]"
        )
        prev = out_tag

    filter_complex = ";".join(filter_parts)

    _codec_flags = _gpu_codec("high")
    _fallback_flags = _sw_fallback("high")

    def _build_cmd(codec_flags: list[str]) -> list[str]:
        return [
        _get_ffmpeg_exe(), "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", f"[{prev}]",
        "-map", "0:a?",
        *codec_flags,
        "-c:a", "copy",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
        ]

    cmd = _build_cmd(_codec_flags)
    fallback_cmd = _build_cmd(_fallback_flags)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, _err = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT)
        if proc.returncode != 0:
            if _uses_nvenc(_codec_flags):
                logger.warning("[gpu] NVENC failed; retrying with libx264")
                logger.debug("[BrollCompositor] compose_overlay_multi NVENC stderr: %s",
                             _err.decode(errors="replace")[-400:])
                output_path.unlink(missing_ok=True)
                proc = await asyncio.create_subprocess_exec(
                    *fallback_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _err = await asyncio.wait_for(proc.communicate(), timeout=_FFMPEG_TIMEOUT)
            if proc.returncode != 0:
                for np_ in norm_paths:
                    np_.unlink(missing_ok=True)
                logger.error("[BrollCompositor] compose_overlay_multi failed: %s",
                             _err.decode()[-400:])
                return False
        for np_ in norm_paths:
            np_.unlink(missing_ok=True)
        return output_path.exists() and output_path.stat().st_size > 0
    except (asyncio.TimeoutError, Exception) as exc:
        logger.error("[BrollCompositor] compose_overlay_multi exception: %s", exc)
        for np_ in norm_paths:
            np_.unlink(missing_ok=True)
        return False
