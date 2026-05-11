"""Video download + transcript generation/analysis.

Wraps the YouTube downloader and AI analysis utilities into a small,
focused module that the rest of the pipeline can call directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional, cast

from ...ai import get_most_relevant_parts_by_transcript
from ...config import Config
from ...video_processing import get_video_transcript
from ...youtube_utils import (
    async_download_youtube_video,
    async_get_youtube_video_title,
)
from ._helpers import get_service_config

logger = logging.getLogger(__name__)


async def download_video(url: str, task_id: Optional[str] = None) -> Optional[Path]:
    """Download a YouTube video asynchronously."""
    logger.info(f"Starting video download: {url}")
    video_path = await async_download_youtube_video(url, 3, task_id)

    if not video_path:
        logger.error(f"Failed to download video: {url}")
        return None

    logger.info(f"Video downloaded successfully: {video_path}")
    return video_path


async def get_video_title(url: str) -> str:
    """Get video title asynchronously, with a fallback."""
    try:
        title = await async_get_youtube_video_title(url)
        return title or "YouTube Video"
    except Exception as e:
        logger.warning(f"Failed to get video title: {e}")
        return "YouTube Video"


async def generate_transcript(video_path: Path, processing_mode: str = "balanced") -> str:
    """Generate transcript from video using faster-whisper."""
    cfg = get_service_config()
    logger.info(f"Generating transcript for: {video_path}")
    speech_model = "best"
    if processing_mode == "fast":
        speech_model = cfg.fast_mode_transcript_model

    transcript_text, _transcript_data = await get_video_transcript(video_path, speech_model)
    transcript = cast(str, transcript_text)
    logger.info(f"Transcript generated: {len(transcript)} characters")
    return transcript


class _SegmentsWrapper:
    """Minimal wrapper so callers can access .most_relevant_segments, .summary, .key_topics."""

    def __init__(self, segments: list) -> None:
        self.most_relevant_segments = segments
        self.summary = ""
        self.key_topics: list[str] = []


async def analyze_transcript(
    transcript: str,
    video_duration: float = 0.0,
    include_broll: bool = False,  # kept for API compat; B-roll handled downstream
) -> Any:
    """
    Analyze transcript with AI to find relevant segments.

    Args:
        transcript: Video transcript text
        video_duration: Total video duration in seconds (0 if unknown)
        include_broll: Reserved for future use; B-roll logic lives in the creative pipeline.
    """
    logger.info(
        f"[AI ANALYSIS] Starting transcript analysis "
        f"(duration={video_duration:.1f}s, transcript_length={len(transcript)} chars)"
    )
    logger.info(f"[AI ANALYSIS] LLM model configured: {Config().llm}")

    try:
        # get_most_relevant_parts_by_transcript returns List[Dict] — wrap it so
        # downstream code can use .most_relevant_segments without changes.
        segments = await get_most_relevant_parts_by_transcript(
            transcript,
            video_duration=video_duration,
        )

        relevant_parts = _SegmentsWrapper(segments)

        segments_count = len(relevant_parts.most_relevant_segments)
        logger.info(f"[AI ANALYSIS] ✅ Complete: {segments_count} segments found")

        if segments_count == 0:
            logger.error(
                "[AI ANALYSIS] ❌ CRITICAL: LLM returned 0 segments! "
                "This will cause 'No Clips Generated' error. "
                "Check: 1) LLM is running, 2) API key is valid, 3) Transcript quality"
            )
            logger.error(f"[AI ANALYSIS] Transcript preview (first 500 chars): {transcript[:500]}")
        else:
            first_seg = relevant_parts.most_relevant_segments[0]
            if isinstance(first_seg, dict):
                logger.info(
                    f"[AI ANALYSIS] First segment: {first_seg.get('start_time')}-"
                    f"{first_seg.get('end_time')}, virality={first_seg.get('virality_score', 'N/A')}"
                )
            else:
                vir_score = (
                    getattr(first_seg.virality, "total_score", "N/A")
                    if hasattr(first_seg, "virality")
                    else "N/A"
                )
                logger.info(
                    f"[AI ANALYSIS] First segment: {first_seg.start_time}-"
                    f"{first_seg.end_time}, virality={vir_score}"
                )

        return relevant_parts

    except Exception as e:
        logger.error(
            f"[AI ANALYSIS] ❌ EXCEPTION during transcript analysis: {type(e).__name__}: {e}",
            exc_info=True,
        )
        raise
