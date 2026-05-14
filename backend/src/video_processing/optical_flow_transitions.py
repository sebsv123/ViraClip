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

from src import gpu_utils

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
                    *gpu_utils.ffmpeg_codec_flags("medium"),
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
                *gpu_utils.ffmpeg_codec_flags("medium"),
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
                *gpu_utils.ffmpeg_codec_flags("medium"),
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
                *gpu_utils.ffmpeg_codec_flags("medium"),
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


# ─────────────────────────────────────────────────────────────────────────────
#  Legacy Transition Functions (Migrated from video_utils.py)
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path
from typing import List, Dict, Any
from moviepy import VideoFileClip, CompositeVideoClip, concatenate_videoclips
from moviepy.video.fx import FadeIn, FadeOut


def get_available_transitions() -> List[str]:
    """Get list of available transition video files."""
    transitions_dir = Path(__file__).parent.parent / "transitions"
    if not transitions_dir.exists():
        logger.warning("Transitions directory not found")
        return []

    transition_files = []
    for file_path in transitions_dir.glob("*.mp4"):
        transition_files.append(str(file_path))

    logger.info(f"Found {len(transition_files)} transition files")
    return transition_files


def apply_transition_effect(
    clip1_path: Path, clip2_path: Path, transition_path: Path, output_path: Path
) -> bool:
    """Apply transition effect between two clips using a transition video."""
    clip1 = None
    clip2 = None
    transition = None
    clip1_tail = None
    clip2_intro = None
    clip2_remainder = None
    intro_segment = None
    final_clip = None

    try:
        # Load clips
        clip1 = VideoFileClip(str(clip1_path))
        clip2 = VideoFileClip(str(clip2_path))
        transition = VideoFileClip(str(transition_path))

        # Keep the transition window within both clips so the output still matches
        # the current clip's duration and metadata.
        transition_duration = min(1.5, transition.duration, clip1.duration, clip2.duration)
        if transition_duration <= 0:
            logger.warning("Transition duration is zero, skipping transition effect")
            return False

        transition = transition.subclipped(0, transition_duration)

        # Resize transition to match clip dimensions
        clip_size = clip2.size
        transition = transition.resized(clip_size)

        # Build a transition intro from the previous clip tail over the first
        # part of the current clip so the exported file keeps clip2's duration.
        clip1_tail_start = max(0, clip1.duration - transition_duration)
        clip1_tail = clip1.subclipped(clip1_tail_start, clip1.duration).with_effects(
            [FadeOut(transition_duration)]
        )
        clip2_intro = clip2.subclipped(0, transition_duration).with_effects(
            [FadeIn(transition_duration)]
        )

        intro_segment = CompositeVideoClip(
            [clip1_tail, clip2_intro, transition], size=clip_size
        ).with_duration(transition_duration)
        if clip2_intro.audio is not None:
            intro_segment = intro_segment.with_audio(clip2_intro.audio)

        final_segments = [intro_segment]
        if clip2.duration > transition_duration:
            clip2_remainder = clip2.subclipped(transition_duration, clip2.duration)
            final_segments.append(clip2_remainder)

        final_clip = (
            concatenate_videoclips(final_segments, method="compose")
            if len(final_segments) > 1
            else intro_segment
        )

        # Write output
        from .clip_creation import VideoProcessor
        processor = VideoProcessor()
        encoding_settings = processor.get_optimal_encoding_settings("high")

        final_clip.write_videofile(
            str(output_path),
            temp_audiofile=str(output_path.parent / f"temp-audio-{output_path.stem}.m4a"),
            remove_temp=True,
            logger=None,
            **encoding_settings,
        )

        logger.info(f"Applied transition effect: {output_path}")
        return True

    except Exception as e:
        logger.error(f"Error applying transition effect: {e}")
        return False
    finally:
        for clip in (
            final_clip,
            intro_segment,
            clip2_remainder,
            clip2_intro,
            clip1_tail,
            transition,
            clip2,
            clip1,
        ):
            if clip is not None:
                try:
                    clip.close()
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════════
# TransitionSelector — AI Context-Aware Transition Selection (Phase 3)
# ═══════════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, Dict, Any
import random


