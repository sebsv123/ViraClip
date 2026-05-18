"""
ClipsAI Adapter — Stub for future ClipsAI integration.

Feature flag: CLIPSAI_ENABLED (default: false)
Status: NOT IMPLEMENTED — reserved for future work.

When implemented, this adapter will:
  - Accept a video path and transcript
  - Call the external ClipsAI API for automated clip generation
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
    """A clip segment proposed by ClipsAI."""
    start_time: float
    end_time: float
    score: float = 0.0
    title: str = ""
    reason: str = ""


class ClipsAIAdapter:
    """
    Stub adapter for ClipsAI integration.

    NOTE: This is a placeholder. The actual integration is not yet implemented.
    When CLIPSAI_ENABLED=True, this stub returns empty results and logs
    a warning to the health report.
    """

    async def generate_clips(
        self,
        video_path: Path,
        transcript: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[ClipCandidate]:
        """
        Generate clips using ClipsAI.

        Current implementation: stub — returns empty list.

        Args:
            video_path: Path to the source video.
            transcript: Optional transcript dict with segments.
            **kwargs: Additional parameters (reserved for future use).

        Returns:
            Empty list (not implemented yet).
        """
        logger.warning(
            "[ClipsAI] NOT IMPLEMENTED — CLIPSAI_ENABLED=True but adapter is a stub. "
            "Returning empty list. Implement clipsai_adapter.py to enable this feature."
        )
        return []


# Singleton
_adapter: Optional[ClipsAIAdapter] = None


def get_clipsai_adapter() -> ClipsAIAdapter:
    """Get or create the singleton ClipsAIAdapter."""
    global _adapter
    if _adapter is None:
        _adapter = ClipsAIAdapter()
    return _adapter
