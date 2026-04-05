"""
Clip creation and rendering utilities.
Handles video clip extraction, cropping, zoom effects, and final composition.
"""

from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
import logging
import subprocess
import uuid
import os
import numpy as np

logger = logging.getLogger(__name__)

_PLATFORM_VF: dict = {
    "tiktok":   "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
    "reels":    "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
    "shorts":   "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
    "all":      "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
    "original": None,
}

# Global flag for CrossFade availability (set at module load time)
try:
    from moviepy.video.fx import CrossFadeIn, CrossFadeOut
    CROSSFADE_AVAILABLE = True
except ImportError:
    CROSSFADE_AVAILABLE = False
    CrossFadeIn = None
    CrossFadeOut = None
    logger.debug("CrossFade effects not available in this moviepy version")

VideoFileClip = None
CompositeVideoClip = None
TextClip = None


def _import_moviepy():
    """Lazy import moviepy components."""
    global VideoFileClip, CompositeVideoClip, TextClip
    if VideoFileClip is None:
        from moviepy import VideoFileClip as _VF, CompositeVideoClip as _CV, TextClip as _TC
        VideoFileClip = _VF
        CompositeVideoClip = _CV
        TextClip = _TC
    return VideoFileClip, CompositeVideoClip, TextClip


def round_to_even(value: int) -> int:
    """Round value to nearest even number (required by many codecs)."""
    return value + (value % 2)


def snap_to_word_boundary(video_path: Path, start: float, end: float) -> Tuple[float, float]:
    """
    Adjust clip boundaries to snap to nearest word boundaries for cleaner cuts.
    """
    try:
        from ..utils.video_extraction import load_cached_transcript_data
        data = load_cached_transcript_data(video_path)
        if not data or "words" not in data:
            return start, end

        words = data["words"]
        if not words:
            return start, end

        start_ms = int(start * 1000)
        end_ms = int(end * 1000)

        best_start = start
        best_end = end
        min_start_diff = abs(words[0]["start"] - start_ms)
        min_end_diff = abs(words[0]["end"] - end_ms)

        for word in words:
            ws, we = word["start"], word["end"]
            if abs(ws - start_ms) < min_start_diff:
                min_start_diff = abs(ws - start_ms)
                best_start = ws / 1000.0
            if abs(we - end_ms) < min_end_diff:
                min_end_diff = abs(we - end_ms)
                best_end = we / 1000.0

        if abs(best_start - start) < 0.3:
            start = best_start
        if abs(best_end - end) < 0.3:
            end = best_end

    except Exception as e:
        logger.debug(f"Word boundary snap failed: {e}")

    return max(0, start), max(start + 0.5, end)


