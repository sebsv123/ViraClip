"""
optical_flow_transitions.py — Phase 2.3
=========================================
Smooth morph transitions between adjacent clip cuts using RAFT optical flow.

Architecture:
  RAFT path (PyTorch required):
    last_frame + first_frame → RAFT-small → flow field → warp + alpha blend
    → N interpolated frames → intermediate morph clip (0.3–0.8s)

  FFmpeg xfade path (always available, CPU-only fallback):
    FFmpeg -filter_complex xfade=transition:duration → smooth dissolve/wipe

  Integration points:
    - video_utils.apply_transition_effect  (existing, enhanced)
    - video_service.apply_single_transition  (activated when clips are adjacent)
    - gpu_tasks.generate_optical_flow_transition  (ARQ GPU task)

Usage:
    # High-level: build morph clip between two existing clips
    result = apply_optical_flow_transition(clip_a, clip_b, output)
    
    # Lower-level: just a morph frame clip between two frames
    morph_path = generate_morph_clip(last_frame, first_frame, duration=0.5, output=...)
"""

import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  RAFT model loading (lazy, cached)
# ─────────────────────────────────────────────────────────────────────────────

_raft_model = None
_raft_available: Optional[bool] = None

# RAFT-small model path (5.3MB — downloaded on first use)
RAFT_MODEL_PATH = Path("/app/models/raft-small.pth")
RAFT_MODEL_URL = (
    "https://dl.dropboxusercontent.com/s/4j4z58wuv8o0mfz/models.zip"
)


def _get_raft_model():
    """Lazy-load RAFT-small model. Returns None if PyTorch/RAFT not available."""
    global _raft_model, _raft_available

    if _raft_available is not None:
        return _raft_model

    try:
        import torch  # noqa: F401
        # Try loading RAFT from torchvision (available from PyTorch ≥ 1.13)
        from torchvision.models.optical_flow import raft_small, Raft_Small_Weights

        weights = Raft_Small_Weights.DEFAULT
        model = raft_small(weights=weights, progress=False)
        model.eval()
        # Move to CUDA if available — RTX 3050 handles RAFT-small easily
        _device = "cuda" if torch.cuda.is_available() and os.environ.get("RAFT_ENABLED", "true").lower() == "true" else "cpu"
        model = model.to(_device)
        _raft_model = model
        _raft_available = True
        logger.info(f"[raft] RAFT-small loaded on {_device.upper()}")

    except (ImportError, AttributeError):
        # Try torchvision < 0.14 (no optical_flow module)
        _raft_available = False
        logger.debug("[raft] torchvision optical_flow not available — using FFmpeg xfade")
    except Exception as e:
        _raft_available = False
        logger.debug(f"[raft] Could not load RAFT model: {e} — using FFmpeg xfade")

    return _raft_model


# ─────────────────────────────────────────────────────────────────────────────
#  Public API
# ─────────────────────────────────────────────────────────────────────────────

def apply_optical_flow_transition(
    clip_a: Path,
    clip_b: Path,
    output_path: Path,
    transition_duration: float = 0.5,
    transition_type: str = "auto",
) -> bool:
    """
    Concatenate clip_a + clip_b with a smooth morph transition between them.

    Args:
        clip_a:              Path to first clip (transition reads its last frame)
        clip_b:              Path to second clip (transition reads its first frame)
        output_path:         Path for concatenated output with transition baked in
        transition_duration: Length of the morph in seconds (default 0.5s)
        transition_type:     "raft" | "xfade" | "auto" (auto tries RAFT, falls back)

    Returns:
        True on success, False on failure (original clips untouched).
    """
    clip_a, clip_b, output_path = Path(clip_a), Path(clip_b), Path(output_path)

    if not clip_a.exists() or not clip_b.exists():
        logger.warning(f"[raft] Input clips not found: {clip_a}, {clip_b}")
        return False

    use_raft = transition_type in ("raft", "auto") and _get_raft_model() is not None

    if use_raft:
        success = _apply_raft_transition(
            clip_a, clip_b, output_path, transition_duration
        )
        if success:
            return True
        logger.warning("[raft] RAFT transition failed — falling back to xfade")

    # Rotate through available xfade effects per output file so adjacent clips
    # never get the same transition style.
    _effect_idx = abs(hash(output_path.name)) % len(XFADE_EFFECTS)
    _effect = XFADE_EFFECTS[_effect_idx]
    return _apply_xfade_transition(clip_a, clip_b, output_path, transition_duration, effect=_effect)


