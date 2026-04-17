"""
Pydantic models for viral segment validation with field validators.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List
import re


class ViralSegment(BaseModel):
    """Validated viral segment with score and timing."""
    
    start: str = Field(pattern=r"^\d{1,2}:\d{2}$", description="Start time in MM:SS format")
    end: str = Field(pattern=r"^\d{1,2}:\d{2}$", description="End time in MM:SS format")
    hook_strength: float = Field(ge=0, le=10, description="Hook strength score 0-10")
    emotional_peak: float = Field(ge=0, le=10, description="Emotional peak score 0-10")
    shareability: float = Field(ge=0, le=10, description="Shareability score 0-10")
    retention: float = Field(ge=0, le=10, description="Retention score 0-10")
    viral_score: float = Field(ge=0, le=10, description="Overall viral score 0-10")
    reason: str = Field(min_length=5, max_length=200, description="1 sentence explaining virality")

    @staticmethod
    def _time_to_seconds(time_str: str) -> int:
        """Convert MM:SS to seconds."""
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    @field_validator("end")
    @classmethod
    def validate_end_time(cls, end: str, info) -> str:
        """Validate end time is after start time and minimum duration is met."""
        if "start" not in info.data:
            return end
        
        start_sec = cls._time_to_seconds(info.data["start"])
        end_sec = cls._time_to_seconds(end)
        
        if end_sec <= start_sec:
            raise ValueError(f"end ({end}) must be after start ({info.data['start']})")
        
        duration = end_sec - start_sec
        if duration < 30:
            raise ValueError(f"Segment duration must be at least 30 seconds, got {duration}s")
        
        return end

    @field_validator("viral_score")
    @classmethod
    def validate_viral_score_is_average(cls, viral_score: float, info) -> float:
        """Ensure viral_score is roughly the average of dimension scores."""
        if not all(k in info.data for k in ["hook_strength", "emotional_peak", "shareability", "retention"]):
            return viral_score
        
        expected = (
            info.data["hook_strength"] +
            info.data["emotional_peak"] +
            info.data["shareability"] +
            info.data["retention"]
        ) / 4.0
        
        # Allow 10% tolerance
        if abs(viral_score - expected) > 1.0:
            raise ValueError(
                f"viral_score ({viral_score:.2f}) should be close to average of dimensions ({expected:.2f})"
            )
        
        return viral_score


class ScoringResponse(BaseModel):
    """Complete scoring response with validated segments."""
    
    segments: List[ViralSegment] = Field(min_length=1, description="List of viral segments")

    @field_validator("segments")
    @classmethod
    def validate_unique_scores(cls, segments: List[ViralSegment]) -> List[ViralSegment]:
        """Ensure all viral scores are distinct (LLM rule compliance)."""
        scores = [seg.viral_score for seg in segments]
        if len(scores) != len(set(scores)):
            raise ValueError("All viral_score values must be distinct from each other")
        
        return segments
