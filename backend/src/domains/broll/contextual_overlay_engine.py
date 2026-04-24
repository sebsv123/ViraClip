"""
Contextual Overlay Engine — Main Orchestrator

Coordinates keyword detection, content sourcing, and overlay rendering.
This is the critical viral feature for TikTok/Reels-style content.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class OverlayEngineResult:
    """Result of contextual overlay processing."""
    success: bool
    output_path: Optional[str] = None
    overlays_applied: int = 0
    keywords_detected: int = 0
    error: Optional[str] = None


class ContextualOverlayEngine:
    """
    Main engine for contextual image/video overlays.
    
    Workflow:
    1. Detect visual keywords from transcript with timing
    2. Fetch appropriate content (images/videos) for each keyword
    3. Render overlays onto video with speaker in corner bubble
    
    This is the #1 viral feature on TikTok/Reels/Shorts.
    """
    
    def __init__(self):
        self.enabled = os.environ.get("CONTEXTUAL_OVERLAYS_ENABLED", "true").lower() == "true"
        self.max_overlays = int(os.environ.get("MAX_OVERLAYS_PER_CLIP", "8"))
        self.min_virality_score = float(os.environ.get("OVERLAY_MIN_VIRALITY", "60.0"))
    
    async def apply_overlays(
        self,
        video_path: Path,
        output_path: Path,
        transcript: str,
        word_timings: List[dict],
        audio_features: dict = None,
        virality_score: float = 50.0,
        overlay_frequency: str = "adaptive"
    ) -> OverlayEngineResult:
        """
        Apply contextual overlays to a video clip.
        
        Args:
            video_path: Input video path
            output_path: Output video path
            transcript: Full transcript text
            word_timings: Word-level timings [{word, start, end}]
            audio_features: Audio analysis features
            virality_score: Clip virality score (0-100)
            overlay_frequency: "low", "medium", "high", "very_high", or "adaptive"
            
        Returns:
            OverlayEngineResult with success status and metadata
        """
        if not self.enabled:
            logger.debug("Contextual overlays DISABLED")
            return OverlayEngineResult(success=False, error="Feature disabled")
        
        if not video_path.exists():
            return OverlayEngineResult(success=False, error=f"Video not found: {video_path}")
        
        if not word_timings:
            logger.debug("No word timings, skipping overlays")
            return OverlayEngineResult(success=False, error="No word timings")
        
        try:
            # Step 1: Detect visual keywords
            from ...domains.detection.visual_keyword_detector import get_visual_keyword_detector
            
            detector = get_visual_keyword_detector()
            
            # Determine max keywords based on frequency
            max_kw = self._get_max_keywords(overlay_frequency)
            
            # Detect with virality filter
            if overlay_frequency == "adaptive":
                keywords = detector.detect_with_virality_filter(
                    transcript=transcript,
                    word_timings=word_timings,
                    audio_features=audio_features or {},
                    virality_score=virality_score,
                    max_keywords=max_kw
                )
            else:
                keywords = detector.detect(
                    transcript=transcript,
                    word_timings=word_timings,
                    max_keywords=max_kw
                )
            
            if not keywords:
                logger.info("No visual keywords detected for overlays")
                return OverlayEngineResult(
                    success=False,
                    keywords_detected=0,
                    error="No keywords detected"
                )
            
            logger.info(f"Detected {len(keywords)} visual keywords: {[k.keyword for k in keywords]}")
            
            # Step 2: Fetch content for each keyword
            from .overlay_content_source import get_overlay_content_source
            
            content_source = get_overlay_content_source()
            
            overlay_tasks = []
            for kw in keywords:
                task = content_source.get_content(
                    keyword=kw.keyword,
                    category=kw.category,
                    prefer_video=False,  # Prefer images for faster processing
                    duration=kw.end_time - kw.start_time
                )
                overlay_tasks.append(task)
            
            # Fetch all content in parallel
            content_results = await asyncio.gather(*overlay_tasks, return_exceptions=True)
            
            # Build overlay events
            from ...video_processing.overlay_renderer import OverlayEvent, OverlayStyle
            
            overlay_events = []
            for kw, content in zip(keywords, content_results):
                if content and not isinstance(content, Exception):
                    overlay_events.append(OverlayEvent(
                        overlay_path=content.path,
                        start_time=kw.start_time,
                        end_time=kw.end_time,
                        keyword=kw.keyword,
                        style=OverlayStyle.FULL_SCREEN_BUBBLE,
                        is_video=content.is_video
                    ))
                else:
                    logger.debug(f"Failed to get content for '{kw.keyword}': {content}")
            
            if not overlay_events:
                logger.warning("No overlay content could be fetched")
                return OverlayEngineResult(
                    success=False,
                    keywords_detected=len(keywords),
                    error="No content fetched"
                )
            
            logger.info(f"Fetched content for {len(overlay_events)}/{len(keywords)} keywords")
            
            # Step 3: Render overlays
            from ...video_processing.overlay_renderer import get_overlay_renderer
            
            renderer = get_overlay_renderer()
            
            result = await renderer.render_overlays(
                base_video=video_path,
                overlay_events=overlay_events,
                output_path=output_path,
                style=OverlayStyle.FULL_SCREEN_BUBBLE
            )
            
            if result.success:
                logger.info(f"✓ Contextual overlays applied: {result.overlays_applied} overlays")
                return OverlayEngineResult(
                    success=True,
                    output_path=result.output_path,
                    overlays_applied=result.overlays_applied,
                    keywords_detected=len(keywords)
                )
            else:
                logger.error(f"Overlay rendering failed: {result.error}")
                return OverlayEngineResult(
                    success=False,
                    keywords_detected=len(keywords),
                    error=result.error
                )
        
        except Exception as e:
            logger.error(f"Contextual overlay engine error: {e}", exc_info=True)
            return OverlayEngineResult(success=False, error=str(e))
    
    def _get_max_keywords(self, frequency: str) -> int:
        """Determine max keywords based on frequency setting."""
        frequency_map = {
            "low": 3,
            "medium": 5,
            "high": 8,
            "very_high": 12,
            "adaptive": 8  # Default for adaptive
        }
        return frequency_map.get(frequency, self.max_overlays)


# Singleton
_engine_instance: Optional[ContextualOverlayEngine] = None


def get_contextual_overlay_engine() -> ContextualOverlayEngine:
    """Get or create singleton engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ContextualOverlayEngine()
    return _engine_instance
