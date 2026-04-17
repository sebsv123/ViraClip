"""
Live Streaming Clip Extraction Service
Extract viral clips from live streams in real-time.
"""

import logging
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)


class StreamStatus(Enum):
    """Live stream processing status."""
    IDLE = "idle"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    PROCESSING = "processing"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class ClipTriggerType(Enum):
    """Types of clip triggers."""
    MANUAL = "manual"           # User-initiated
    AUTO_VIRAL = "auto_viral"   # AI-detected viral moment
    CHAT_COMMAND = "chat"       # Chat command trigger
    SCHEDULED = "scheduled"     # Time-based
    EVENT = "event"             # Special event detected


@dataclass
class LiveClip:
    """Clip extracted from live stream."""
    clip_id: str
    stream_id: str
    start_time: datetime
    end_time: datetime
    duration_seconds: float
    trigger_type: ClipTriggerType
    viral_score: float
    preview_url: Optional[str]
    status: str  # pending, processing, ready, published
    chat_reaction_count: int
    peak_viewer_count: int


@dataclass
class StreamConfig:
    """Live stream configuration."""
    stream_id: str
    stream_url: str
    platform: str  # youtube, twitch, etc.
    auto_clip_enabled: bool
    clip_duration: int  # seconds
    viral_threshold: float
    chat_monitoring: bool
    output_format: str


