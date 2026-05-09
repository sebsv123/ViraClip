"""
Long-form Coordinator — orchestrates the full pipeline: script → TTS → assemble → metadata.
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .script_writer import ScriptResult, write_script
from .narrator_tts import NarrationAudio, generate_narration
from .scene_assembler import AssembledVideo, assemble_video
from .yt_metadata_generator import YTMetadata, generate_yt_metadata

logger = logging.getLogger(__name__)


@dataclass
class LongformResult:
    video_path: Optional[Path]
    thumbnail_path: Optional[Path] = None
    metadata: Optional[YTMetadata] = None
    script: Optional[ScriptResult] = None
    total_duration: float = 0.0
    estimated_cost_usd: float = 0.0
    sections_count: int = 0
    status: str = "pending"
    error: Optional[str] = None


async def create_longform_video(
    topic: str,
    duration_seconds: int = 600,
    output_dir: Path = Path("/app/exports/longform"),
) -> LongformResult:
    """Orchestrate the full long-form video creation pipeline."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = LongformResult(status="processing")

    try:
        # Phase 1: Script writing
        logger.info(f"[Longform] Phase 1/4: Writing script for '{topic}' ({duration_seconds}s)")
        script = await write_script(topic, duration_seconds)
        if not script or not script.sections:
            return LongformResult(status="failed", error="Script generation returned empty result")
        result.script = script
        result.sections_count = len(script.sections)
        logger.info(f"[Longform] ✓ Script: {script.title} ({len(script.sections)} sections)")

        # Phase 2: Narration TTS
        logger.info(f"[Longform] Phase 2/4: Generating narration ({len(script.sections)} sections)")
        narrations = await generate_narration(script.sections)
        if not narrations:
            return LongformResult(status="failed", error="Narration generation failed")
        logger.info(f"[Longform] ✓ Narration: {len(narrations)} audio files")

        # Phase 3: Video assembly
        output_path = output_dir / f"longform_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.mp4"
        logger.info(f"[Longform] Phase 3/4: Assembling video → {output_path}")
        video = await assemble_video(script.sections, narrations, output_path)
        result.video_path = video.output_path
        result.total_duration = video.total_duration
        logger.info(f"[Longform] ✓ Video: {video.total_duration:.0f}s, {video.sections_count} scenes")

        # Phase 4: YouTube metadata
        logger.info(f"[Longform] Phase 4/4: Generating YouTube metadata")
        metadata = await generate_yt_metadata(script)
        result.metadata = metadata
        logger.info(f"[Longform] ✓ Metadata: {metadata.title if metadata else 'N/A'}")

        # Cost estimation
        total_chars = sum(len(s.narration_text) for s in script.sections)
        total_tokens = sum(len(s.narration_text.split()) for s in script.sections) * 1.5
        result.estimated_cost_usd = round(
            total_tokens * 0.00000027 +  # DeepSeek cost per token
            total_chars * 0.00003,       # ElevenLabs cost per character
            4
        )
        result.status = "completed"

    except Exception as e:
        logger.error(f"[Longform] Pipeline failed: {e}", exc_info=True)
        result.status = "failed"
        result.error = str(e)

    return result
