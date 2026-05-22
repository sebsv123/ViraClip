"""
Transitions Service — Professional video transitions for ViraClip.

Provides a clean API for applying transitions between video segments:

    apply_transition(input_a, input_b, type, duration, output) -> Path

Supported transition types:
  - "crossfade"   : FFmpeg xfade=fade (smooth dissolve between clips)
  - "fade_black"  : fade out A to black, then fade in from black
  - "slide_left"  : FFmpeg xfade=slideleft (A slides left, B appears)

Before applying any transition, both inputs are normalised to the same
resolution (1080×1920), frame rate (30 fps), pixel format (yuv420p), and
audio codec (AAC 128k).  This guarantees FFmpeg compatibility.

Preset system:
  - "default" : always crossfade (0.25 s)
  - "dynamic" : alternates crossfade / slide_left based on clip type

Fallback: if xfade fails, falls back to concat demuxer (hard cut) and
logs the failure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
DEFAULT_TRANSITION_DURATION = 0.25  # seconds
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
DEFAULT_FPS = 30.0
AUDIO_BITRATE = "128k"
AUDIO_SAMPLE_RATE = "48000"
_FFMPEG_TIMEOUT = 120  # seconds per transition

# ── Supported transition types ─────────────────────────────────────────────
TRANSITION_TYPES = {"crossfade", "fade_black", "slide_left"}

# ── Preset definitions ─────────────────────────────────────────────────────
PRESETS = {
    "default": {
        "description": "Always crossfade (0.25 s)",
        "transition_for": lambda _clip_type: "crossfade",
    },
    "dynamic": {
        "description": "Alternates crossfade / slide_left based on clip type",
        "transition_for": lambda clip_type: (
            "slide_left" if clip_type in ("broll", "action", "transition")
            else "crossfade"
        ),
    },
}


# ── Helpers ────────────────────────────────────────────────────────────────


def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _get_ffprobe_exe() -> str:
    """Return path to ffprobe binary."""
    import shutil
    if shutil.which("ffprobe"):
        return "ffprobe"
    # Fallback: try alongside ffmpeg
    ffmpeg = _get_ffmpeg_exe()
    if ffmpeg.endswith("ffmpeg"):
        return ffmpeg.replace("ffmpeg", "ffprobe")
    return "ffprobe"


async def _run_ffmpeg(cmd: list[str], timeout: float = _FFMPEG_TIMEOUT) -> tuple[int, bytes]:
    """Run an FFmpeg subprocess and return (returncode, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, b"TIMEOUT"
    return proc.returncode or 0, stderr


def _probe_streams(video_path: Path) -> dict:
    """Probe video and audio stream info using ffprobe.

    Returns a dict with keys: width, height, fps, has_audio, audio_codec.
    Falls back to safe defaults on failure.
    """
    info = {"width": DEFAULT_WIDTH, "height": DEFAULT_HEIGHT, "fps": DEFAULT_FPS,
            "has_audio": True, "audio_codec": "aac"}
    try:
        cmd = [
            _get_ffprobe_exe(), "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        data = __import__("json").loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                info["width"] = int(stream.get("width", DEFAULT_WIDTH))
                info["height"] = int(stream.get("height", DEFAULT_HEIGHT))
                fps_str = stream.get("r_frame_rate", "30/1")
                try:
                    num, den = fps_str.split("/")
                    info["fps"] = round(float(num) / float(den), 3)
                except Exception:
                    info["fps"] = DEFAULT_FPS
            elif stream.get("codec_type") == "audio":
                info["has_audio"] = True
                info["audio_codec"] = stream.get("codec_name", "aac")
    except Exception as exc:
        logger.debug("[Transitions] probe_streams failed for %s: %s", video_path, exc)
    return info


def _probe_duration(video_path: Path) -> float:
    """Return duration in seconds. Falls back to 0.0."""
    try:
        cmd = [
            _get_ffprobe_exe(), "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


# ── Input normalisation ────────────────────────────────────────────────────


def _ensure_audio_stream(clip_path: Path, output_path: Path) -> Path:
    """Add a silent audio stream to a clip if it has no audio.

    B-roll clips from Pexels/Coverr often lack audio streams, which causes
    the xfade filter's acrossfade to fail with "Stream specifier ':a' matches
    no streams". This function probes the clip and adds anullsrc if needed.

    Args:
        clip_path: Input video path.
        output_path: Output path for the video with guaranteed audio stream.

    Returns:
        Path to the clip with audio (same as clip_path if audio already present).
    """
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name",
         "-of", "default=noprint_wrappers=1", str(clip_path)],
        capture_output=True, text=True, timeout=15
    )
    if probe.stdout.strip():
        return clip_path  # ya tiene audio

    logger.info("[Transitions] Adding silent audio stream to %s", clip_path.name)
    subprocess.run([
        _get_ffmpeg_exe(), "-y",
        "-i", str(clip_path),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(output_path),
    ], capture_output=True, timeout=60)
    return output_path


async def _normalise_input(
    input_path: Path,
    output_path: Path,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: float = DEFAULT_FPS,
) -> bool:
    """Normalise a video to target resolution, fps, pixel format, and audio.

    Uses a filter chain: scale → setsar → fps → format=yuv420p.
    Audio is re-encoded to AAC 128k 48kHz.

    Before normalising, ensures the input has an audio stream (adds silent
    audio if missing) to prevent xfade/acrossfade failures.
    """
    # FIX 3: Ensure input has audio stream before normalising
    tmp_audio = input_path.parent / f"_audiofix_{input_path.name}"
    try:
        input_with_audio = _ensure_audio_stream(input_path, tmp_audio)
    except Exception:
        input_with_audio = input_path

    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-i", str(input_with_audio),
        "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
               f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
               f"fps={fps},format=yuv420p",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-ar", AUDIO_SAMPLE_RATE,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    rc, stderr = await _run_ffmpeg(cmd, timeout=_FFMPEG_TIMEOUT)
    ok = rc == 0 and output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        logger.warning(
            "[Transitions] Normalise failed for %s (rc=%d, exists=%s, size=%d)",
            input_path.name, rc, output_path.exists(),
            output_path.stat().st_size if output_path.exists() else -1,
        )
    # Cleanup temp audio-fix file
    if tmp_audio.exists():
        tmp_audio.unlink(missing_ok=True)
    return ok


# ── Transition implementations ─────────────────────────────────────────────


async def _apply_crossfade(
    input_a: Path,
    input_b: Path,
    duration: float,
    output_path: Path,
) -> bool:
    """Apply crossfade (xfade=fade) transition between two clips.

    Both inputs must already be normalised (same resolution, fps, format).
    """
    dur_a = _probe_duration(input_a)
    dur_b = _probe_duration(input_b)
    offset = dur_a - duration  # xfade offset = start of transition in A

    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-i", str(input_a),
        "-i", str(input_b),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=fade:duration={duration:.3f}:offset={offset:.3f}[v];"
        f"[0:a][1:a]acrossfade=d={duration:.3f}[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-ar", AUDIO_SAMPLE_RATE,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    rc, stderr = await _run_ffmpeg(cmd, timeout=_FFMPEG_TIMEOUT)
    ok = rc == 0 and output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        logger.warning(
            "[Transitions] crossfade failed (rc=%d): %s",
            rc, stderr.decode(errors="replace")[-300:],
        )
    return ok


async def _apply_fade_black(
    input_a: Path,
    input_b: Path,
    duration: float,
    output_path: Path,
) -> bool:
    """Apply fade-to-black transition.

    Fades A out to black, then fades B in from black.
    Uses a concat of: [A with fade out] + [black] + [B with fade in].
    The black hold is 0.1 s to avoid a flash.
    """
    dur_a = _probe_duration(input_a)
    dur_b = _probe_duration(input_b)
    half = duration / 2.0
    black_hold = 0.1

    # Clamp fade-out start to avoid negative st values when dur_a < half
    fade_out_start = max(0.0, dur_a - half)

    # We use a single filter_complex with trim + fade + concat
    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-i", str(input_a),
        "-i", str(input_b),
        "-filter_complex",
        # Segment A: trim to full duration, fade out over 'half' seconds
        f"[0:v]trim=0:{dur_a:.3f},fade=t=out:st={fade_out_start:.3f}:d={half:.3f}:color=black[v0];"
        # Segment B: trim to full duration, fade in over 'half' seconds
        f"[1:v]trim=0:{dur_b:.3f},fade=t=in:st=0:d={half:.3f}:color=black[v1];"
        # Black filler
        f"color=c=black:s={DEFAULT_WIDTH}x{DEFAULT_HEIGHT}:d={black_hold}:r={DEFAULT_FPS}[black];"
        # Concat video
        f"[v0][black][v1]concat=n=3:v=1:a=0[outv];"
        # Audio: crossfade A into B (no curve param — not supported in FFmpeg 7.1)
        f"[0:a][1:a]acrossfade=d={duration:.3f}[outa]",
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-ar", AUDIO_SAMPLE_RATE,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    rc, stderr = await _run_ffmpeg(cmd, timeout=_FFMPEG_TIMEOUT)
    ok = rc == 0 and output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        logger.warning(
            "[Transitions] fade_black failed (rc=%d): %s",
            rc, stderr.decode(errors="replace")[-300:],
        )
    return ok


async def _apply_slide_left(
    input_a: Path,
    input_b: Path,
    duration: float,
    output_path: Path,
) -> bool:
    """Apply slide-left transition (xfade=slideleft).

    Both inputs must already be normalised.
    """
    dur_a = _probe_duration(input_a)
    offset = dur_a - duration

    cmd = [
        _get_ffmpeg_exe(), "-y",
        "-i", str(input_a),
        "-i", str(input_b),
        "-filter_complex",
        f"[0:v][1:v]xfade=transition=slideleft:duration={duration:.3f}:offset={offset:.3f}[v];"
        f"[0:a][1:a]acrossfade=d={duration:.3f}[a]",
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", AUDIO_BITRATE,
        "-ar", AUDIO_SAMPLE_RATE,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    rc, stderr = await _run_ffmpeg(cmd, timeout=_FFMPEG_TIMEOUT)
    ok = rc == 0 and output_path.exists() and output_path.stat().st_size > 0
    if not ok:
        logger.warning(
            "[Transitions] slide_left failed (rc=%d): %s",
            rc, stderr.decode(errors="replace")[-300:],
        )
    return ok


# ── Fallback: concat demuxer (hard cut) ────────────────────────────────────


async def _fallback_concat(
    input_a: Path,
    input_b: Path,
    output_path: Path,
) -> bool:
    """Fallback: concatenate two clips using concat demuxer (hard cut).

    Used when xfade-based transitions fail.  Both inputs must already be
    normalised to the same codec/resolution/fps.

    Returns False immediately if either input file does not exist.
    """
    if not input_a.exists():
        logger.error("[Transitions] Fallback concat: input_a does not exist: %s", input_a)
        return False
    if not input_b.exists():
        logger.error("[Transitions] Fallback concat: input_b does not exist: %s", input_b)
        return False
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write(f"file '{input_a}'\n")
            f.write(f"file '{input_b}'\n")
            concat_file = f.name

        cmd = [
            _get_ffmpeg_exe(), "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]
        rc, stderr = await _run_ffmpeg(cmd, timeout=_FFMPEG_TIMEOUT)
        os.unlink(concat_file)
        ok = rc == 0 and output_path.exists() and output_path.stat().st_size > 0
        if not ok:
            logger.error(
                "[Transitions] Fallback concat also failed (rc=%d)", rc,
            )
        return ok
    except Exception as exc:
        logger.error("[Transitions] Fallback concat exception: %s", exc)
        return False


# ── QA Validation ──────────────────────────────────────────────────────────

# Minimum transition duration enforced by QA (seconds)
_QA_MIN_TRANSITION_DURATION = 0.6


def _qa_validate_transition(
    transition_type: str,
    duration: float,
) -> float:
    """Validate and clamp transition parameters before returning timeline.

    Checks:
      - Transition duration >= 0.6s (clamp up + WARNING if violated)

    Returns the (possibly clamped) duration.
    """
    if duration < _QA_MIN_TRANSITION_DURATION:
        logger.warning(
            "[Transitions QA] Clamping %s duration from %.2fs to %.2fs (min=%.1fs)",
            transition_type, duration, _QA_MIN_TRANSITION_DURATION,
            _QA_MIN_TRANSITION_DURATION,
        )
        duration = _QA_MIN_TRANSITION_DURATION
    return duration


# ── Public API ─────────────────────────────────────────────────────────────


async def apply_transition(
    input_a: Path,
    input_b: Path,
    transition_type: str = "crossfade",
    duration: float = DEFAULT_TRANSITION_DURATION,
    output_path: Optional[Path] = None,
    preset: Optional[str] = None,
    clip_type: str = "talking_head",
) -> Path:
    """Apply a transition between *input_a* and *input_b*.

    Args:
        input_a: First video clip (will transition FROM this).
        input_b: Second video clip (will transition TO this).
        transition_type: One of "crossfade", "fade_black", "slide_left".
            Ignored when *preset* is set.
        duration: Transition duration in seconds (default 0.25).
        output_path: Desired output path.  If None, a temp path is created
            next to *input_a*.
        preset: Optional preset name ("default" or "dynamic").  When set,
            *transition_type* is derived from *clip_type*.
        clip_type: Clip type hint for preset resolution (e.g. "talking_head",
            "broll", "action", "transition").

    Returns:
        Path to the output file.  If the transition fails entirely (including
        fallback), returns *input_a* unchanged.

    Raises:
        ValueError: If *transition_type* is not recognised.
    """
    input_a = Path(input_a)
    input_b = Path(input_b)

    # Resolve transition type from preset
    if preset:
        preset_def = PRESETS.get(preset)
        if preset_def:
            transition_type = preset_def["transition_for"](clip_type)
            logger.debug(
                "[Transitions] Preset '%s' resolved to '%s' for clip_type='%s'",
                preset, transition_type, clip_type,
            )

    if transition_type not in TRANSITION_TYPES:
        raise ValueError(
            f"Unknown transition type '{transition_type}'. "
            f"Supported: {', '.join(sorted(TRANSITION_TYPES))}"
        )

    # ── QA: validate and clamp transition parameters ───────────────────
    duration = _qa_validate_transition(transition_type, duration)

    if output_path is None:
        output_path = input_a.with_name(
            f"trans_{input_a.stem}_{input_b.stem}{input_a.suffix}"
        )

    output_path = Path(output_path)

    # ── Step 1: Normalise both inputs ──────────────────────────────────
    tmpdir = Path(tempfile.mkdtemp(prefix="viraclip_trans_"))
    try:
        norm_a = tmpdir / f"norm_a_{input_a.name}"
        norm_b = tmpdir / f"norm_b_{input_b.name}"

        ok_a = await _normalise_input(input_a, norm_a)
        ok_b = await _normalise_input(input_b, norm_b)

        if not ok_a or not ok_b:
            logger.warning(
                "[Transitions] Input normalisation failed (a=%s, b=%s) — falling back to concat",
                ok_a, ok_b,
            )
            # Try fallback with original inputs
            ok = await _fallback_concat(input_a, input_b, output_path)
            if ok:
                return output_path
            return input_a

        # ── Step 2: Apply transition ───────────────────────────────────
        success = False
        if transition_type == "crossfade":
            success = await _apply_crossfade(norm_a, norm_b, duration, output_path)
        elif transition_type == "fade_black":
            success = await _apply_fade_black(norm_a, norm_b, duration, output_path)
        elif transition_type == "slide_left":
            success = await _apply_slide_left(norm_a, norm_b, duration, output_path)

        if success:
            logger.info(
                "[Transitions] ✓ %s (%.2f s) → %s",
                transition_type, duration, output_path.name,
            )
            return output_path

        # ── Step 3: Fallback ───────────────────────────────────────────
        logger.warning(
            "[Transitions] %s failed — falling back to hard concat",
            transition_type,
        )
        ok = await _fallback_concat(norm_a, norm_b, output_path)
        if ok:
            return output_path

        return input_a

    finally:
        # Cleanup temp dir
        try:
            for f in tmpdir.iterdir():
                f.unlink(missing_ok=True)
            tmpdir.rmdir()
        except Exception:
            pass


async def apply_transition_batch(
    clips: list[Path],
    transition_type: str = "crossfade",
    duration: float = DEFAULT_TRANSITION_DURATION,
    output_path: Optional[Path] = None,
    preset: Optional[str] = None,
    clip_types: Optional[list[str]] = None,
) -> Path:
    """Apply transitions across a batch of clips, concatenating them.

    Args:
        clips: Ordered list of clip paths to concatenate with transitions.
        transition_type: Transition type (used when *preset* is None).
        duration: Transition duration in seconds.
        output_path: Desired output path.
        preset: Optional preset name.
        clip_types: Optional list of clip types (one per clip) for preset
            resolution.  If None, all are treated as "talking_head".

    Returns:
        Path to the final concatenated output.
    """
    if len(clips) < 2:
        # Single clip — just return it
        if clips:
            return clips[0]
        raise ValueError("apply_transition_batch requires at least 1 clip")

    if clip_types is None:
        clip_types = ["talking_head"] * len(clips)

    # ── Transition rotation system ────────────────────────────────────────────
    # Rotate through available transitions to avoid repetitive look.
    # Never repeat the same transition twice in a row.
    _TRANSITION_ROTATION = ["crossfade", "slide_left", "fade_black"]
    _last_transition = None
    _rotation_index = 0

    def _pick_transition(clip_idx: int, prev_clip_type: str) -> str:
        """Pick the next transition in rotation with context awareness.
        
        If the previous clip ended on an emotional/loud moment (action/broll),
        force a hard cut (no transition). Otherwise rotate through the list.
        """
        nonlocal _last_transition, _rotation_index
        
        # Context rule: if previous clip was action/broll, use hard cut
        if prev_clip_type in ("action", "broll", "transition"):
            _last_transition = None
            return "crossfade"  # Will be treated as hard cut via 0.01s duration
        
        # Rotation: pick next, skip if same as last
        for _ in range(len(_TRANSITION_ROTATION)):
            candidate = _TRANSITION_ROTATION[_rotation_index % len(_TRANSITION_ROTATION)]
            _rotation_index += 1
            if candidate != _last_transition:
                _last_transition = candidate
                return candidate
        
        return "crossfade"  # fallback

    # Build the chain iteratively: merge clip[0] + clip[1], then result + clip[2], etc.
    current = clips[0]
    tmpdir = Path(tempfile.mkdtemp(prefix="viraclip_trans_batch_"))
    try:
        for i in range(1, len(clips)):
            ct = clip_types[i] if i < len(clip_types) else "talking_head"
            prev_ct = clip_types[i - 1] if i - 1 < len(clip_types) else "talking_head"
            
            # Pick transition via rotation + context
            trans_type = _pick_transition(i, prev_ct)
            
            # For action/broll clips, use very short duration (hard cut feel)
            trans_dur = 0.01 if prev_ct in ("action", "broll", "transition") else duration
            
            tmp_out = tmpdir / f"batch_{i:04d}.mp4"
            current = await apply_transition(
                input_a=current,
                input_b=clips[i],
                transition_type=trans_type,
                duration=trans_dur,
                output_path=tmp_out,
                preset=preset,
                clip_type=ct,
            )
            logger.info(
                "[TRANSITION] Applied %s between clip %d and clip %d",
                trans_type, i, i + 1,
            )

        # Move final result to desired output path
        if output_path is None:
            output_path = clips[0].with_name(
                f"concat_{clips[0].stem}_to_{clips[-1].stem}{clips[0].suffix}"
            )
        output_path = Path(output_path)

        if current != tmpdir / f"batch_{len(clips)-1:04d}.mp4":
            # Fallback happened — copy
            import shutil
            shutil.copy2(str(current), str(output_path))
        else:
            current.replace(output_path)

        logger.info(
            "[Transitions] Batch concat: %d clips → %s (transition=%s, dur=%.2f s)",
            len(clips), output_path.name, transition_type, duration,
        )
        return output_path

    finally:
        try:
            for f in tmpdir.iterdir():
                f.unlink(missing_ok=True)
            tmpdir.rmdir()
        except Exception:
            pass