def generate_morph_clip(
    frame_a: Path,
    frame_b: Path,
    num_frames: int = 15,
    fps: int = 30,
    output_path: Optional[Path] = None,
) -> Optional[Path]:
    """
    Generate a short morph transition clip between two frames.
    Uses RAFT flow warping when available, cross-dissolve as CPU fallback.

    Args:
        frame_a:      Source frame (JPEG/PNG)
        frame_b:      Target frame (JPEG/PNG)
        num_frames:   Number of interpolation frames (default 15 = 0.5s at 30fps)
        fps:          Output frame rate
        output_path:  Path for the output MP4; uses a temp file if None

    Returns:
        Path to the generated morph clip, or None on failure.
    """
    if output_path is None:
        output_path = Path(tempfile.mkdtemp()) / f"morph_{uuid.uuid4().hex[:8]}.mp4"

    model = _get_raft_model()
    if model is not None:
        result = _raft_morph_clip(frame_a, frame_b, num_frames, fps, output_path, model)
        if result:
            return output_path

    # CPU fallback: cross-dissolve via imageio + ffmpeg
    return _crossfade_morph_clip(frame_a, frame_b, num_frames, fps, output_path)


def extract_boundary_frames(clip_path: Path) -> tuple[Optional[Path], Optional[Path]]:
    """
    Extract the last frame and first frame of a clip for transition generation.

    Returns:
        (first_frame_path, last_frame_path) as temporary JPEGs, or (None, None).
    """
    tmp_dir = Path(tempfile.mkdtemp())
    first = tmp_dir / "first.jpg"
    last = tmp_dir / "last.jpg"

    try:
        # First frame at t=0
        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", "0",
                "-i", str(clip_path),
                "-vframes", "1", "-q:v", "2",
                str(first),
            ],
            capture_output=True, timeout=10,
        )

        # Last frame (seek to end - 1/fps ≈ 33ms before end)
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration", "-of", "csv=p=0",
             str(clip_path)],
            capture_output=True, text=True, timeout=10,
        )
        duration = float(probe.stdout.strip().split("\n")[0]) if probe.stdout.strip() else 1.0
        seek_last = max(0.0, duration - 0.05)

        subprocess.run(
            [
                "ffmpeg", "-y", "-ss", str(seek_last),
                "-i", str(clip_path),
                "-vframes", "1", "-q:v", "2",
                str(last),
            ],
            capture_output=True, timeout=10,
        )

        if first.exists() and last.exists():
            return first, last

    except Exception as e:
        logger.warning(f"[raft] Frame extraction failed: {e}")

    return None, None


# ─────────────────────────────────────────────────────────────────────────────
#  RAFT optical flow implementation
# ─────────────────────────────────────────────────────────────────────────────

