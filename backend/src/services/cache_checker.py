"""
mtime-based cache checking to avoid reprocessing completed tasks.
"""

import os
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class CacheChecker:
    """Check for existing processed clips before starting pipeline."""
    
    def __init__(self, temp_dir: str = "/app/temp/uploads"):
        self.temp_dir = Path(temp_dir)
        self.clips_dir = self.temp_dir / "clips"
    
    async def check_existing_clips(
        self,
        task_id: str,
        video_path: str,
        min_clips: int = 1,
        force_fresh: bool = False
    ) -> Optional[List[dict]]:
        """
        Check if clips already exist for this task and are newer than source video.
        
        Args:
            task_id: Task identifier
            video_path: Path to source video file
            min_clips: Minimum number of clips to consider cache valid
            force_fresh: If True, always return None to force reprocessing (for testing improvements)
            
        Returns:
            List of clip metadata dicts if cache is valid, None otherwise
        """
        # CACHE DISABLED: Always process fresh clips
        logger.info(f"🔄 Cache disabled for task {task_id}: processing fresh clips")
        return None
        
        # FORCE FRESH: Skip cache entirely when comparing improvements
        if force_fresh:
            logger.info(f"🔄 Force fresh enabled for task {task_id}: skipping cache check")
            return None
        
        try:
            # Get video file mtime
            video_mtime = os.path.getmtime(video_path)
            
            # Find clips matching this task_id
            clip_pattern = f"clip_*_viral_{task_id}*.mp4"
            clip_files = list(self.clips_dir.glob(clip_pattern))
            
            if len(clip_files) < min_clips:
                logger.debug(f"Cache miss: only {len(clip_files)} clips found for task {task_id}")
                return None
            
            # Check if all clips are newer than the video
            clips_metadata = []
            for clip_path in clip_files:
                clip_mtime = os.path.getmtime(clip_path)
                
                if clip_mtime < video_mtime:
                    logger.debug(
                        f"Cache invalid: clip {clip_path.name} is older than source video"
                    )
                    return None
                
                # Extract clip metadata
                clips_metadata.append({
                    "path": str(clip_path),
                    "filename": clip_path.name,
                    "size_bytes": clip_path.stat().st_size,
                    "created_at": datetime.fromtimestamp(clip_mtime).isoformat(),
                    "duration_estimate": self._estimate_duration(clip_path)
                })
            
            logger.info(
                f"✅ Cache hit: {len(clips_metadata)} valid clips found for task {task_id}"
            )
            return clips_metadata
            
        except FileNotFoundError:
            logger.debug(f"Cache miss: video file not found at {video_path}")
            return None
        except Exception as e:
            logger.warning(f"Cache check failed for task {task_id}: {e}")
            return None
    
    def _estimate_duration(self, clip_path: Path) -> Optional[float]:
        """
        Estimate clip duration from file size (rough approximation).
        For more accurate duration, would need ffprobe, but that's overkill for cache check.
        """
        try:
            size_mb = clip_path.stat().st_size / (1024 * 1024)
            # Rough estimate: ~1MB per 10 seconds for compressed social media clips
            return size_mb * 10.0
        except Exception:
            return None
    
    async def invalidate_cache(self, task_id: str) -> int:
        """
        Delete all clips for a given task (cache invalidation).
        
        Args:
            task_id: Task identifier
            
        Returns:
            Number of clips deleted
        """
        try:
            clip_pattern = f"clip_*_viral_{task_id}*"
            clip_files = list(self.clips_dir.glob(clip_pattern))
            
            deleted = 0
            for clip_path in clip_files:
                clip_path.unlink()
                deleted += 1
            
            if deleted > 0:
                logger.info(f"🗑️  Invalidated cache: deleted {deleted} clips for task {task_id}")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Cache invalidation failed for task {task_id}: {e}")
            return 0
    
    async def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        try:
            all_clips = list(self.clips_dir.glob("clip_*.mp4"))
            total_size = sum(f.stat().st_size for f in all_clips)
            
            return {
                "total_clips": len(all_clips),
                "total_size_gb": round(total_size / (1024**3), 2),
                "clips_dir": str(self.clips_dir),
                "oldest_clip": min(
                    (datetime.fromtimestamp(f.stat().st_mtime) for f in all_clips),
                    default=None
                ).isoformat() if all_clips else None,
                "newest_clip": max(
                    (datetime.fromtimestamp(f.stat().st_mtime) for f in all_clips),
                    default=None
                ).isoformat() if all_clips else None
            }
        except Exception as e:
            return {
                "error": str(e)
            }


# Singleton instance
_cache_checker: Optional[CacheChecker] = None


def get_cache_checker(temp_dir: str = "/app/temp/uploads") -> CacheChecker:
    """Get or create cache checker singleton."""
    global _cache_checker
    if _cache_checker is None:
        _cache_checker = CacheChecker(temp_dir)
    return _cache_checker
