"""Video service — thin facade over the video domain submodules.

Historically this file held a 2700-line `VideoService` class with dozens of
`@staticmethod` methods. Those methods have been split into focused
submodules (one responsibility each):

- :mod:`._helpers`     — pure utilities (ffmpeg path, time formatting, file ops)
- :mod:`._subtitles`   — ASS subtitle generation and 9:16 cropping
- :mod:`._transcript`  — YouTube download + Whisper transcription + AI analysis
- :mod:`._clips`       — heavy clip rendering pipeline
- :mod:`._pipeline`    — `process_video_complete` end-to-end orchestrator

`VideoService` is preserved as a namespace so existing call sites of the form
`VideoService.METHOD(...)` keep working unchanged. New code should prefer
calling the submodule functions directly.
"""

from __future__ import annotations

from . import _clips, _helpers, _pipeline, _subtitles, _transcript


class VideoService:
    """Static facade over the video domain submodules.

    Every attribute below is a thin re-export so legacy callers like
    ``VideoService.create_video_clips(...)`` keep working without changes.
    """

    # ── _helpers ──────────────────────────────────────────────────────────
    _get_ffmpeg_exe = staticmethod(_helpers.get_ffmpeg_exe)
    _get_file_duration = staticmethod(_helpers.get_file_duration)
    _seconds_to_ass_time = staticmethod(_helpers.seconds_to_ass_time)
    _adjust_words_for_cuts = staticmethod(_helpers.adjust_words_for_cuts)
    resolve_local_video_path = staticmethod(_helpers.resolve_local_video_path)

    # ── _subtitles ────────────────────────────────────────────────────────
    _burn_subtitles_word_level = staticmethod(_subtitles.burn_subtitles_word_level)
    _crop_to_vertical_9_16 = staticmethod(_subtitles.crop_to_vertical_9_16)

    # ── _transcript ───────────────────────────────────────────────────────
    download_video = staticmethod(_transcript.download_video)
    get_video_title = staticmethod(_transcript.get_video_title)
    generate_transcript = staticmethod(_transcript.generate_transcript)
    analyze_transcript = staticmethod(_transcript.analyze_transcript)

    # ── _clips ────────────────────────────────────────────────────────────
    create_video_clips_parallel = staticmethod(_clips.create_video_clips_parallel)
    create_video_clips = staticmethod(_clips.create_video_clips)
    create_single_clip = staticmethod(_clips.create_single_clip)
    apply_single_transition = staticmethod(_clips.apply_single_transition)

    # ── _pipeline ─────────────────────────────────────────────────────────
    determine_source_type = staticmethod(_pipeline.determine_source_type)
    process_video_complete = staticmethod(_pipeline.process_video_complete)


# Backwards-compatible re-exports (some callers use bare functions)
get_service_config = _helpers.get_service_config
UPLOAD_URL_PREFIX = _helpers.UPLOAD_URL_PREFIX
