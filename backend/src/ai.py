"""
DEPRECATED: Este modulo esta en proceso de migracion a domains/ai/
No anadir nuevas funciones aqui. Ver domains/ai/__init__.py
Simbolos activos: get_most_relevant_parts_by_transcript
Imports activos en: _transcript.py, _clips_batch.py,
                    _clip_renderer.py, _clips_transitions.py, ai_metrics.py

AI-related functions for transcript analysis with enhanced precision and virality scoring.
"""

from pathlib import Path
from typing import List, Dict, Any, Optional, Literal
import asyncio
import logging
import re

try:
    from pydantic_ai import Agent
    PYDANTIC_AI_AVAILABLE = True
except ImportError:
    PYDANTIC_AI_AVAILABLE = False
    Agent = None
from pydantic import BaseModel, Field, field_validator, model_validator, computed_field

from .config import Config

logger = logging.getLogger(__name__)
config = Config()


class CampaignStrategy(BaseModel):
    """V3 Phase 5: Holistic social media strategy for a collection of clips."""
    campaign_theme: str = Field(description="The overarching theme or narrative of the campaign")
    posting_schedule: List[str] = Field(description="Suggested relative timing for each clip (e.g. 'Day 1: Morning')")
    hashtags: List[str] = Field(description="Recommended trending and niche hashtags")
    target_audience: str = Field(description="Detailed profile of the viewer most likely to engage")
    cta_variation: str = Field(description="A specific call-to-action that ties the clips together")


class ViralityAnalysis(BaseModel):
    """Detailed virality breakdown for a segment."""

    hook_score: int = Field(
        description="How strong is the opening hook (0-25)", ge=0, le=25
    )
    engagement_score: Optional[int] = Field(
        default=None, description="How engaging/entertaining is the content (0-25)", ge=0, le=25
    )
    value_score: Optional[int] = Field(
        default=None, description="Educational/informational value (0-25)", ge=0, le=25
    )
    shareability_score: int = Field(
        description="Likelihood of being shared (0-25)", ge=0, le=25
    )
    total_score: Optional[int] = Field(
        default=None, description="Combined virality score (0-100)", ge=0, le=100
    )
    hook_type: Optional[
        Literal["question", "statement", "statistic", "story", "contrast", "none"]
    ] = Field(
        default="none",
        description="Type of hook: question, statement, statistic, story, contrast, or none",
    )
    virality_reasoning: str = Field(description="Explanation of the virality score")

    @model_validator(mode="after")
    def compute_total_score(self) -> "ViralityAnalysis":
        if self.total_score is None:
            self.total_score = min(100, (
                (self.hook_score or 0)
                + (self.engagement_score or 0)
                + (self.value_score or 0)
                + (self.shareability_score or 0)
            ))
        return self


class _TimestampStr(str):
    """String subclass that supports float arithmetic for duration calculations."""
    @staticmethod
    def _to_secs(v: "_TimestampStr") -> float:
        try:
            parts = str(v).strip().split(":")
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            return float(parts[0])
        except Exception:
            return 0.0

    def __sub__(self, other):
        return self._to_secs(self) - self._to_secs(other)  # type: ignore

    def __rsub__(self, other):
        return self._to_secs(other) - self._to_secs(self)  # type: ignore

    def __float__(self):
        return self._to_secs(self)

    def __ge__(self, other):
        if isinstance(other, str):
            return self._to_secs(self) >= self._to_secs(_TimestampStr(other))
        return self._to_secs(self) >= other

    def __le__(self, other):
        if isinstance(other, str):
            return self._to_secs(self) <= self._to_secs(_TimestampStr(other))
        return self._to_secs(self) <= other


