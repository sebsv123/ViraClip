"""
Data contract between AI analysis and renderer.
Adapted from schibsted/videofy_minimal - bridges the gap between ai.py and video_utils.py.
"""

from pydantic import BaseModel
from typing import Literal


class TextLine(BaseModel):
    """Text block with timestamp (from Whisper word-level)."""
    line_id: int
    text: str
    display_text: str | None = None
    start: float
    end: float
    who: str = "default"


class SegmentAsset(BaseModel):
    """Visual asset assigned to a segment."""
    type: Literal["frame", "broll", "generated"]
    path: str
    url: str | None = None
    description: str | None = None
    hotspot: dict | None = None


class Segment(BaseModel):
    """Segment = minimum unit of edited clip."""
    id: int
    # From ViraClip ai.py
    virality_score: float = 0.0
    hook_score: float = 0.0
    hook_type: str = "none"
    mood: str = "neutral"
    # From Videofy
    camera_movement: str = "none"
    style: str = "bottom"
    # Content
    texts: list[TextLine]
    assets: list[SegmentAsset] = []
    # Timestamps
    start: float
    end: float


class ClipTimeline(BaseModel):
    """Complete timeline of a clip."""
    clip_id: str
    task_id: str
    source_url: str
    preset: str = "default"
    segments: list[Segment]
    total_duration: float


DEFAULT_CAMERA_MOVEMENTS = [
    "zoom-in", "pan-right", "zoom-in",
    "pan-left", "zoom-in", "zoom-out",
]

VALID_CAMERA_MOVEMENTS = {
    "none", "pan-left", "pan-right", "pan-up", "pan-down",
    "zoom-in", "zoom-out", "zoom-rotate-left", "zoom-rotate-right",
}
