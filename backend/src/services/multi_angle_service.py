"""
Multi-Angle Service - orchestrates processing of multiple camera angles.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
from ..utils.audio_analysis import find_audio_offset

if TYPE_CHECKING:
    from .video_service import VideoService

logger = logging.getLogger(__name__)

class MultiAngleService:
    """Service for handling multiple video sources (e.g., dual-angle shots)."""

    def __init__(self, video_service: Optional["VideoService"] = None):
        if video_service is None:
            from .video_service import VideoService
            video_service = VideoService()
        self.video_service = video_service

    async def synchronize_sources(self, primary_path: Path, secondary_path: Path) -> Dict[str, Any]:
        """
        Calculates the temporal sync between two angles.
        Returns sync metadata.
        """
        logger.info(f"Synchronizing angles: {primary_path.name} and {secondary_path.name}")
        
        try:
            offset = find_audio_offset(primary_path, secondary_path)
            
            return {
                "offset_seconds": offset,
                "sync_ready": True,
                "primary": str(primary_path),
                "secondary": str(secondary_path)
            }
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            return {"sync_ready": False, "error": str(e)}

    def get_aligned_timestamps(self, primary_start: float, primary_end: float, offset: float) -> Tuple[float, float]:
        """
        Maps a timestamp from the primary video to the equivalent in the secondary video.
        Offset: pos means secondary starts AFTER primary.
        """
        # If secondary starts 2s AFTER primary, then 'secondary_time = primary_time - 2s'
        secondary_start = primary_start - offset
        secondary_end = primary_end - offset
        return secondary_start, secondary_end

    def generate_camera_switching_plan(self, duration: float, interval: float = 3.3) -> List[Dict[str, Any]]:
        """
        Generates a schedule of cuts between angles.
        In production, this would be based on 'shot energy' or face detection.
        For V2 prototype, it's a rhythmic switch every 'interval' seconds.
        """
        logger.info(f"Generating camera switching plan for {duration}s video (interval: {interval}s)")
        plan = []
        current_time = 0.0
        current_angle = 0 # 0=primary, 1=secondary
        
        while current_time < duration:
            end_time = min(current_time + interval, duration)
            plan.append({
                "start": current_time,
                "end": end_time,
                "angle": current_angle
            })
            current_time = end_time
            current_angle = 1 - current_angle # Toggle
            
        return plan