class TransitionType(Enum):
    """Available transition types."""
    FADE = auto()
    DISSOLVE = auto()
    WIPE_LEFT = auto()
    WIPE_RIGHT = auto()
    WIPE_UP = auto()
    WIPE_DOWN = auto()
    ZOOM_IN = auto()
    ZOOM_OUT = auto()
    SLIDE_LEFT = auto()
    SLIDE_RIGHT = auto()
    OPTICAL_FLOW = auto()  # RAFT-based morph
    GLITCH = auto()
    FLASH = auto()


@dataclass
class TransitionContext:
    """Context for AI transition selection."""
    segment_a_text: str = ""           # Previous segment transcript
    segment_b_text: str = ""           # Next segment transcript  
    segment_a_mood: str = "neutral"    # Mood of previous segment
    segment_b_mood: str = "neutral"    # Mood of next segment
    topic_shift: bool = False          # Is there a topic change?
    emotional_shift: bool = False      # Is there an emotional shift?
    is_hook_boundary: bool = False     # Is this a hook → content boundary?
    video_style: str = "default"       # Style: viral, cinematic, minimal


class TransitionSelector:
    """
    AI-driven transition selection based on context.
    
    Rules:
    - Emotional shifts → Dramatic transitions (flash, glitch, zoom)
    - Topic changes → Smooth transitions (fade, dissolve, wipe)
    - Similar content → Minimal/no transition
    - Fast-paced content → Quick transitions (wipe, slide)
    - Cinematic content → Smooth optical flow or dissolves
    """
    
    # Transition categories by mood/context
    TRANSITION_CATEGORIES = {
        "dramatic": [TransitionType.FLASH, TransitionType.GLITCH, TransitionType.ZOOM_IN],
        "smooth": [TransitionType.FADE, TransitionType.DISSOLVE, TransitionType.OPTICAL_FLOW],
        "energetic": [TransitionType.WIPE_LEFT, TransitionType.WIPE_RIGHT, TransitionType.SLIDE_LEFT],
        "subtle": [TransitionType.FADE, TransitionType.ZOOM_OUT],
        "topic_change": [TransitionType.WIPE_LEFT, TransitionType.WIPE_RIGHT, TransitionType.DISSOLVE],
    }
    
    def __init__(self):
        self.available_transitions = self._scan_available_transitions()
    
    def _scan_available_transitions(self) -> Dict[TransitionType, bool]:
        """Scan for available transition types (files, models, etc.)."""
        # Check for optical flow capability
        has_optical_flow = _get_raft_model() is not None
        
        # Check for transition video files
        transitions_dir = Path(__file__).parent.parent.parent / "transitions"
        has_transition_files = transitions_dir.exists() and list(transitions_dir.glob("*.mp4"))
        
        return {
            TransitionType.FADE: True,  # Always available (FFmpeg)
            TransitionType.DISSOLVE: True,
            TransitionType.WIPE_LEFT: True,
            TransitionType.WIPE_RIGHT: True,
            TransitionType.WIPE_UP: True,
            TransitionType.WIPE_DOWN: True,
            TransitionType.ZOOM_IN: True,
            TransitionType.ZOOM_OUT: True,
            TransitionType.SLIDE_LEFT: True,
            TransitionType.SLIDE_RIGHT: True,
            TransitionType.OPTICAL_FLOW: has_optical_flow,
            TransitionType.GLITCH: has_transition_files,
            TransitionType.FLASH: True,  # Can generate programmatically
        }
    
    def select_transition(
        self,
        context: TransitionContext,
        duration: float = 0.5,
    ) -> Optional[TransitionType]:
        """
        Select the best transition type based on context.
        
        Args:
            context: TransitionContext with segment information
            duration: Desired transition duration (seconds)
        
        Returns:
            Selected TransitionType or None for no transition (cut)
        """
        # Rule 1: No transition for very similar content
        if not context.topic_shift and not context.emotional_shift:
            if context.video_style in ("minimal", "viral_fast"):
                logger.debug("[Transition] Similar content + minimal style → no transition")
                return None
        
        candidates = []
        
        # Rule 2: Emotional shifts → dramatic
        if context.emotional_shift:
            candidates.extend(self.TRANSITION_CATEGORIES["dramatic"])
        
        # Rule 3: Topic changes → smooth directional
        elif context.topic_shift:
            candidates.extend(self.TRANSITION_CATEGORIES["topic_change"])
        
        # Rule 4: Hook boundaries → energetic
        elif context.is_hook_boundary:
            candidates.extend(self.TRANSITION_CATEGORIES["energetic"])
        
        # Rule 5: Default based on style
        else:
            if context.video_style == "cinematic":
                candidates.extend(self.TRANSITION_CATEGORIES["smooth"])
            elif context.video_style == "viral_fast":
                candidates.extend(self.TRANSITION_CATEGORIES["energetic"])
            else:
                candidates.extend(self.TRANSITION_CATEGORIES["subtle"])
        
        # Filter by availability
        available = [t for t in candidates if self.available_transitions.get(t, False)]
        
        if not available:
            # Fallback to always-available transitions
            available = [TransitionType.FADE, TransitionType.DISSOLVE]
        
        # Weighted random selection (prefer first candidates)
        weights = [len(available) - i for i in range(len(available))]
        selected = random.choices(available, weights=weights, k=1)[0]
        
        logger.info(f"[Transition] Selected {selected.name} for context: {self._context_summary(context)}")
        return selected
    
    def _context_summary(self, context: TransitionContext) -> str:
        """Generate a summary string for logging."""
        parts = []
        if context.topic_shift:
            parts.append("topic_change")
        if context.emotional_shift:
            parts.append("emotional")
        if context.is_hook_boundary:
            parts.append("hook")
        parts.append(f"style={context.video_style}")
        return ", ".join(parts) if parts else "default"
    
    def get_transition_duration(
        self,
        transition_type: TransitionType,
        base_duration: float = 0.5,
        context: Optional[TransitionContext] = None,
    ) -> float:
        """
        Get optimal transition duration based on type and context.
        
        Args:
            transition_type: The selected transition type
            base_duration: Base duration in seconds
            context: Optional context for adjustment
        
        Returns:
            Recommended duration in seconds
        """
        # Adjust based on transition type
        multipliers = {
            TransitionType.FADE: 1.0,
            TransitionType.DISSOLVE: 1.2,
            TransitionType.OPTICAL_FLOW: 1.5,
            TransitionType.FLASH: 0.3,
            TransitionType.GLITCH: 0.4,
            TransitionType.ZOOM_IN: 0.8,
            TransitionType.ZOOM_OUT: 0.8,
        }
        
        multiplier = multipliers.get(transition_type, 1.0)
        duration = base_duration * multiplier
        
        # Adjust for style
        if context:
            if context.video_style == "viral_fast":
                duration *= 0.7  # Faster transitions
            elif context.video_style == "cinematic":
                duration *= 1.3  # Slower, more deliberate
        
        return round(duration, 2)