def create_dynamic_crop_clip(
    clip,
    trajectory: List[Tuple[float, int, int]],
    target_width: int,
    target_height: int,
) -> Any:
    """
    Create a dynamically cropped clip that follows face trajectory.
    """
    from moviepy import VideoClip as _VC
    import cv2

    orig_w, orig_h = clip.w, clip.h
    target_ratio = target_width / target_height

    def crop_frame(get_frame, t):
        frame = get_frame(t)
        if not trajectory:
            if orig_w / orig_h > target_ratio:
                new_h = orig_h
                new_w = int(new_h * target_ratio)
            else:
                new_w = orig_w
                new_h = int(new_w / target_ratio)
            x0 = (orig_w - new_w) // 2
            y0 = (orig_h - new_h) // 2
            return frame[y0 : y0 + new_h, x0 : x0 + new_w]

        cx, cy = orig_w // 2, orig_h // 2
        for i, (tt, tx, ty) in enumerate(trajectory):
            if abs(tt - t) < 0.5:
                cx, cy = tx, ty
                break

        if orig_w / orig_h > target_ratio:
            new_h = orig_h
            new_w = int(new_h * target_ratio)
        else:
            new_w = orig_w
            new_h = int(new_w / target_ratio)

        x0 = max(0, min(cx - new_w // 2, orig_w - new_w))
        y0 = max(0, min(cy - new_h // 2, orig_h - new_h))

        cropped = frame[y0 : y0 + new_h, x0 : x0 + new_w]
        return cv2.resize(cropped, (target_width, target_height), interpolation=cv2.INTER_LINEAR)

    def make_frame(t):
        return crop_frame(clip.get_frame, t)

    new_clip = _VC(frame_function=make_frame, duration=clip.duration)
    new_clip.fps = clip.fps or 30
    if clip.audio is not None:
        new_clip = new_clip.with_audio(clip.audio)
    return new_clip


def create_optimized_clip(
    video_path: Path,
    start_time: float,
    end_time: float,
    output_path: Path,
    add_subtitles: bool = True,
    font_family: str = "THEBOLDFONT",
    font_size: int = 24,
    font_color: str = "#FFFFFF",
    caption_template: str = "default",
    output_format: str = "vertical",
    split_screen: bool = False,
    hook_title: Optional[str] = None,
    camera_plan: Optional[List[Dict[str, Any]]] = None,
    sync_offset: float = 0.0,
    secondary_video_path: Optional[Path] = None,
    segment: Optional[Dict[str, Any]] = None,
    elite_metadata: Optional[Dict[str, Any]] = None,
    gpu_encoding_settings: Optional[Dict[str, Any]] = None,
    target_platform: str = "tiktok",
) -> bool:
    """
    Create a high-quality clip with resource management and effects.
    """
    VideoFileClip, _, TextClip = _import_moviepy()
    from ..utils.resource_management import ResourceGuard
    from .face_detection import detect_active_speaker_trajectory
    from .subtitles import create_assemblyai_subtitles
    from .audio import mix_background_music

    if segment is None:
        segment = {}

    # ── GUARD: video file must exist before ANY processing ──────────────────
    video_path = Path(video_path)
    if not video_path.exists():
        parent_dir = video_path.parent
        logger.error(
            f"❌ Source video NOT FOUND: {video_path}  "
            f"[clip {start_time:.1f}s-{end_time:.1f}s → {output_path.name}]  "
            f"Likely deleted/moved during EliteAI phase. Check video_service.py."
        )
        try:
            if parent_dir.exists():
                files_in_dir = list(parent_dir.glob("*"))
                logger.error(f"   Parent dir exists. Files: {[f.name for f in files_in_dir[:10]]}")
            else:
                logger.error(f"   Parent dir does NOT exist: {parent_dir}")
        except Exception as e:
            logger.error(f"   Could not list parent dir: {e}")
        return False
    else:
        file_size = video_path.stat().st_size / (1024*1024)
        logger.info(f"✓ Source video verified: {video_path.name} ({file_size:.1f}MB)")
    # ────────────────────────────────────────────────────────────────────────

    guard = ResourceGuard()
    temp_segment_path = None
    try:
        with guard.manage():
            # 1. Word Boundary Snapping
            start_time, end_time = snap_to_word_boundary(video_path, start_time, end_time)
            duration = end_time - start_time
            if duration <= 0:
                logger.error(f"Invalid clip duration: {duration:.1f}s")
                return False

            keep_original = output_format == "original"
            logger.info(f"🚀 Render Start: {start_time:.1f}s-{end_time:.1f}s")

            # 2. Fast Path (ffmpeg stream copy)
            if not add_subtitles and keep_original and not camera_plan:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-ss", str(start_time),
                        "-i", str(video_path), "-t", str(duration),
                        "-c", "copy", "-movflags", "+faststart",
                        str(output_path),
                    ],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    return True

            # 3. PRE-EXTRACT SEGMENT WITH FFMPEG (prevents OOM on large/4K videos)
            # Extract exact segment + scale to portrait before MoviePy touches it
            ffmpeg_timeout = int(os.environ.get("FFMPEG_SEGMENT_TIMEOUT", "300"))
            temp_segment_path = video_path.parent / f"temp_segment_{uuid.uuid4().hex}.mp4"

            logger.info(f"🔧 FFmpeg pre-extraction: {duration:.1f}s segment from {video_path.name}")
            _vf = _PLATFORM_VF.get(target_platform, _PLATFORM_VF["tiktok"])
            _ffmpeg_base = [
                "ffmpeg", "-y",
                "-ss", str(start_time),
                "-i", str(video_path),
                "-t", str(duration),
                "-map", "0:v:0",
                "-map", "0:a?",
            ]
            if _vf:
                _ffmpeg_base += ["-vf", _vf]
            ffmpeg_cmd = _ffmpeg_base + [
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(temp_segment_path)
            ]

            ffmpeg_result = subprocess.run(
                ffmpeg_cmd,
                capture_output=True,
                text=True,
                timeout=ffmpeg_timeout
            )

            if ffmpeg_result.returncode != 0:
                logger.error(f"❌ FFmpeg pre-extraction failed (exit {ffmpeg_result.returncode})")
                logger.error(f"FFmpeg stderr: {ffmpeg_result.stderr[-500:]}")
                raise RuntimeError(f"FFmpeg segment extraction failed: {ffmpeg_result.stderr[-200:]}")

            segment_size = temp_segment_path.stat().st_size / (1024*1024)
            logger.info(f"✅ FFmpeg extracted {segment_size:.1f}MB segment → MoviePy")

            # MoviePy now loads only the small pre-extracted segment
            video_for_moviepy = temp_segment_path
            moviepy_start = 0.0
            moviepy_end = duration

            # 4. Load & Track Master Resources (small segment only)
            main_video = guard.track(VideoFileClip(str(video_for_moviepy)))

            # Multi-Angle Intelligence
            if camera_plan and secondary_video_path and Path(secondary_video_path).exists():
                logger.info("🎬 Multi-Angle Switcher Active")
                secondary_video = guard.track(VideoFileClip(str(secondary_video_path)))
                cut_clips = []

                for cut in camera_plan:
                    cut_start = max(moviepy_start, cut["start"] - start_time)
                    cut_end = min(moviepy_end, cut["end"] - start_time)
                    if cut_start >= cut_end:
                        continue

                    if cut["angle"] == 0:
                        angle_clip = main_video.subclipped(cut_start, cut_end)
                    else:
                        sec_start = cut_start - sync_offset
                        sec_end = cut_end - sync_offset
                        sec_start = max(0, min(sec_start, secondary_video.duration))
                        sec_end = max(0, min(sec_end, secondary_video.duration))
                        if sec_start >= sec_end:
                            angle_clip = main_video.subclipped(cut_start, cut_end)
                        else:
                            angle_clip = secondary_video.subclipped(sec_start, sec_end)
                    cut_clips.append(angle_clip)

                if cut_clips:
                    from moviepy import concatenate_videoclips
                    clip = guard.track(concatenate_videoclips(cut_clips))
                else:
                    clip = guard.track(main_video.subclipped(moviepy_start, min(moviepy_end, main_video.duration)))
            else:
                clip = guard.track(main_video.subclipped(moviepy_start, min(moviepy_end, main_video.duration)))

            # 5. Process Geometry
            # Since FFmpeg already scaled to 1080x1920, geometry is already correct for vertical
            if keep_original:
                processed_clip = clip
                target_width, target_height = round_to_even(clip.w), round_to_even(clip.h)
                if (target_width, target_height) != (clip.w, clip.h):
                    processed_clip = guard.track(clip.resized((target_width, target_height)))
            else:
                # FFmpeg pre-extraction already scaled to 1080x1920
                target_width, target_height = 1080, 1920
                processed_clip = clip

            # 5.5 Zoom Punch-In Effect
            try:
                _clip_dur = processed_clip.duration or duration
                _punch_dur = min(0.4, _clip_dur * 0.08)
                if _punch_dur > 0.1 and _clip_dur > 1.0:
                    from moviepy import VideoClip as _VC
                    import cv2

                    _base_clip = processed_clip
                    _pw, _ph = target_width, target_height

                    def _zoom_frame(t):
                        frame = _base_clip.get_frame(t)
                        if t < _punch_dur:
                            progress = t / _punch_dur
                            ease = 1.0 - (1.0 - progress) ** 2
                            scale = 1.05 - 0.05 * ease
                        else:
                            scale = 1.0
                        if scale <= 1.0 or frame.shape[0] < 2 or frame.shape[1] < 2:
                            return frame
                        h, w = frame.shape[:2]
                        new_h, new_w = int(h / scale), int(w / scale)
                        y0, x0 = (h - new_h) // 2, (w - new_w) // 2
                        cropped = frame[y0 : y0 + new_h, x0 : x0 + new_w]
                        return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)

                    _zoomed = _VC(frame_function=_zoom_frame, duration=_clip_dur)
                    _zoomed.fps = processed_clip.fps or 30
                    if processed_clip.audio is not None:
                        _zoomed = _zoomed.with_audio(processed_clip.audio)
                    processed_clip = guard.track(_zoomed)
            except Exception as _zoom_e:
                logger.debug(f"Zoom punch-in skipped: {_zoom_e}")

            # 6. Composite Stack
            final_stack = [processed_clip]

            from ..video_utils import get_template, get_scaled_font_size, find_font_path
            _tmpl = get_template(caption_template)
            _fs = get_scaled_font_size(_tmpl.get("font_size", font_size), target_width)
            _font_path = find_font_path(font_family)

            # Subtitles: handled via FFmpeg ASS burn in video_service.py (after face crop).
            # MoviePy subtitle compositor disabled — it received 0 words because
            # load_cached_transcript_data is keyed on the original video, not the
            # pre-extracted segment, so no words were ever found here.
            if add_subtitles:
                logger.debug("Subtitles deferred to FFmpeg ASS burn (post crop stage)")

            # Split Screen
            if split_screen:
                processed_clip = guard.track(
                    processed_clip.resized(width=target_width, height=target_height // 2)
                    .with_position(("center", "top"))
                )
                final_stack[0] = processed_clip

            # Hook Title
            if hook_title:
                _hook_resolved = _font_path
                if not _hook_resolved:
                    try:
                        from ..font_registry import find_font_path as _fr_ffp, FONTS_DIR, SUPPORTED_FONT_EXTENSIONS
                        _hook_resolved = (
                            _fr_ffp(font_family)
                            or _fr_ffp("TikTokSans-Regular")
                            or _fr_ffp("THEBOLDFONT")
                        )
                        if not _hook_resolved:
                            for _ext in SUPPORTED_FONT_EXTENSIONS:
                                _cands = sorted(FONTS_DIR.glob(f"*{_ext}"))
                                if _cands:
                                    _hook_resolved = _cands[0]
                                    break
                    except Exception:
                        pass

                hook_font = str(_hook_resolved) if _hook_resolved else None
                if hook_font:
                    hook_kwargs = dict(
                        text=hook_title.upper(),
                        font=hook_font,
                        font_size=_tmpl.get("hook_font_size", 56),
                        color=_tmpl.get("hook_color", "#FFFFFF"),
                        stroke_color=_tmpl.get("hook_stroke_color", "#000000"),
                        stroke_width=_tmpl.get("hook_stroke_width", 2),
                        duration=min(3.0, duration),
                    )
                    _raw_hook = TextClip(**hook_kwargs).with_position(("center", 0.15), relative=True)
                    if CROSSFADE_AVAILABLE:
                        try:
                            _raw_hook = _raw_hook.with_effects([CrossFadeIn(0.3), CrossFadeOut(0.3)])
                        except Exception as _fx_e:
                            logger.debug(f"Hook fade skipped: {_fx_e}")
                    final_stack.append(guard.track(_raw_hook))

            # 7. Final Composition
            if len(final_stack) > 1:
                final_clip = guard.track(CompositeVideoClip(final_stack))
            else:
                final_clip = processed_clip

            # Smooth Fade-in / Fade-out
            if CROSSFADE_AVAILABLE:
                try:
                    _fade_dur = min(0.3, final_clip.duration * 0.08)
                    if _fade_dur > 0.05 and final_clip.duration > 1.0:
                        final_clip = guard.track(
                            final_clip.with_effects([CrossFadeIn(_fade_dur), CrossFadeOut(_fade_dur)])
                        )
                except Exception as _fade_e:
                    logger.debug(f"Fade effects skipped: {_fade_e}")

            # 8. Write final clip
            from ..video_utils import VideoProcessor
            processor = VideoProcessor(font_family, font_size, font_color)

            if gpu_encoding_settings:
                encoding_settings = gpu_encoding_settings
                logger.info(f"✨ Using GPU encoding: {encoding_settings.get('codec')}")
            else:
                encoding_settings = processor.get_optimal_encoding_settings("high")
                logger.info("Using CPU encoding (libx264)")

            _fps_used = clip.fps or 30

            output_path.parent.mkdir(parents=True, exist_ok=True)

            final_clip.write_videofile(
                str(output_path),
                temp_audiofile=str(output_path.parent / f"temp-audio-{output_path.stem}.m4a"),
                remove_temp=True, logger=None, fps=_fps_used, **encoding_settings
            )

            logger.info(f"✅ Render Complete: {output_path}")
            return True

    except Exception as e:
        import traceback
        logger.error(f"❌ Render Failed [{output_path}]: {e}\n{traceback.format_exc()}")
        return False
    finally:
        # Guaranteed cleanup of FFmpeg temp segment
        if temp_segment_path and temp_segment_path.exists():
            try:
                temp_segment_path.unlink()
                logger.debug(f"🧹 Cleaned up temp segment: {temp_segment_path.name}")
            except Exception as cleanup_err:
                logger.warning(f"Failed to cleanup temp segment: {cleanup_err}")