class TranscriptSegment(BaseModel):
    """Represents a relevant segment of transcript with precise timing and virality analysis."""

    start_time: str = Field(description="Start timestamp in MM:SS format")
    end_time: str = Field(description="End timestamp in MM:SS format")
    text: str = Field(
        description=(
            "Transcript text taken only from the selected timestamp range. "
            "Keep it verbatim or near-verbatim, and do not paraphrase or merge non-contiguous lines."
        )
    )
    relevance_score: float = Field(
        description="Relevance score from 0.0 to 1.0", ge=0.0, le=1.0
    )
    reasoning: str = Field(
        description=(
            "Brief factual explanation of why this exact segment works as a clip. "
            "Base it only on the provided transcript content."
        )
    )
    virality: ViralityAnalysis = Field(description="Detailed virality score breakdown")
    theme: Optional[str] = Field(
        default="General",
        description="Thematic category of the clip (e.g. Motivational, Controversy, Edu-tainment)"
    )
    suggested_edits: Optional[str] = Field(
        default="Standard viral zoom and captions",
        description="Creative suggestions for editing this specific segment to maximize impact"
    )
    virality_score: float = Field(
        default=0.0,
        description="Composite virality score 0-10 (computed from virality breakdown)"
    )
    hook_title: str = Field(
        default="",
        description="Short viral-optimized hook title for the segment"
    )

    @field_validator("start_time", "end_time", mode="after")
    @classmethod
    def wrap_as_timestamp_str(cls, v: str) -> _TimestampStr:
        return _TimestampStr(v)

    @field_validator("relevance_score", mode="before")
    @classmethod
    def normalize_relevance_score(cls, v: float) -> float:
        """Normalize relevance_score from 0-100 scale to 0-1 before field constraint fires."""
        if isinstance(v, (int, float)) and v > 1.0:
            normalized = round(float(v) / 100.0, 4)
            logger.warning(
                f"[VALIDATOR] relevance_score {v} out of [0,1] range — normalizing to {normalized}"
            )
            return min(normalized, 1.0)
        return v

    @model_validator(mode="after")
    def enforce_business_rules(self) -> "TranscriptSegment":
        """
        Enforce all business invariants regardless of what the LLM returned.
        Schema-first: TranscriptSegment must be impossible to construct with invalid data.
        """
        def _ts_to_secs(ts: str) -> float:
            try:
                parts = ts.strip().split(":")
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                return float(parts[0])
            except Exception:
                return 0.0

        def _secs_to_ts(s: float) -> str:
            m = int(s) // 60
            sec = int(s) % 60
            return f"{m:02d}:{sec:02d}"

        start = _ts_to_secs(self.start_time)
        end = _ts_to_secs(self.end_time)

        # Regla 1: timestamps coherentes
        if end <= start:
            raise ValueError(
                f"end_time ({self.end_time}) must be > start_time ({self.start_time})"
            )

        # Populate derived fields
        if self.virality:
            self.virality_score = round(self.virality.total_score / 10.0, 2) if self.virality.total_score else 0.0
        if not self.hook_title and self.reasoning:
            self.hook_title = self.reasoning[:80]

        # Regla 2: duracion minima 30s (con limite de video_duration)
        MIN_DURATION = 30.0
        duration = end - start
        if duration < MIN_DURATION:
            logger.warning(
                f"[VALIDATOR] Segment too short ({duration:.1f}s): "
                f"{self.start_time}→{self.end_time} — extending end_time to +{MIN_DURATION}s"
            )
            extended_end = start + MIN_DURATION
            max_end = getattr(self, '_video_duration', float('inf')) - 0.5
            end = min(extended_end, max_end)
            self.end_time = _secs_to_ts(end)
            logger.info(f"[VALIDATOR] Extended segment: {self.start_time}→{self.end_time} (clamped to video bounds)")

        return self


class BRollOpportunity(BaseModel):
    """Identifies an opportunity to insert B-roll footage."""

    timestamp: str = Field(description="When to insert B-roll (MM:SS format)")
    duration: float = Field(
        description="How long to show B-roll (2-5 seconds)", ge=2.0, le=5.0
    )
    search_term: str = Field(description="Keyword to search for B-roll footage")
    context: str = Field(description="What's being discussed at this point")


class TranscriptAnalysis(BaseModel):
    """Analysis result for transcript segments with virality and B-roll opportunities."""

    most_relevant_segments: List[TranscriptSegment]
    summary: str = Field(description="Brief summary of the video content")
    key_topics: List[str] = Field(description="List of main topics discussed")
    broll_opportunities: Optional[List[BRollOpportunity]] = Field(
        default=None, description="B-roll insertion opportunities"
    )


VIRAL_SCORER_SYSTEM_PROMPT = """You are an expert viral content strategist and video editor with deep knowledge of TikTok, Instagram Reels, and YouTube Shorts algorithms.

Your task is to analyze video transcripts and identify the most viral-worthy segments.

For each segment you identify, provide:
1. Precise timestamps (MM:SS format)
2. The exact transcript text for that segment
3. A detailed virality analysis with scores for:
   - Hook strength (0-25): How compelling is the opening?
   - Engagement (0-25): Will viewers watch to the end?
   - Value (0-25): Educational, entertaining, or emotional value?
   - Shareability (0-25): Will people share this?
4. Hook type classification
5. Theme categorization
6. Suggested edits for maximum impact

CRITICAL RULES:
- Minimum segment duration: 30 seconds
- Maximum segment duration: 90 seconds
- Segments must not overlap
- Focus on complete thoughts or stories
- Prioritize segments with strong hooks
- Each segment must be self-contained and understandable without context

VIRAL CONTENT PATTERNS TO LOOK FOR:
- Controversial or surprising statements
- Emotional peaks (anger, joy, shock, inspiration)
- Actionable advice or clear value propositions
- Storytelling with clear narrative arc
- Relatable struggles or universal experiences
- Expert credibility moments
- Data or statistics that surprise
- Before/after transformations
- Strong opinion or hot take"""


