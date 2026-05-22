"""Phi3ViralityService — compatibility stub (no-op).

The original Phi-3-mini ONNX implementation was removed during the ai.py
refactor (commit 6e28576).  _clip_renderer.py still imports this module at
the top level, which crashes uvicorn before the app can start.

This stub satisfies the import contract so the backend starts correctly.
Instead of raising RuntimeError (which triggers LLMRouter fallback with
~2s latency per clip), score_segment() returns a neutral default score
immediately.  The LLMRouter in _clip_renderer.py is still used as the
primary scorer — this stub is only called when PHI3_ENABLED=true, which
is not the default.

To re-enable a real local model, replace this file with a proper
implementation and keep the same public interface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ViralityScore:
    """Result object returned by Phi3ViralityService.score_segment()."""

    total_score: float = 50.0
    primary_hook_type: str = "Content"
    scroll_stop_probability: float = 0.5
    recommended_duration: str = "30-60s"
    confidence: float = 0.0
    breakdown: dict = field(default_factory=dict)


class Phi3ViralityService:
    """No-op stub — returns neutral default score without latency."""

    def __init__(self) -> None:
        logger.debug(
            "[Phi3ViralityService] No-op stub — returning default score. "
            "LLMRouter handles real scoring."
        )

    async def score_segment(
        self,
        segment_text: str,
        duration: float,
        audio_features: Optional[dict] = None,
    ) -> ViralityScore:
        # Return neutral default immediately — no latency, no exception
        return ViralityScore(
            total_score=50.0,
            primary_hook_type="Content",
            scroll_stop_probability=0.5,
            recommended_duration="30-60s",
            confidence=0.0,
        )

    def is_available(self) -> bool:
        return False


# ── Singleton ────────────────────────────────────────────────────────────────

_phi3_instance: Optional[Phi3ViralityService] = None


def get_phi3_service() -> Phi3ViralityService:
    """Return the singleton Phi3ViralityService instance."""
    global _phi3_instance
    if _phi3_instance is None:
        _phi3_instance = Phi3ViralityService()
    return _phi3_instance
