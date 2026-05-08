"""
SFX Orchestrator — coordinates LLM query generation + Freesound download + mixing.
"""
import logging
import os
from typing import Any, Dict, List, Optional

from .sfx_llm_query import generate_sfx_plan
from .freesound_client import FreesoundClient
from .sfx_mixer import apply_sfx

logger = logging.getLogger(__name__)


class SFXOrchestrator:
    """Orchestrates the full SFX pipeline: plan → fetch → mix."""

    def __init__(self, freesound_client: Optional[FreesoundClient] = None):
        self.freesound = freesound_client or FreesoundClient()
        self.enabled = os.getenv("SFX_ENABLED", "false").lower() == "true"

    async def plan_and_fetch(
        self,
        transcript_segments: List[Dict[str, Any]],
        jump_cuts: List[float],
        clip_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate SFX plan via LLM and download all assets from Freesound."""
        if not self.enabled:
            logger.debug("[SFX] Disabled (SFX_ENABLED=false)")
            return []

        clip_metadata = clip_metadata or {}

        try:
            # Step 1: LLM generates the SFX plan
            plan = await generate_sfx_plan(
                transcript_segments=transcript_segments,
                jump_cuts=jump_cuts,
                video_topic=clip_metadata.get("topic", ""),
                mood=clip_metadata.get("mood", "neutral"),
                energy=clip_metadata.get("energy", 0.5),
                clip_duration=clip_metadata.get("duration", 60),
            )

            if not plan:
                logger.info("[SFX] LLM returned empty plan")
                return []

            # Step 2: Download each SFX from Freesound
            for sfx in plan:
                query = sfx.get("freesound_query", "")
                category = sfx.get("category", "transitions")
                path = await self.freesound.search_and_download(
                    query=query,
                    category=category,
                )
                sfx["local_path"] = path
                if path:
                    logger.info(f"[SFX] ✅ {category}: '{query}' → {path}")
                else:
                    logger.warning(f"[SFX] ⚠️ Not found: '{query}'")

            # Filter to only valid SFX
            valid = [s for s in plan if s.get("local_path")]
            logger.info(f"[SFX] Plan: {len(valid)}/{len(plan)} SFX ready")
            return valid

        except Exception as e:
            logger.error(f"[SFX] Orchestrator error: {e}")
            return []

    async def process_clip(
        self,
        input_path: str,
        output_path: str,
        transcript_segments: List[Dict[str, Any]],
        jump_cuts: List[float],
        clip_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Full pipeline: plan → fetch → mix for a single clip."""
        sfx_plan = await self.plan_and_fetch(
            transcript_segments=transcript_segments,
            jump_cuts=jump_cuts,
            clip_metadata=clip_metadata,
        )

        if not sfx_plan:
            return input_path

        return await apply_sfx(
            input_video=input_path,
            sfx_plan=sfx_plan,
            output_path=output_path,
        )

    async def close(self):
        await self.freesound.close()
