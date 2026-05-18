"""
AiClipsMaker Adapter — Stub for future ai-clips-maker integration.

Feature flag: AI_CLIPS_MAKER_ENABLED (default: false)
Status: NOT IMPLEMENTED — reserved for future work.

When implemented, this adapter will:
  - Accept a video path and transcript
  - Call the external ai-clips-maker API for AI-driven clip segmentation
  - Return a list of ClipCandidate with start/end times and scores

Current behavior:
  - Returns empty list (graceful no-op)
  - Logs a warning when called with the flag enabled
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ClipCandidate:
    """A clip segment proposed by ai-clips-maker."""
    start_time: float
    end_time: float
    score: float = 0.0
    title: str = ""
    reason: str = ""


class AiClipsMakerAdapter:
    """
    Stub adapter for ai-clips-maker integration.

    NOTE: This is a placeholder. The actual integration is not yet implemented.
    When AI_CLIPS_MAKER_ENABLED=True, this stub returns empty results and logs
    a warning to the health report.
    """

    async def analyze(
        self,
        video_path: Path,
        transcript: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[ClipCandidate]:
        """
        Analyze a video using ai-clips-maker and return clip candidates.

        Current implementation: stub — returns empty list.

        Args:
            video_path: Path to the source video.
            transcript: Optional transcript dict with segments.
            **kwargs: Additional parameters (reserved for future use).

        Returns:
            Empty list (not implemented yet).
        """
        logger.warning(
            "[AiClipsMaker] NOT IMPLEMENTED — AI_CLIPS_MAKER_ENABLED=True but adapter is a stub. "
            "Returning empty list. Implement ai_clips_maker_adapter.py to enable this feature."
        )
        return []


# Singleton
_adapter: Optional[AiClipsMakerAdapter] = None


def get_ai_clips_maker_adapter() -> AiClipsMakerAdapter:
    """Get or create the singleton AiClipsMakerAdapter."""
    global _adapter
    if _adapter is None:
        _adapter = AiClipsMakerAdapter()
    return _adapter