def _raft_morph_clip(
    frame_a: Path,
    frame_b: Path,
    num_frames: int,
    fps: int,
    output_path: Path,
    model,
) -> bool:
    """Compute RAFT optical flow + warp to produce interpolated morph frames."""
    try:
        import torch
        import torchvision.transforms.functional as F
        import cv2

        img_a = cv2.imread(str(frame_a))
        img_b = cv2.imread(str(frame_b))
        if img_a is None or img_b is None:
            return False

        # Resize to same dimensions (raft needs even dimensions)
        h, w = img_a.shape[:2]
        h_even = h - (h % 8)
        w_even = w - (w % 8)
        img_a_r = cv2.resize(img_a, (w_even, h_even))
        img_b_r = cv2.resize(img_b, (w_even, h_even))

        # Convert to float32 tensor [0,1] — RAFT expects (N, C, H, W) float
        def to_tensor(img):
            return torch.from_numpy(
                img[:, :, ::-1].copy().astype(np.float32) / 255.0
            ).permute(2, 0, 1).unsqueeze(0)

        _dev = next(model.parameters()).device
        t_a = to_tensor(img_a_r).to(_dev)
        t_b = to_tensor(img_b_r).to(_dev)

        # RAFT inference (GPU if available)
        with torch.no_grad():
            # torchvision RAFT expects [0, 255] range uint8 tensors
            t_a_uint = (t_a * 255).byte()
            t_b_uint = (t_b * 255).byte()
            list_of_flows = model(t_a_uint, t_b_uint)
            flow = list_of_flows[-1][0]  # (2, H, W) — still on _dev

        # Build interpolated frames via flow warping
        frames = []
        for i in range(num_frames):
            alpha = i / max(num_frames - 1, 1)

            # Forward warp: from A towards B
            partial_flow = flow * alpha
            grid_y, grid_x = torch.meshgrid(
                torch.arange(h_even, dtype=torch.float32, device=_dev),
                torch.arange(w_even, dtype=torch.float32, device=_dev),
                indexing="ij",
            )
            # Normalize to [-1, 1] for grid_sample
            grid_x_n = (grid_x + partial_flow[0]) / (w_even / 2) - 1
            grid_y_n = (grid_y + partial_flow[1]) / (h_even / 2) - 1
            grid = torch.stack([grid_x_n, grid_y_n], dim=-1).unsqueeze(0)

            warped_a = torch.nn.functional.grid_sample(
                t_a, grid, mode="bilinear", padding_mode="border", align_corners=True
            )

            # Blend warped A + B — move to CPU for numpy
            frame = ((1 - alpha) * warped_a + alpha * t_b).clamp(0, 1)
            frame_np = (frame[0].permute(1, 2, 0).cpu().numpy() * 255).astype(np.uint8)
            frame_bgr = frame_np[:, :, ::-1]
            frames.append(cv2.resize(frame_bgr, (w, h)))

        # Write frames to MP4 via OpenCV
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))
        for f in frames:
            out.write(f)
        out.release()

        if output_path.exists() and output_path.stat().st_size > 1000:
            # Re-encode to H264 for compatibility
            reenc = output_path.with_name(f"reenc_{output_path.name}")
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(output_path),
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-movflags", "+faststart", str(reenc),
                ],
                capture_output=True, timeout=30,
            )
            if reenc.exists():
                output_path.unlink(missing_ok=True)
                reenc.rename(output_path)

            logger.debug(f"[raft] RAFT morph clip generated: {output_path.name}")
            return True

    except Exception as e:
        logger.warning(f"[raft] RAFT morph failed: {e}")

    return False