def build_dynamic_user_prompt(
    transcript: str,
    video_duration: float,
    num_clips: int = 3,
    language: str = "en",
    min_score: float = 0.6,
) -> str:
    """Build a dynamic user prompt for viral segment extraction."""
    duration_str = f"{int(video_duration // 60)}:{int(video_duration % 60):02d}"

    return f"""Analyze this video transcript and identify the {num_clips} most viral-worthy segments.

VIDEO DURATION: {duration_str}
LANGUAGE: {language}
MINIMUM QUALITY THRESHOLD: {min_score * 100:.0f}/100

TRANSCRIPT:
{transcript}

Extract exactly {num_clips} segments that would perform best as short-form viral content.

Requirements:
1. Each segment must be 30-90 seconds long
2. Start with the strongest hook possible
3. Score each segment's viral potential with detailed breakdown
4. Provide specific editing suggestions
5. Ensure segments don't overlap

Return your analysis as a structured JSON response matching the TranscriptAnalysis schema."""


async def get_validated_segments(
    transcript: str,
    video_duration: float,
    num_clips: int = 3,
    language: str = "en",
    min_score: float = 0.6,
    model: str = "groq:llama-3.3-70b-versatile",
) -> TranscriptAnalysis:
    """
    Extract and validate viral segments from a transcript using AI.

    Args:
        transcript: The full video transcript text
        video_duration: Duration of the video in seconds
        num_clips: Number of clips to extract
        language: Language of the transcript
        min_score: Minimum relevance score threshold
        model: AI model to use for analysis

    Returns:
        TranscriptAnalysis with validated segments
    """
    if not PYDANTIC_AI_AVAILABLE:
        raise ImportError(
            "pydantic_ai is required for get_validated_segments. "
            "Install it with: pip install pydantic-ai"
        )

    agent = Agent(
        model=model,
        output_type=TranscriptAnalysis,
        system_prompt=VIRAL_SCORER_SYSTEM_PROMPT,
    )

    user_prompt = build_dynamic_user_prompt(
        transcript=transcript,
        video_duration=video_duration,
        num_clips=num_clips,
        language=language,
        min_score=min_score,
    )

    result = await agent.run(user_prompt)
    # pydantic-ai moderno usa .output; fallback a .data para compatibilidad
    analysis = getattr(result, "output", None) or getattr(result, "data", None)
    if analysis is None:
        raise ValueError("AgentRunResult has neither 'output' nor 'data' attribute")

    # Filter segments below minimum score
    filtered_segments = [
        seg for seg in analysis.most_relevant_segments
        if seg.relevance_score >= min_score
    ]

    if not filtered_segments:
        logger.warning(
            f"No segments met minimum score {min_score}. "
            f"Returning all {len(analysis.most_relevant_segments)} segments."
        )
        filtered_segments = analysis.most_relevant_segments

    analysis.most_relevant_segments = filtered_segments[:num_clips]
    return analysis


async def get_most_relevant_parts_by_transcript(
    transcript: str,
    video_duration: float,
    num_clips: int = 3,
    language: str = "en",
    min_score: float = 0.6,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Main entry point: extract the most viral segments from a transcript.

    Returns a list of dicts compatible with the legacy segment format used
    throughout the codebase.
    """
    effective_model = model or config.llm or "groq:llama-3.3-70b-versatile"

    try:
        analysis = await get_validated_segments(
            transcript=transcript,
            video_duration=video_duration,
            num_clips=num_clips,
            language=language,
            min_score=min_score,
            model=effective_model,
        )

        segments = []
        for seg in analysis.most_relevant_segments:
            segments.append({
                "start_time": seg.start_time,
                "end_time": seg.end_time,
                "text": seg.text,
                "relevance_score": seg.relevance_score,
                "reasoning": seg.reasoning,
                "virality_score": seg.virality_score,
                "hook_title": seg.hook_title,
                "theme": seg.theme,
                "suggested_edits": seg.suggested_edits,
                "virality": {
                    "hook_score": seg.virality.hook_score,
                    "engagement_score": seg.virality.engagement_score,
                    "value_score": seg.virality.value_score,
                    "shareability_score": seg.virality.shareability_score,
                    "total_score": seg.virality.total_score,
                    "hook_type": seg.virality.hook_type,
                    "virality_reasoning": seg.virality.virality_reasoning,
                },
            })

        return segments

    except Exception as e:
        logger.error(f"Error extracting segments: {e}")
        raise
