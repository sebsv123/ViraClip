"""Domain: ai."""

# Re-exports from legacy ai.py — pending full migration
# These symbols are imported by _transcript.py, _clips_batch.py,
# _clip_renderer.py, _clips_transitions.py, ai_metrics.py
from src.ai import get_most_relevant_parts_by_transcript  # noqa: F401

__all__ = [
    "get_most_relevant_parts_by_transcript",
]