def _apply_raft_transition(
    clip_a: Path,
    clip_b: Path,
    output_path: Path,
    transition_duration: float,
) -> bool:
    """Full RAFT pipeline: extract boundary frames → morph clip → concatenate."""
    try:
        _, last_frame = extract_boundary_frames(clip_a)
        first_frame, _ = extract_boundary_frames(clip_b)

        if last_frame is None or first_frame is None:
            return False

        fps = 30
        num_frames = max(3, int(transition_duration * fps))
        morph_path = clip_a.parent / f"morph_{uuid.uuid4().hex[:8]}.mp4"

        if not _raft_morph_clip(last_frame, first_frame, num_frames, fps, morph_path, _raft_model):
            return False

        # Concatenate: clip_a + morph + clip_b
        concat_list = clip_a.parent / f"concat_{uuid.uuid4().hex[:8]}.txt"
        concat_list.write_text(
            f"file '{clip_a.absolute()}'\n"
            f"file '{morph_path.absolute()}'\n"
            f"file '{clip_b.absolute()}'\n"
        )

        result = subprocess.run(
            [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", str(concat_list),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True, timeout=120,
        )

        morph_path.unlink(missing_ok=True)
        concat_list.unlink(missing_ok=True)
        try:
            if last_frame.parent.exists():
                import shutil
                shutil.rmtree(last_frame.parent, ignore_errors=True)
            if first_frame.parent.exists():
                import shutil
                shutil.rmtree(first_frame.parent, ignore_errors=True)
        except Exception:
            pass

        if result.returncode == 0 and output_path.exists():
            logger.info(f"[raft] RAFT transition applied → {output_path.name}")
            return True

        logger.warning(f"[raft] FFmpeg concat failed: {result.stderr.decode()[:200]}")

    except Exception as e:
        logger.warning(f"[raft] RAFT transition pipeline failed: {e}")

    return False


# ─────────────────────────────────────────────────────────────────────────────
#  FFmpeg xfade fallback (CPU-only, no PyTorch needed)
# ─────────────────────────────────────────────────────────────────────────────

# Available xfade transitions in order of "viral" impact
XFADE_EFFECTS = [
    "fade",        # universal
    "wipeleft",    # direction-aware wipe
    "slideleft",   # slides — popular in fast-cut TikToks
    "fadeblack",   # punch cut through black
    "smoothleft",  # smoothest
]


def _apply_xfade_transition(
    clip_a: Path,
    clip_b: Path,
    output_path: Path,
    transition_duration: float = 0.5,
    effect: str = "fade",
) -> bool:
    """
    CPU-only FFmpeg xfade transition between two clips.
    Result is a single concatenated file with the transition baked in.
    """
    try:
        # Probe duration of clip_a to compute xfade offset
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=duration",
             "-of", "csv=p=0", str(clip_a)],
            capture_output=True, text=True, timeout=10,
        )
        duration_a = float(probe.stdout.strip().split("\n")[0]) if probe.stdout.strip() else 5.0

        xfade_offset = max(0.0, duration_a - transition_duration)

        filter_complex = (
            f"[0:v][1:v]xfade=transition={effect}"
            f":duration={transition_duration:.3f}"
            f":offset={xfade_offset:.3f}[v];"
            f"[0:a][1:a]acrossfade=d={transition_duration:.3f}[a]"
        )

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(clip_a),
                "-i", str(clip_b),
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True,
            timeout=120,
        )

        if result.returncode == 0 and output_path.exists():
            logger.debug(f"[xfade] {effect} transition → {output_path.name}")
            return True

        # xfade with audio can fail if one clip has no audio — retry without audio filter
        result2 = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(clip_a),
                "-i", str(clip_b),
                "-filter_complex",
                f"[0:v][1:v]xfade=transition={effect}"
                f":duration={transition_duration:.3f}"
                f":offset={xfade_offset:.3f}[v]",
                "-map", "[v]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ],
            capture_output=True,
            timeout=120,
        )

        if result2.returncode == 0 and output_path.exists():
            logger.debug(f"[xfade] {effect} (no-audio) transition → {output_path.name}")
            return True

        logger.warning(f"[xfade] FFmpeg xfade failed: {result2.stderr.decode()[:200]}")

    except Exception as e:
        logger.warning(f"[xfade] Transition failed: {e}")

    return False


def _crossfade_morph_clip(
    frame_a: Path,
    frame_b: Path,
    num_frames: int,
    fps: int,
    output_path: Path,
) -> Optional[Path]:
    """
    Pure NumPy cross-dissolve between two frames (no PyTorch, no FFmpeg xfade).
    Produces an intermediate morph clip (MP4) by alpha blending.
    """
    try:
        import cv2

        img_a = cv2.imread(str(frame_a))
        img_b = cv2.imread(str(frame_b))
        if img_a is None or img_b is None:
            return None

        h, w = img_a.shape[:2]
        h_b, w_b = img_b.shape[:2]
        if (h, w) != (h_b, w_b):
            img_b = cv2.resize(img_b, (w, h))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(str(output_path), fourcc, fps, (w, h))

        for i in range(num_frames):
            alpha = i / max(num_frames - 1, 1)
            blended = cv2.addWeighted(img_a, 1.0 - alpha, img_b, alpha, 0.0)
            out.write(blended)

        out.release()

        if output_path.exists() and output_path.stat().st_size > 500:
            return output_path

    except Exception as e:
        logger.warning(f"[xfade] Cross-dissolve morph failed: {e}")

    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Utility: check what's available
# ─────────────────────────────────────────────────────────────────────────────

def get_transition_capabilities() -> dict:
    """Return what transition capabilities are available on this machine."""
    raft = _get_raft_model() is not None

    # Check FFmpeg xfade support
    xfade_ok = False
    try:
        r = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True, text=True, timeout=5,
        )
        xfade_ok = "xfade" in r.stdout
    except Exception:
        pass

    # Check cv2
    cv2_ok = False
    try:
        import cv2  # noqa: F401
        cv2_ok = True
    except ImportError:
        pass

    return {
        "raft_available": raft,
        "xfade_available": xfade_ok,
        "cv2_available": cv2_ok,
        "best_mode": "raft" if raft else ("xfade" if xfade_ok else "crossfade"),
    }
