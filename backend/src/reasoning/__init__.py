"""
Structured Reasoning System for ViraClip

Transparent Chain-of-Thought reasoning for local LLMs.
Inspired by Claude's reasoning methodology.

5-Step Pipeline:
1. OBSERVE - Extract facts from input
2. ANALYZE - Identify patterns and relationships
3. HYPOTHESIZE - Generate theories about outcomes
4. SCORE - Quantify dimensions with evidence
5. RECOMMEND - Provide actionable suggestions
"""

from .engine import ReasoningEngine, ReasoningContext, ReasoningResult
from .steps import (
    ObserveStep,
    AnalyzeStep,
    HypothesizeStep,
    ScoreStep,
    RecommendStep,
)

__all__ = [
    "ReasoningEngine",
    "ReasoningContext",
    "ReasoningResult",
    "ObserveStep",
    "AnalyzeStep",
    "HypothesizeStep",
    "ScoreStep",
    "RecommendStep",
]
