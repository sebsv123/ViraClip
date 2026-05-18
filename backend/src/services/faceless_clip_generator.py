"""
FacelessClipGenerator — Stub for future faceless video generation.

Feature flag: FACELESS_FEATURE_ENABLED (default: false)
Status: NOT IMPLEMENTED — reserved for future work.

When implemented, this generator will:
  - Accept a text prompt and configuration
  - Generate a complete "faceless" video using text-to-video + TTS narration
  - Return the path to the generated video file

Current behavior:
  - Returns None (graceful no-op)
  - Logs a warning when called with the flag enabled
  - Raises NotImplementedError if called directly
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FacelessGenerationResult:
    """Result of a faceless video generation request."""
    video_path: Optional[Path] = None
    success: bool = False
    error: Optional[str] = None


class FacelessClipGenerator:
    """
    Stub generator for faceless video content.

    NOTE: This is a placeholder. The actual integration is not yet implemented.
    When FACELESS_FEATURE_ENABLED=True, this stub returns None and logs
    a warning to the health report.
    """

    async def generate_from_prompt(
        self,
        prompt: str,
        output_path: Path,
        duration_s: float = 30.0,
        voice: str = "default",
        **kwargs: Any,
    ) -> Optional[FacelessGenerationResult]:
        """
        Generate a faceless video from a text prompt.

        Current implementation: stub — returns None with error message.

        Args:
            prompt: Text description of the video to generate.
            output_path: Where to write the generated video.
            duration_s: Target duration in seconds.
            voice: TTS voice to use.
            **kwargs: Additional parameters (reserved for future use).

        Returns:
            FacelessGenerationResult with success=False and error message.
        """
        logger.warning(
            "[Faceless] NOT IMPLEMENTED — FACELESS_FEATURE_ENABLED=True but generator is a stub. "
            "Returning None. Implement faceless_clip_generator.py to enable this feature."
        )
        return FacelessGenerationResult(
            success=False,
            error="Faceless video generation is not yet implemented. "
                  "This feature flag is reserved for future work.",
        )


# Singleton
_generator: Optional[FacelessClipGenerator] = None


def get_faceless_clip_generator() -> FacelessClipGenerator:
    """Get or create the singleton FacelessClipGenerator."""
    global _generator
    if _generator is None:
        _generator = FacelessClipGenerator()
    return _generator
