"""
Feature Flag Manager — centralized runtime feature toggles for ViraClip.

Two-layer design:
  1. STATIC FLAGS — read from Config (env vars) at startup, never change at runtime.
  2. RUNTIME FLAGS — mutable singleton that can be overridden via dashboard/API
     without redeploy (future: persisted in DB).

Usage:
    from src.core.feature_flags import get_flag, set_flag, is_enabled

    if is_enabled("AI_BROLL_ENABLED"):
        use_ai_broll_recommender()
    else:
        use_tfidf_fallback()

All new integration flags are OFF by default (opt-in via .env).
See backend/.env.example for recommended values per environment.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from src.config import get_config

logger = logging.getLogger(__name__)

# ── Flag metadata for documentation / future dashboard ──────────────────────

FLAG_META: Dict[str, Dict[str, Any]] = {
    # ── AI B-Roll Recommender ──────────────────────────────────────────────
    "AI_BROLL_ENABLED": {
        "description": "LLM-powered B-roll keyword extraction from transcript segments",
        "fallback": "Uses simple TF-IDF keyword extraction (no LLM call)",
        "default": False,
        "env_var": "AI_BROLL_ENABLED",
        "since": "2026-05",
    },
    # ── Short Video Maker Pexels ───────────────────────────────────────────
    "SHORT_VIDEO_MAKER_PEXELS_ENABLED": {
        "description": "Port of short-video-maker's Pexels client for B-roll fetching",
        "fallback": "Uses the existing PexelsService (pexels_client.py) directly",
        "default": False,
        "env_var": "SHORT_VIDEO_MAKER_PEXELS_ENABLED",
        "since": "2026-05",
    },
    # ── Background Music ───────────────────────────────────────────────────
    "BACKGROUND_MUSIC_ENABLED": {
        "description": "Mood-based background music selection from local library",
        "fallback": "No background music (pipeline continues silently)",
        "default": False,
        "env_var": "BACKGROUND_MUSIC_ENABLED",
        "since": "2026-05",
    },
    # ── AI Clips Maker ─────────────────────────────────────────────────────
    "AI_CLIPS_MAKER_ENABLED": {
        "description": "External AI-driven clip segmentation (ai-clips-maker integration)",
        "fallback": "Uses internal viral_gate segmentation only. No external scene boundary adjustment.",
        "default": False,
        "env_var": "AI_CLIPS_MAKER_ENABLED",
        "since": "2026-05",
    },
    # ── ClipsAI ────────────────────────────────────────────────────────────
    "CLIPSAI_ENABLED": {
        "description": "Third-party ClipsAI service for automated clip generation",
        "fallback": "Skips ClipsAI, uses native pipeline only",
        "default": False,
        "env_var": "CLIPSAI_ENABLED",
        "since": "2026-05",
    },
    # ── Shorts Highlight Engine ────────────────────────────────────────────
    "SHORTS_ENGINE_ENABLED": {
        "description": "LLM-based highlight detection + OpenCV face-aware vertical crop",
        "fallback": "Uses existing segment boundaries (no highlight re-ranking)",
        "default": False,
        "env_var": "SHORTS_ENGINE_ENABLED",
        "since": "2026-05",
    },
    # ── Editlist Backend ───────────────────────────────────────────────────
    "EDITLIST_ENABLED": {
        "description": "Declarative editlist pipeline (master switch)",
        "fallback": "Builds FFmpeg commands directly (legacy approach)",
        "default": True,
        "env_var": "EDITLIST_ENABLED",
        "since": "2026-04",
    },
    "EDITLIST_ENABLE_CUTS": {
        "description": "Editlist phase 1: cuts/concat only",
        "fallback": "Legacy FFmpeg cut commands",
        "default": True,
        "env_var": "EDITLIST_ENABLE_CUTS",
        "since": "2026-04",
    },
    "EDITLIST_ENABLE_OVERLAYS": {
        "description": "Editlist phase 2: + overlays",
        "fallback": "Legacy overlay rendering",
        "default": False,
        "env_var": "EDITLIST_ENABLE_OVERLAYS",
        "since": "2026-04",
    },
    "EDITLIST_ENABLE_TRANSITIONS": {
        "description": "Editlist phase 3: + transitions",
        "fallback": "No transitions between clips",
        "default": False,
        "env_var": "EDITLIST_ENABLE_TRANSITIONS",
        "since": "2026-04",
    },
    # ── Face Auto-Crop ────────────────────────────────────────────────────
    "FACE_AUTOCROP_ENABLED": {
        "description": "Intelligent face-tracking auto-crop to 9:16 using OpenCV Haar cascades. Takes priority over ImpactZoomService and zoom_punch.",
        "fallback": "Fixed center crop (no face tracking). ImpactZoom/zoom_punch behave as before.",
        "default": True,
        "env_var": "FACE_AUTOCROP_ENABLED",
        "since": "2026-05",
    },
    # ── Faceless Feature ───────────────────────────────────────────────────
    "FACELESS_FEATURE_ENABLED": {
        "description": "Automated faceless video generation (text-to-video + TTS narration)",
        "fallback": "Requires source video input (no auto-generation)",
        "default": False,
        "env_var": "FACELESS_FEATURE_ENABLED",
        "since": "2026-05",
    },
    # ── Caption Backend ────────────────────────────────────────────────────
    "CAPTION_BACKEND": {
        "description": "Subtitle rendering backend: 'legacy' (drawtext) or 'auto_subtitle' (AssemblyAI)",
        "fallback": "legacy — original drawtext-based subtitle rendering",
        "default": "legacy",
        "env_var": "CAPTION_BACKEND",
        "since": "2026-05",
    },
    # ── Export Preset ──────────────────────────────────────────────────────
    "EXPORT_PRESET": {
        "description": "Export preset template: tiktok_basic, fast_vertical, youtube_shorts, instagram_reels",
        "fallback": "tiktok_basic — 9:16, 30fps, AAC 128k",
        "default": "tiktok_basic",
        "env_var": "EXPORT_PRESET",
        "since": "2026-05",
    },
    # ── Optimization Loop ──────────────────────────────────────────────────
    "OPTIMIZATION_LOOP_ENABLED": {
        "description": "Clip performance analysis + creative hints feedback loop",
        "fallback": "No performance-driven optimization",
        "default": False,
        "env_var": "OPTIMIZATION_LOOP_ENABLED",
        "since": "2026-05",
    },
}


class FeatureFlagManager:
    """
    Thread-safe singleton for runtime feature flags.

    Static flags are read from Config (env vars) at construction time.
    Runtime overrides can be applied via set() / set_all() for future
    dashboard-driven toggles without redeploy.
    """

    _instance: Optional["FeatureFlagManager"] = None

    def __new__(cls) -> "FeatureFlagManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._runtime_overrides: Dict[str, Any] = {}
        return cls._instance

    # ── Public API ─────────────────────────────────────────────────────────

    def is_enabled(self, key: str, default: bool = False) -> bool:
        """
        Check if a feature flag is enabled.

        Priority: runtime override > Config env var > default.
        """
        # 1. Runtime override (future dashboard)
        if key in self._runtime_overrides:
            return bool(self._runtime_overrides[key])

        # 2. Config env var
        cfg = get_config()
        config_key = key.lower()
        config_val = getattr(cfg, config_key, None)
        if config_val is not None:
            return bool(config_val)

        # 3. Fallback to metadata default
        meta = FLAG_META.get(key, {})
        return bool(meta.get("default", default))

    def get(self, key: str, default: Any = None) -> Any:
        """Get a flag value (supports non-bool flags like CAPTION_BACKEND)."""
        # 1. Runtime override
        if key in self._runtime_overrides:
            return self._runtime_overrides[key]

        # 2. Config env var
        cfg = get_config()
        config_key = key.lower()
        config_val = getattr(cfg, config_key, None)
        if config_val is not None:
            return config_val

        # 3. Metadata default
        meta = FLAG_META.get(key, {})
        return meta.get("default", default)

    def set(self, key: str, value: Any) -> None:
        """Set a runtime override for a flag (not persisted across restarts)."""
        self._runtime_overrides[key] = value
        logger.info("Feature flag runtime override: %s = %s", key, value)

    def set_all(self, flags: Dict[str, Any]) -> None:
        """Apply multiple runtime overrides at once."""
        self._runtime_overrides.update(flags)
        logger.info("Feature flags bulk update: %d flags", len(flags))

    def get_all(self) -> Dict[str, Any]:
        """Return all flag states (static + runtime overrides)."""
        result: Dict[str, Any] = {}
        for key in FLAG_META:
            result[key] = self.get(key)
        # Also include any runtime-only flags not in metadata
        for key in self._runtime_overrides:
            if key not in result:
                result[key] = self._runtime_overrides[key]
        return result

    def get_meta(self, key: str) -> Dict[str, Any]:
        """Return metadata for a flag (description, fallback, etc.)."""
        return FLAG_META.get(key, {})

    def get_all_meta(self) -> Dict[str, Dict[str, Any]]:
        """Return metadata for all registered flags."""
        return dict(FLAG_META)

    def to_json(self) -> str:
        """Serialize all flag states to JSON."""
        return json.dumps(self.get_all(), indent=2)

    def reset_runtime_overrides(self) -> None:
        """Clear all runtime overrides (revert to Config defaults)."""
        self._runtime_overrides.clear()
        logger.info("Feature flags: runtime overrides cleared")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (useful for testing)."""
        cls._instance = None
        import sys
        mod = sys.modules.get("src.core.feature_flags")
        if mod:
            mod.FEATURE_FLAGS = cls()


# ── Module-level convenience functions ──────────────────────────────────────

FEATURE_FLAGS = FeatureFlagManager()


def is_enabled(key: str, default: bool = False) -> bool:
    """Convenience: check if a feature flag is enabled."""
    return FEATURE_FLAGS.is_enabled(key, default=default)


def get_flag(key: str, default: Any = None) -> Any:
    """Convenience: get a flag value."""
    return FEATURE_FLAGS.get(key, default=default)


def set_flag(key: str, value: Any) -> None:
    """Convenience: set a runtime override."""
    FEATURE_FLAGS.set(key, value)