def create_context_aware_transition(
    clip1_path: Path,
    clip2_path: Path,
    output_path: Path,
    segment_a_text: str = "",
    segment_b_text: str = "",
    video_style: str = "default",
) -> bool:
    """
    High-level function to create a context-aware transition between clips.
    
    Args:
        clip1_path: First clip
        clip2_path: Second clip
        output_path: Output path
        segment_a_text: Transcript of first segment
        segment_b_text: Transcript of second segment
        video_style: Style preference (viral_fast, cinematic, minimal, default)
    
    Returns:
        True on success
    """
    # Build context
    context = TransitionContext(
        segment_a_text=segment_a_text,
        segment_b_text=segment_b_text,
        video_style=video_style,
        topic_shift=_detect_topic_shift(segment_a_text, segment_b_text),
        emotional_shift=_detect_emotional_shift(segment_a_text, segment_b_text),
    )
    
    # Select transition
    selector = TransitionSelector()
    transition_type = selector.select_transition(context)
    
    if transition_type is None:
        # No transition needed — simple concatenate
        return _simple_concatenate(clip1_path, clip2_path, output_path)
    
    # Get duration
    duration = selector.get_transition_duration(transition_type, context=context)
    
    # Apply transition based on type
    if transition_type == TransitionType.OPTICAL_FLOW:
        return apply_optical_flow_transition(clip1_path, clip2_path, output_path, duration)
    elif transition_type in (TransitionType.FADE, TransitionType.DISSOLVE):
        # Use xfade filter
        return _apply_xfade_transition(clip1_path, clip2_path, output_path, transition_type, duration)
    else:
        # Use transition video if available
        transition_file = _get_transition_file(transition_type)
        if transition_file:
            return apply_transition_effect(clip1_path, clip2_path, transition_file, output_path)
        else:
            # Fallback to simple fade
            return _apply_xfade_transition(clip1_path, clip2_path, output_path, TransitionType.FADE, duration)


