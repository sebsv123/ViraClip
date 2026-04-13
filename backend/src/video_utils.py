"""
video_utils.py — Unified compatibility wrapper
================================================

This module maintains backward compatibility while the codebase uses
the new modular structure in video_processing/.

All functionality has been migrated to specific submodules:
- video_processing.transcription (get_video_transcript)
- video_processing.subtitles (create_*_subtitles)
- video_processing.face_detection (detect_faces_in_clip, detect_face_trajectory)
- video_processing.audio (mix_background_music, get_background_music_for_niche)
- video_processing.clip_creation (create_optimized_clip, VideoProcessor)
- video_processing.optical_flow_transitions (transitions)
- video_processing.utils (shared utilities)

Migration complete — Phase 0A (April 2026)
"""

# Re-export everything from video_processing for backward compatibility
from .video_processing import *  # noqa: F401, F403

# Explicitly re-export commonly used items for clarity
from .video_processing import (
    # Core clip creation
    create_optimized_clip,
    create_clips_from_segments,
    create_clips_with_transitions,
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
    AUDIO_NORMALIZE_FILTER,
    build_music_mix_filter,
    
    # Transitions (migrated from video_utils)
    get_available_transitions,
    apply_transition_effect,
    
    # B-Roll (consolidated from broll.py)
    BRollVideo,
    BRollSuggestion,
    search_broll_videos,
    get_best_broll_video,
    # NEW: Professional B-Roll overlay system (Phase 2)
    BRollDecision,
    BRollOverlayEngine,
    BRollDecisionEngine,
    insert_broll_into_clip,
    
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
    # Core clip creation
    "create_optimized_clip",
    "create_clips_from_segments",
    "create_clips_with_transitions",
    "VideoProcessor",
    
    # Transcription
    "get_video_transcript",
    "cache_transcript_data",
    "load_cached_transcript_data",
    "snap_to_word_boundary",
    "format_transcript_for_analysis",
    
    # Face detection
    "detect_faces_in_clip",
    "detect_optimal_crop_region",
    "detect_face_trajectory",
    "detect_active_speaker_trajectory",
    "filter_face_outliers",
    
    # Subtitles
    "create_bounce_subtitles",
    "create_static_subtitles",
    "create_karaoke_subtitles",
    "create_pop_subtitles",
    "create_fade_subtitles",
    "create_assemblyai_subtitles",
    "get_words_in_range",
    "adaptive_word_groups",
    
    # Audio
    "mix_background_music",
    "get_background_music_for_niche",
    "fetch_pixabay_music",
    "AUDIO_NORMALIZE_FILTER",
    "build_music_mix_filter",
    
    # Transitions
    "get_available_transitions",
    "apply_transition_effect",
    
    # B-Roll
    "BRollVideo",
    "BRollSuggestion",
    "search_broll_videos",
    "get_best_broll_video",
    # NEW: Professional B-Roll overlay system (Phase 2)
    "BRollDecision",
    "BRollOverlayEngine",
    "BRollDecisionEngine",
    "insert_broll_into_clip",
    
    # Utils
    "format_ms_to_timestamp",
    "parse_timestamp_to_seconds",
    "round_to_even",
    "get_scaled_font_size",
    "get_subtitle_max_width",
    "get_safe_vertical_position",
    "inject_emoji",
]
