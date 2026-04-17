"""
Backward compatibility wrapper for video_utils.py

This file maintains backward compatibility while the codebase transitions
to the new modular structure in video_processing/.

Usage:
    # Old imports still work
    from src.video_utils import create_optimized_clip
    
    # New imports (preferred)
    from src.video_processing import create_optimized_clip

All imports are re-exported from video_processing modules.
"""

# Re-export everything from video_processing for backward compatibility
from .video_processing import *  # noqa: F401, F403

# Explicitly re-export commonly used items for clarity
from .video_processing import (
    # Core clip creation
    create_optimized_clip,
    VideoProcessor,
    
    # Transcription
    get_video_transcript,
    cache_transcript_data,
    load_cached_transcript_data,
    snap_to_word_boundary,
    format_transcript_for_analysis,
    
    # Face detection
    detect_faces_in_clip,
    detect_optimal_crop_region,
    detect_face_trajectory,
    detect_active_speaker_trajectory,
    filter_face_outliers,
    
    # Subtitles
    create_bounce_subtitles,
    create_static_subtitles,
    create_karaoke_subtitles,
    create_pop_subtitles,
    create_fade_subtitles,
    create_assemblyai_subtitles,
    get_words_in_range,
    adaptive_word_groups,
    
    # Audio
    mix_background_music,
    get_background_music_for_niche,
    fetch_pixabay_music,
    
    # Utils
    format_ms_to_timestamp,
    parse_timestamp_to_seconds,
    round_to_even,
    get_scaled_font_size,
    get_subtitle_max_width,
    get_safe_vertical_position,
    inject_emoji,
)

__all__ = [
    "create_optimized_clip",
    "VideoProcessor",
    "get_video_transcript",
    "cache_transcript_data",
    "load_cached_transcript_data",
    "snap_to_word_boundary",
    "format_transcript_for_analysis",
    "detect_faces_in_clip",
    "detect_optimal_crop_region",
    "detect_face_trajectory",
    "detect_active_speaker_trajectory",
    "filter_face_outliers",
    "create_bounce_subtitles",
    "create_static_subtitles",
    "create_karaoke_subtitles",
    "create_pop_subtitles",
    "create_fade_subtitles",
    "create_assemblyai_subtitles",
    "get_words_in_range",
    "adaptive_word_groups",
    "mix_background_music",
    "get_background_music_for_niche",
    "fetch_pixabay_music",
    "format_ms_to_timestamp",
    "parse_timestamp_to_seconds",
    "round_to_even",
    "get_scaled_font_size",
    "get_subtitle_max_width",
    "get_safe_vertical_position",
    "inject_emoji",
]
