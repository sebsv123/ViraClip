"""
Scene-Aware Segment Selection

Integrates scene detection to create smoother clips that respect scene boundaries.
Prevents jarring mid-scene cuts.
"""

import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class SceneAwareSegmenter:
    """Refines segment boundaries using scene detection."""
    
    def __init__(self):
        self.enabled = True
        self.scene_boundary_threshold = 1.0  # seconds
    
    async def refine_segments_with_scenes(
        self,
        video_path: Path,
        ai_segments: List[Dict[str, Any]],
        use_scene_detection: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Refine AI-selected segments to align with scene boundaries.
        
        Args:
            video_path: Source video
            ai_segments: AI-selected segments (from virality scoring)
            use_scene_detection: Enable scene-aware refinement
            
        Returns:
            Refined segments with adjusted boundaries
        """
        if not use_scene_detection or not ai_segments:
            return ai_segments
        
        try:
            # Detect scene changes in video
            from .scene_detection import SceneDetectionService
            
            scene_service = SceneDetectionService()
            scene_segments = await scene_service.detect_scenes(video_path)
            
            if not scene_segments:
                logger.debug("No scenes detected, using original segments")
                return ai_segments
            
            # Refine each AI segment to align with scene boundaries
            refined_segments = []
            
            for seg in ai_segments:
                start = float(seg.get("start_time", seg.get("start", 0)))
                end = float(seg.get("end_time", seg.get("end", start + 30)))
                
                # Find closest scene boundaries
                refined_start, refined_end = self._find_scene_boundaries(
                    start, end, scene_segments
                )
                
                # Create refined segment
                refined_seg = seg.copy()
                refined_seg["start_time"] = refined_start
                refined_seg["end_time"] = refined_end
                refined_seg["original_start"] = start
                refined_seg["original_end"] = end
                refined_seg["scene_aligned"] = True
                
                # Adjust duration if changed
                original_duration = end - start
                new_duration = refined_end - refined_start
                duration_change = new_duration - original_duration
                
                if abs(duration_change) > 0.5:
                    logger.info(
                        f"Scene alignment adjusted segment by {duration_change:.1f}s "
                        f"({start:.1f}-{end:.1f} → {refined_start:.1f}-{refined_end:.1f})"
                    )
                
                refined_segments.append(refined_seg)
            
            logger.info(f"✓ Scene-aware refinement: {len(refined_segments)} segments aligned")
            return refined_segments
        
        except Exception as e:
            logger.warning(f"Scene detection failed, using original segments: {e}")
            return ai_segments
    
    def _find_scene_boundaries(
        self,
        start: float,
        end: float,
        scene_segments: List[Any]
    ) -> tuple:
        """
        Find closest scene boundaries to given start/end times.
        
        Returns:
            (refined_start, refined_end) aligned to scene boundaries
        """
        # Find scene that contains start time
        start_scene = None
        end_scene = None
        
        for scene in scene_segments:
            scene_start = scene.start_time
            scene_end = scene.end_time
            
            # Check if start falls in this scene
            if scene_start <= start <= scene_end:
                start_scene = scene
            
            # Check if end falls in this scene
            if scene_start <= end <= scene_end:
                end_scene = scene
        
        # Determine refined boundaries
        if start_scene:
            # If start is near scene boundary, snap to it
            if abs(start - start_scene.start_time) < self.scene_boundary_threshold:
                refined_start = start_scene.start_time
            else:
                refined_start = start
        else:
            refined_start = start
        
        if end_scene:
            # If end is near scene boundary, snap to it
            if abs(end - end_scene.end_time) < self.scene_boundary_threshold:
                refined_end = end_scene.end_time
            else:
                refined_end = end
        else:
            refined_end = end
        
        # Ensure minimum duration
        if refined_end - refined_start < 3.0:
            # Too short, use original
            refined_start = start
            refined_end = end
        
        return refined_start, refined_end


# Singleton
_segmenter_instance: Optional[SceneAwareSegmenter] = None


def get_scene_aware_segmenter() -> SceneAwareSegmenter:
    """Get or create singleton scene-aware segmenter."""
    global _segmenter_instance
    if _segmenter_instance is None:
        _segmenter_instance = SceneAwareSegmenter()
    return _segmenter_instance
