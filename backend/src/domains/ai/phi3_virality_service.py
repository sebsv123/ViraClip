"""Phi3ViralityService — compatibility stub.

The original Phi-3-mini ONNX implementation was removed during the ai.py
refactor (commit 6e28576).  _clip_renderer.py still imports this module at
the top level, which crashes uvicorn before the app can start.

This stub satisfies the import contract so the backend starts correctly.
When PHI3_ENABLED=true (the default), score_segment() raises an exception
which _clip_renderer.py catches and delegates to the LLMRouter fallback
that is already implemented inline.  Behaviour is therefore identical to
having Phi-3 unavailable — the LLM-based scorer takes over transparently.

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
    """Stub — no local model loaded.

    Raises RuntimeError on score_segment() so _clip_renderer.py falls back
    to LLMRouter automatically (the except block on line ~110 of
    _clip_renderer.py handles this case).
    """

    def __init__(self) -> None:
        logger.info(
            "[Phi3ViralityService] Running as stub — "
            "LLMRouter fallback will be used for virality scoring."
        )

    async def score_segment(
        self,
        segment_text: str,
        duration: float,
        audio_features: Optional[dict] = None,
    ) -> ViralityScore:
        raise RuntimeError(
            "Phi3ViralityService is a stub — no local model available. "
            "LLMRouter fallback should handle scoring."
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
