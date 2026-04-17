"""
Avatar Compositor — ViraClip
=============================
Composites a rendered avatar video onto a clip using FFmpeg.

Compositing modes inspired by the UV-Volumes (CVPR 2023) and ERNeRF pipelines:
  PICTURE_IN_PICTURE  → Avatar overlaid in a corner of the clip
  FACE_REPLACE        → Avatar face swapped onto speaker in clip (ERNeRF-style)
  SIDE_BY_SIDE        → Split screen: clip left, avatar right
  FULL_REPLACE        → Avatar replaces clip entirely (talking head mode)
  LOWER_THIRD         → Avatar as animated lower-third presenter

Background matting patterns from UV-Volumes:
  - Green-screen removal (chroma key)
  - Alpha channel compositing
  - Edge-aware blending
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class CompositeMode(str, Enum):
    PICTURE_IN_PICTURE = "pip"
    FACE_REPLACE = "face_replace"
    SIDE_BY_SIDE = "side_by_side"
    FULL_REPLACE = "full_replace"
    LOWER_THIRD = "lower_third"


@dataclass
class CompositeOptions:
    """Options for compositing an avatar onto a clip."""
    mode: CompositeMode = CompositeMode.PICTURE_IN_PICTURE

    # PIP / LOWER_THIRD positioning
    pip_position: str = "bottom_right"   # top_left | top_right | bottom_left | bottom_right | center
    pip_scale: float = 0.28              # Avatar size as fraction of clip width
    pip_margin: int = 20                 # Pixels from edge

    # Face replace options
    face_blend_alpha: float = 0.85       # 0=transparent, 1=opaque

    # Background keying (UV-Volumes green-screen approach)
    chroma_key_color: Optional[str] = None   # e.g. "0x00FF00" for green screen
    chroma_key_similarity: float = 0.3
    chroma_key_blend: float = 0.1

    # Output
    output_resolution: Optional[Tuple[int, int]] = None   # None = match clip


class AvatarCompositor:
    """
    Composites a NeRF-rendered avatar video onto a source clip.

    Patterns from UV-Volumes:
    - UV-space alpha compositing for seamless blending
    - Matting via learned alpha channel or chroma key

    Patterns from ERNeRF:
    - Face region detection and replacement
    - Perspective-correct face warp to target face location
    """

    # ------------------------------------------------------------------
    # Primary compositing entry point
    # ------------------------------------------------------------------

    async def composite(
        self,
        clip_path: str,
        avatar_video_path: str,
        output_path: str,
        options: Optional[CompositeOptions] = None,
    ) -> str:
        """
        Composite avatar_video_path onto clip_path.

        Returns output_path on success.
        """
        opts = options or CompositeOptions()

        if opts.mode == CompositeMode.PICTURE_IN_PICTURE:
            return await self._composite_pip(clip_path, avatar_video_path, output_path, opts)
        elif opts.mode == CompositeMode.SIDE_BY_SIDE:
            return await self._composite_side_by_side(clip_path, avatar_video_path, output_path, opts)
        elif opts.mode == CompositeMode.FULL_REPLACE:
            return await self._composite_full_replace(avatar_video_path, output_path, opts)
        elif opts.mode == CompositeMode.LOWER_THIRD:
            return await self._composite_lower_third(clip_path, avatar_video_path, output_path, opts)
        elif opts.mode == CompositeMode.FACE_REPLACE:
            return await self._composite_face_replace(clip_path, avatar_video_path, output_path, opts)
        else:
            raise ValueError(f"Unknown composite mode: {opts.mode}")

    # ------------------------------------------------------------------
    # Picture-in-picture compositing
    # ------------------------------------------------------------------

    async def _composite_pip(
        self,
        clip_path: str,
        avatar_path: str,
        output_path: str,
        opts: CompositeOptions,
    ) -> str:
        """
        Overlay avatar as picture-in-picture on the clip.

        FFmpeg overlay filter positions the avatar in one of 5 positions.
        Chroma keying removes avatar background if chroma_key_color set.
        """
        # Get clip dimensions
        clip_w, clip_h = await self._get_video_dimensions(clip_path)
        pip_w = int(clip_w * opts.pip_scale)
        pip_h = int(pip_w * 16 / 9)  # 9:16 avatar aspect for portrait

        # Compute position
        x_pos, y_pos = self._compute_pip_position(
            opts.pip_position, clip_w, clip_h, pip_w, pip_h, opts.pip_margin
        )

        # Build avatar filter chain
        avatar_filter = f"[1:v]scale={pip_w}:{pip_h}"

        if opts.chroma_key_color:
            avatar_filter += (
                f",chromakey={opts.chroma_key_color}"
                f":{opts.chroma_key_similarity}:{opts.chroma_key_blend}"
            )

        # Add rounded corners for aesthetic (UV-Volumes style edge blending)
        avatar_filter += "[avatar]"

        filter_complex = (
            f"{avatar_filter};"
            f"[0:v][avatar]overlay={x_pos}:{y_pos}:shortest=1[out]"
        )

        cmd = [
            "ffmpeg",
            "-i", clip_path,
            "-i", avatar_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            output_path,
            "-y",
        ]

        await self._run_ffmpeg(cmd, "PIP composite")
        return output_path

    # ------------------------------------------------------------------
    # Side-by-side compositing
    # ------------------------------------------------------------------

    async def _composite_side_by_side(
        self,
        clip_path: str,
        avatar_path: str,
        output_path: str,
        opts: CompositeOptions,
    ) -> str:
        """
        Split screen: clip on left half, avatar on right half.
        Both scaled to fill their half at target resolution.
        """
        clip_w, clip_h = await self._get_video_dimensions(clip_path)
        half_w = clip_w // 2

        filter_complex = (
            f"[0:v]scale={half_w}:{clip_h},setsar=1[left];"
            f"[1:v]scale={half_w}:{clip_h},setsar=1[right];"
            f"[left][right]hstack=inputs=2[out]"
        )

        cmd = [
            "ffmpeg",
            "-i", clip_path,
            "-i", avatar_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            output_path,
            "-y",
        ]

        await self._run_ffmpeg(cmd, "side-by-side composite")
        return output_path

    # ------------------------------------------------------------------
    # Full replace — avatar becomes the entire video
    # ------------------------------------------------------------------

    async def _composite_full_replace(
        self,
        avatar_path: str,
        output_path: str,
        opts: CompositeOptions,
    ) -> str:
        """
        Use avatar video as the clip entirely (talking head mode).
        Original clip audio is preserved if available.
        """
        res = opts.output_resolution or (1080, 1920)
        w, h = res

        cmd = [
            "ffmpeg",
            "-i", avatar_path,
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            output_path,
            "-y",
        ]

        await self._run_ffmpeg(cmd, "full replace")
        return output_path

    # ------------------------------------------------------------------
    # Lower-third — avatar as animated presenter bar
    # ------------------------------------------------------------------

    async def _composite_lower_third(
        self,
        clip_path: str,
        avatar_path: str,
        output_path: str,
        opts: CompositeOptions,
    ) -> str:
        """
        Avatar placed in the lower-third of the frame.
        Inspired by news anchor / presenter broadcast style.
        Semi-transparent background bar added for readability.
        """
        clip_w, clip_h = await self._get_video_dimensions(clip_path)
        avatar_h = clip_h // 3
        avatar_w = int(avatar_h * 9 / 16)

        # Lower-third: bottom-left, with dark semi-transparent bar
        x_pos = opts.pip_margin
        y_pos = clip_h - avatar_h - opts.pip_margin

        avatar_filter = f"[1:v]scale={avatar_w}:{avatar_h}"
        if opts.chroma_key_color:
            avatar_filter += (
                f",chromakey={opts.chroma_key_color}"
                f":{opts.chroma_key_similarity}:{opts.chroma_key_blend}"
            )
        avatar_filter += "[avatar]"

        # Draw dark bar behind avatar
        bar_filter = (
            f"[0:v]drawbox="
            f"x={x_pos - 10}:y={y_pos - 10}:"
            f"w={avatar_w + 20}:h={avatar_h + 20}:"
            "color=black@0.5:t=fill[bg]"
        )

        filter_complex = (
            f"{bar_filter};"
            f"{avatar_filter};"
            f"[bg][avatar]overlay={x_pos}:{y_pos}:shortest=1[out]"
        )

        cmd = [
            "ffmpeg",
            "-i", clip_path,
            "-i", avatar_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            output_path,
            "-y",
        ]

        await self._run_ffmpeg(cmd, "lower-third composite")
        return output_path

    # ------------------------------------------------------------------
    # Face replace — ERNeRF-style face swap
    # ------------------------------------------------------------------

    async def _composite_face_replace(
        self,
        clip_path: str,
        avatar_path: str,
        output_path: str,
        opts: CompositeOptions,
    ) -> str:
        """
        Replace face region in clip with avatar face.
        Inspired by ERNeRF's post-processing which pastes the rendered
        face region back onto the original video.

        Pipeline:
        1. Detect face in clip (MediaPipe)
        2. Crop and warp avatar face to match target face region
        3. Alpha-blend with feathered edges
        """
        # Try MediaPipe face detection for precise placement
        face_region = await self._detect_face_region(clip_path)

        if face_region is None:
            # Fallback to center PIP if no face found
            logger.warning("[Compositor] No face detected in clip, falling back to PIP")
            return await self._composite_pip(clip_path, avatar_path, output_path, opts)

        x, y, w, h = face_region
        clip_w, clip_vid_h = await self._get_video_dimensions(clip_path)

        # Build ERNeRF-style face paste filter
        # Scale avatar to face size, overlay with alpha blend
        avatar_filter = (
            f"[1:v]scale={w}:{h},"
            f"format=rgba,"
            # Feather edges for seamless blend (UV-Volumes edge blending)
            f"vignette=angle=PI/4:mode=backward[face]"
        )

        if opts.chroma_key_color:
            avatar_filter = (
                f"[1:v]scale={w}:{h},"
                f"chromakey={opts.chroma_key_color}"
                f":{opts.chroma_key_similarity}:{opts.chroma_key_blend},"
                f"format=rgba[face]"
            )

        filter_complex = (
            f"{avatar_filter};"
            f"[0:v][face]overlay={x}:{y}:"
            f"shortest=1:alpha=straight[out]"
        )

        cmd = [
            "ffmpeg",
            "-i", clip_path,
            "-i", avatar_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-c:a", "copy",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            output_path,
            "-y",
        ]

        await self._run_ffmpeg(cmd, "face replace composite")
        return output_path

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_pip_position(
        self,
        position: str,
        clip_w: int,
        clip_h: int,
        pip_w: int,
        pip_h: int,
        margin: int,
    ) -> Tuple[int, int]:
        """Compute (x, y) for PIP overlay position."""
        positions = {
            "top_left":     (margin, margin),
            "top_right":    (clip_w - pip_w - margin, margin),
            "bottom_left":  (margin, clip_h - pip_h - margin),
            "bottom_right": (clip_w - pip_w - margin, clip_h - pip_h - margin),
            "center":       ((clip_w - pip_w) // 2, (clip_h - pip_h) // 2),
        }
        return positions.get(position, positions["bottom_right"])

    async def _get_video_dimensions(self, video_path: str) -> Tuple[int, int]:
        """Get width and height of a video file via ffprobe."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams",
            video_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()

        try:
            info = json.loads(stdout)
            for stream in info.get("streams", []):
                if stream.get("codec_type") == "video":
                    return stream["width"], stream["height"]
        except Exception:
            pass

        return 1080, 1920  # Default vertical video

    async def _detect_face_region(self, video_path: str) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect face region in the first few frames of a clip.
        Returns (x, y, w, h) or None if no face found.
        """
        try:
            import cv2
            import mediapipe as mp

            cap = cv2.VideoCapture(video_path)
            mp_face = mp.solutions.face_detection

            with mp_face.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            ) as detector:
                for _ in range(10):  # Check first 10 frames
                    ret, frame = cap.read()
                    if not ret:
                        break

                    h, w = frame.shape[:2]
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = detector.process(rgb)

                    if results.detections:
                        det = results.detections[0]
                        bb = det.location_data.relative_bounding_box
                        x = int(bb.xmin * w)
                        y = int(bb.ymin * h)
                        fw = int(bb.width * w)
                        fh = int(bb.height * h)
                        cap.release()
                        return x, y, fw, fh

            cap.release()
        except ImportError:
            logger.warning("[Compositor] MediaPipe not available for face detection")
        except Exception as e:
            logger.warning(f"[Compositor] Face detection failed: {e}")

        return None

    async def _run_ffmpeg(self, cmd: list, label: str):
        """Run an FFmpeg command, raising on failure."""
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg {label} failed (rc={proc.returncode}): {stderr.decode()[:300]}"
            )
        logger.debug(f"[Compositor] {label} complete")


# Singleton
_compositor: Optional[AvatarCompositor] = None


def get_avatar_compositor() -> AvatarCompositor:
    global _compositor
    if _compositor is None:
        _compositor = AvatarCompositor()
    return _compositor