def _detect_topic_shift(text_a: str, text_b: str) -> bool:
    """Detect if there's a topic shift between segments."""
    # Simple heuristic: compare keyword overlap
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())
    
    if not words_a or not words_b:
        return False
    
    overlap = len(words_a & words_b)
    total = len(words_a | words_b)
    
    if total == 0:
        return False
    
    similarity = overlap / total
    return similarity < 0.3  # Less than 30% overlap = topic shift


def _detect_emotional_shift(text_a: str, text_b: str) -> bool:
    """Detect emotional shift between segments."""
    # Simple keyword-based detection
    emotional_markers = [
        "wow", "amazing", "incredible", "shocking", "surprising",
        "terrible", "awful", "fantastic", "unbelievable", "omg"
    ]
    
    has_emotion_a = any(marker in text_a.lower() for marker in emotional_markers)
    has_emotion_b = any(marker in text_b.lower() for marker in emotional_markers)
    
    return has_emotion_a != has_emotion_b


def _simple_concatenate(clip1: Path, clip2: Path, output: Path) -> bool:
    """Simple concatenation without transitions."""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip1),
            "-i", str(clip2),
            "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
            "-map", "[outv]", "-map", "[outa]",
            *gpu_utils.ffmpeg_codec_flags("medium"),
            "-c:a", "aac", "-b:a", "192k",
            str(output)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return result.returncode == 0
    except Exception as e:
        logger.error(f"Simple concatenate failed: {e}")
        return False


def _apply_xfade_transition(
    clip1: Path,
    clip2: Path,
    output: Path,
    transition_type: TransitionType,
    duration: float,
) -> bool:
    """Apply FFmpeg xfade transition."""
    try:
        # Map TransitionType to xfade transition name
        xfade_map = {
            TransitionType.FADE: "fade",
            TransitionType.DISSOLVE: "fadeblack",
            TransitionType.WIPE_LEFT: "wipeleft",
            TransitionType.WIPE_RIGHT: "wiperight",
            TransitionType.WIPE_UP: "wipeup",
            TransitionType.WIPE_DOWN: "wipedown",
        }
        
        transition_name = xfade_map.get(transition_type, "fade")
        
        # Get clip1 duration for transition offset
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(clip1)
        ]
        probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        clip1_duration = float(probe_result.stdout.strip())
        
        offset = max(0, clip1_duration - duration)
        
        filter_complex = (
            f"[0:v]format=pix_fmts=yuv420p[va];"
            f"[1:v]format=pix_fmts=yuv420p[vb];"
            f"[va][vb]xfade=transition={transition_name}:duration={duration}:offset={offset}[vout];"
            f"[0:a][1:a]acrossfade=d={duration}[aout]"
        )
        
        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip1),
            "-i", str(clip2),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            *gpu_utils.ffmpeg_codec_flags("medium"),
            "-c:a", "aac", "-b:a", "192k",
            str(output)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        if result.returncode == 0:
            logger.info(f"✅ xfade transition applied: {transition_name}, dur={duration:.2f}s")
            return True
        else:
            logger.error(f"xfade failed: {result.stderr[-300:]}")
            return False
            
    except Exception as e:
        logger.error(f"xfade transition error: {e}")
        return False


def _get_transition_file(transition_type: TransitionType) -> Optional[Path]:
    """Get path to transition video file if available."""
    transitions_dir = Path(__file__).parent.parent.parent / "transitions"
    if not transitions_dir.exists():
        return None
    
    # Map transition type to filename pattern
    pattern_map = {
        TransitionType.GLITCH: "*glitch*.mp4",
        TransitionType.FLASH: "*flash*.mp4",
        TransitionType.ZOOM_IN: "*zoom*.mp4",
    }
    
    pattern = pattern_map.get(transition_type)
    if not pattern:
        return None
    
    matches = list(transitions_dir.glob(pattern))
    if matches:
        return matches[0]
    
    return None
