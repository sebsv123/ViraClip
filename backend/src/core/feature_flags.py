"""
Feature Flag Manager — singleton for runtime feature toggles.

FEATURE_FLAGS is a module-level singleton accessible from any module via:
    from src.core.feature_flags import FEATURE_FLAGS

Flags are set by DependencyHealthChecker at worker startup and can be
re-evaluated periodically by the SelfHealer recovery loop.
"""

import json
import logging
from typing import Any, Dict, Optional

from src import gpu_utils

logger = logging.getLogger(__name__)

# Default state: all features enabled
_DEFAULT_FLAGS: Dict[str, Any] = {
    "audio_spectral_analysis": True,
    "narrative_cut_detection": True,
    "face_tracking_mediapipe": True,
    "gpu_encode": True,
    "beat_sync_librosa": True,
    "ffmpeg": True,
    "llm_groq": True,
    "llm_deepseek": True,
}

# Fallback descriptions for each feature
FALLBACK_MAP: Dict[str, str] = {
    "audio_spectral_analysis": "skipped",
    "narrative_cut_detection": "skipped",
    "face_tracking_mediapipe": "haar_cascade",
    "gpu_encode": gpu_utils.nvenc_available(),
    "beat_sync_librosa": "ffmpeg_tempo_estimate",
    "ffmpeg": "—",
    "llm_groq": "deepseek",
    "llm_deepseek": "groq",
}


class FeatureFlagManager:
    """Thread-safe singleton for runtime feature flags."""

    _instance: Optional["FeatureFlagManager"] = None

    def __new__(cls) -> "FeatureFlagManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._flags = dict(_DEFAULT_FLAGS)
        return cls._instance

    def get(self, key: str, default: Any = True) -> Any:
        return self._flags.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._flags[key] = value

    def get_all(self) -> Dict[str, Any]:
        return dict(self._flags)

    def set_all(self, flags: Dict[str, Any]) -> None:
        self._flags.update(flags)

    def to_json(self) -> str:
        return json.dumps(self._flags)

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (useful for testing)."""
        cls._instance = None
        import sys
        mod = sys.modules.get("src.core.feature_flags")
        if mod:
            mod.FEATURE_FLAGS = cls()


# Module-level convenience singleton
FEATURE_FLAGS = FeatureFlagManager()
