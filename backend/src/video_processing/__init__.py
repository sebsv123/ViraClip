"""
Video Processing Module - Refactored from video_utils.py

Organizes video processing functionality into logical modules:
- transcription: Video transcription and caching
- face_detection: Face/speaker detection and tracking
- subtitles: Subtitle generation (bounce, karaoke, static, etc.)
- audio: Background music mixing
- clip_creation: Main clip rendering orchestration
- hook_analysis: Viral hook pattern detection
- viral_effects: Visual effects for viral content
- niche_analysis: Content niche and trends analysis
- virality_tuner: Virality scoring fine-tuning
- utils: Shared utilities
"""

# Re-export main functions for backward compatibility
from .transcription import (
    get_video_transcript,
    cache_transcript_data,
    load_cached_transcript_data,
    snap_to_word_boundary,
    format_transcript_for_analysis,
)

from .face_detection import (
    detect_faces_in_clip,
    detect_optimal_crop_region,
    detect_face_trajectory,
    detect_active_speaker_trajectory,
    filter_face_outliers,
)

from .subtitles import (
    create_bounce_subtitles,
    create_static_subtitles,
    create_karaoke_subtitles,
    create_pop_subtitles,
    create_fade_subtitles,
    create_assemblyai_subtitles,
    get_words_in_range,
)

from .audio import (
    mix_background_music,
    get_background_music_for_niche,
    fetch_pixabay_music,
    AUDIO_NORMALIZE_FILTER,
    build_music_mix_filter,
    _validate_audio_stream,
)

from .clip_creation import (
    create_optimized_clip,
    create_clips_from_segments,
    create_clips_with_transitions,
)

# NEW: Viral analysis modules
from .hook_analysis import (
    analyze_segment_virality,
    compare_hook_strength,
    detect_hooks_in_text,
    score_segment_hooks,
    detect_retention_mechanisms,
    HookPattern,
)

from .niche_analysis import (
    analyze_content_niche,
    optimize_for_platform,
    get_niche_specific_tips,
    NicheAnalysis,
)

from .virality_tuner import (
    ViralityScoringTuner,
    get_tuner,
)

from .viral_effects import (
    ViralVisualEffects,
    ViralTransitionEffects,
    EffectPresets,
    analyze_content_type_for_effects,
    get_effects_for_content,
)

# B-Roll (consolidated from broll.py)
from .broll import (
    BRollVideo,
    BRollSuggestion,
    search_broll_videos,
    get_best_broll_video,
)

# NEW: Professional B-Roll overlay system (Phase 2)
from .broll_overlay import (
    BRollDecision,
    BRollOverlayEngine,
    BRollDecisionEngine,
    insert_broll_into_clip,
)

# Transition functions (migrated from video_utils)
from .optical_flow_transitions import (
    get_available_transitions,
    apply_transition_effect,
)

# Import generate_clip_thumbnail from correct location
try:
    from ..services.ai_thumbnail_service import generate_clip_thumbnail
except ImportError:
    # Fallback if service not available
    def generate_clip_thumbnail(*args, **kwargs):
        return False

from .utils import (
    format_ms_to_timestamp,
    parse_timestamp_to_seconds,
    round_to_even,
    get_scaled_font_size,
    get_subtitle_max_width,
    get_safe_vertical_position,
    inject_emoji,
    adaptive_word_groups,
)

__all__ = [
    # Transcription
    "get_video_transcript",
    "cache_transcript_data",
    "load_cached_transcript_data",
    "get_redis_transcript_cache",
    "set_redis_transcript_cache",
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
    "_validate_audio_stream",
    # Clip creation
    "create_optimized_clip",
    "create_clips_from_segments",
    "create_clips_with_transitions",
    # NEW: Viral analysis
    "analyze_segment_virality",
    "compare_hook_strength",
    "detect_hooks_in_text",
    "score_segment_hooks",
    "detect_retention_mechanisms",
    "HookPattern",
    # NEW: Niche analysis
    "analyze_content_niche",
    "optimize_for_platform",
    "get_niche_specific_tips",
    "NicheAnalysis",
    # NEW: Virality tuner
    "ViralityScoringTuner",
    "get_tuner",
    # NEW: Viral effects
    "ViralVisualEffects",
    "ViralTransitionEffects",
    "EffectPresets",
    "analyze_content_type_for_effects",
    "get_effects_for_content",
    # Transitions (migrated from video_utils)
    "get_available_transitions",
    "apply_transition_effect",
    # B-Roll (consolidated from broll.py)
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
    "adaptive_word_groups",
]