class LiveStreamService:
    """
    Service for processing live streams and extracting clips.
    """
    
    def __init__(self, output_dir: Path = Path("/app/temp/live_clips")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self._active_streams: Dict[str, StreamConfig] = {}
        self._stream_status: Dict[str, StreamStatus] = {}
        self._extracted_clips: Dict[str, List[LiveClip]] = {}
        self._processing_tasks: Dict[str, asyncio.Task] = {}
    
    async def start_stream_monitoring(
        self,
        stream_id: str,
        stream_url: str,
        platform: str,
        config: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Start monitoring a live stream for clip extraction.
        
        Args:
            stream_id: Unique stream identifier
            stream_url: Stream URL (HLS/M3U8)
            platform: Streaming platform
            config: Additional configuration
        """
        if stream_id in self._active_streams:
            logger.warning(f"Stream {stream_id} is already being monitored")
            return False
        
        cfg = StreamConfig(
            stream_id=stream_id,
            stream_url=stream_url,
            platform=platform,
            auto_clip_enabled=config.get("auto_clip", True) if config else True,
            clip_duration=config.get("clip_duration", 30) if config else 30,
            viral_threshold=config.get("viral_threshold", 75.0) if config else 75.0,
            chat_monitoring=config.get("chat_monitoring", True) if config else True,
            output_format=config.get("format", "vertical") if config else "vertical"
        )
        
        self._active_streams[stream_id] = cfg
        self._stream_status[stream_id] = StreamStatus.CONNECTING
        self._extracted_clips[stream_id] = []
        
        # Start background processing
        task = asyncio.create_task(self._process_stream(stream_id))
        self._processing_tasks[stream_id] = task
        
        logger.info(f"Started monitoring stream: {stream_id} from {platform}")
        return True
    
    async def _process_stream(self, stream_id: str) -> None:
        """Background task to process live stream."""
        try:
            self._stream_status[stream_id] = StreamStatus.STREAMING
            
            while stream_id in self._active_streams:
                # Check for viral moments
                await self._detect_viral_moments(stream_id)
                
                # Wait before next check
                await asyncio.sleep(5)
                
        except Exception as e:
            logger.error(f"Stream processing error for {stream_id}: {e}")
            self._stream_status[stream_id] = StreamStatus.ERROR
        
        finally:
            self._stream_status[stream_id] = StreamStatus.DISCONNECTED
    
    async def _detect_viral_moments(self, stream_id: str) -> None:
        """Detect viral moments in live stream."""
        # This would analyze:
        # - Chat activity spikes
        # - Viewer count changes
        # - Audio levels (laughter, excitement)
        # - Visual activity
        
        # Placeholder: Simulate detection
        pass
    
    async def extract_clip(
        self,
        stream_id: str,
        duration: int = 30,
        trigger: ClipTriggerType = ClipTriggerType.MANUAL,
        custom_start: Optional[datetime] = None
    ) -> Optional[LiveClip]:
        """
        Extract a clip from the live stream.
        
        Args:
            stream_id: Stream identifier
            duration: Clip duration in seconds
            trigger: What triggered the clip
            custom_start: Custom start time (None = now)
        """
        if stream_id not in self._active_streams:
            return None
        
        import uuid
        
        clip_id = f"live_{stream_id}_{uuid.uuid4().hex[:8]}"
        
        # Determine time range
        end_time = datetime.now()
        if custom_start:
            start_time = custom_start
        else:
            start_time = end_time - timedelta(seconds=duration)
        
        # Create clip record
        clip = LiveClip(
            clip_id=clip_id,
            stream_id=stream_id,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration,
            trigger_type=trigger,
            viral_score=0.0,  # Will be calculated
            preview_url=None,
            status="processing",
            chat_reaction_count=0,
            peak_viewer_count=0
        )
        
        # Start clip extraction
        asyncio.create_task(self._process_clip_extraction(clip))
        
        # Add to extracted clips
        self._extracted_clips[stream_id].append(clip)
        
        logger.info(f"Extracting clip {clip_id} from stream {stream_id}")
        return clip
    
    async def _process_clip_extraction(self, clip: LiveClip) -> None:
        """Process clip extraction from stream."""
        try:
            # This would:
            # 1. Download segment from HLS stream
            # 2. Process with standard clip pipeline
            # 3. Generate preview
            # 4. Calculate viral score
            
            # Simulate processing
            await asyncio.sleep(2)
            
            # Calculate viral score based on stream metrics
            clip.viral_score = await self._calculate_live_viral_score(clip)
            clip.status = "ready"
            
            logger.info(f"Clip {clip.clip_id} ready with score {clip.viral_score:.1f}")
            
        except Exception as e:
            logger.error(f"Clip extraction failed: {e}")
            clip.status = "error"
    
    async def _calculate_live_viral_score(self, clip: LiveClip) -> float:
        """Calculate viral score for live clip."""
        # Factors for live clips:
        # - Chat velocity during clip
        # - Viewer retention
        # - Trigger type (manual vs auto)
        # - Time of stream
        
        base_score = 50.0
        
        # Boost for chat reactions
        chat_boost = min(20, clip.chat_reaction_count / 10)
        
        # Boost for peak viewers
        viewer_boost = min(15, clip.peak_viewer_count / 100)
        
        # Trigger type bonus
        trigger_bonus = {
            ClipTriggerType.MANUAL: 5,
            ClipTriggerType.AUTO_VIRAL: 15,
            ClipTriggerType.CHAT_COMMAND: 10,
            ClipTriggerType.SCHEDULED: 0,
            ClipTriggerType.EVENT: 20
        }.get(clip.trigger_type, 0)
        
        return min(100, base_score + chat_boost + viewer_boost + trigger_bonus)
    
    async def stop_stream_monitoring(self, stream_id: str) -> bool:
        """Stop monitoring a stream."""
        if stream_id not in self._active_streams:
            return False
        
        # Cancel processing task
        if stream_id in self._processing_tasks:
            self._processing_tasks[stream_id].cancel()
            del self._processing_tasks[stream_id]
        
        # Clean up
        del self._active_streams[stream_id]
        del self._stream_status[stream_id]
        
        # Keep clips for now, they might still be processing
        logger.info(f"Stopped monitoring stream: {stream_id}")
        return True
    
    def get_stream_status(self, stream_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a monitored stream."""
        if stream_id not in self._active_streams:
            return None
        
        clips = self._extracted_clips.get(stream_id, [])
        
        return {
            "stream_id": stream_id,
            "status": self._stream_status.get(stream_id, StreamStatus.IDLE).value,
            "config": {
                "platform": self._active_streams[stream_id].platform,
                "auto_clip_enabled": self._active_streams[stream_id].auto_clip_enabled,
                "viral_threshold": self._active_streams[stream_id].viral_threshold
            },
            "clips_extracted": len(clips),
            "clips_ready": sum(1 for c in clips if c.status == "ready"),
            "total_duration": sum(c.duration_seconds for c in clips)
        }
    
    def get_stream_clips(
        self,
        stream_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all clips extracted from a stream."""
        if stream_id not in self._extracted_clips:
            return []
        
        clips = self._extracted_clips[stream_id]
        
        if status:
            clips = [c for c in clips if c.status == status]
        
        return [
            {
                "clip_id": c.clip_id,
                "start_time": c.start_time.isoformat(),
                "duration": c.duration_seconds,
                "trigger": c.trigger_type.value,
                "viral_score": c.viral_score,
                "status": c.status,
                "chat_reactions": c.chat_reaction_count
            }
            for c in sorted(clips, key=lambda x: x.start_time, reverse=True)
        ]
    
    async def publish_clip(
        self,
        clip_id: str,
        platforms: List[str]
    ) -> Dict[str, Any]:
        """Publish a live clip to social platforms."""
        # Find clip
        clip = None
        stream_id = None
        
        for sid, clips in self._extracted_clips.items():
            for c in clips:
                if c.clip_id == clip_id:
                    clip = c
                    stream_id = sid
                    break
            if clip:
                break
        
        if not clip:
            return {"error": "Clip not found"}
        
        # Publish to each platform
        results = {}
        
        for platform in platforms:
            try:
                # This would use the social integration service
                results[platform] = {"status": "published", "url": f"https://{platform}.com/clip/{clip_id}"}
            except Exception as e:
                results[platform] = {"status": "failed", "error": str(e)}
        
        clip.status = "published"
        
        return {
            "clip_id": clip_id,
            "published_to": results,
            "viral_score": clip.viral_score
        }
    
    def get_active_streams(self) -> List[Dict[str, Any]]:
        """Get list of all active streams."""
        return [
            {
                "stream_id": sid,
                "platform": cfg.platform,
                "status": self._stream_status.get(sid, StreamStatus.IDLE).value,
                "clips_count": len(self._extracted_clips.get(sid, []))
            }
            for sid, cfg in self._active_streams.items()
        ]


# Global instance
_live_service: Optional[LiveStreamService] = None


def get_live_stream_service() -> LiveStreamService:
    """Get global live stream service."""
    global _live_service
    if _live_service is None:
        _live_service = LiveStreamService()
    return _live_service


# Convenience functions
async def start_live_clip_extraction(
    stream_url: str,
    platform: str,
    stream_id: Optional[str] = None
) -> str:
    """Start extracting clips from a live stream."""
    import uuid
    
    sid = stream_id or f"stream_{uuid.uuid4().hex[:8]}"
    
    service = get_live_stream_service()
    await service.start_stream_monitoring(sid, stream_url, platform)
    
    return sid


async def create_live_clip(stream_id: str, duration: int = 30) -> Optional[LiveClip]:
    """Create a clip from active live stream."""
    service = get_live_stream_service()
    return await service.extract_clip(stream_id, duration, ClipTriggerType.MANUAL)
