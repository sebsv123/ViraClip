"""
Scene Detection and Automatic Cut Detection Service
Automatically detects scene changes and optimal cut points in video.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from ..constants import FFPROBE_TIMEOUT, DEFAULT_SCENE_LENGTH
import subprocess
import numpy as np

logger = logging.getLogger(__name__)


class SceneChangeType(Enum):
    """Types of scene changes."""
    CUT = "cut"           # Hard cut
    FADE = "fade"         # Fade transition
    DISSOLVE = "dissolve"  # Cross dissolve
    WIPE = "wipe"         # Wipe transition
    GRADUAL = "gradual"   # Gradual change


@dataclass
class SceneSegment:
    """Detected scene segment."""
    start_time: float
    end_time: float
    duration: float
    scene_id: int
    change_type: Optional[SceneChangeType]
    visual_hash: str  # For similarity comparison
    keyframe_path: Optional[Path]


@dataclass
class CutPoint:
    """Optimal cut point for clip extraction."""
    timestamp: float
    confidence: float
    cut_type: str  # "scene_change", "audio_pause", "motion_break"
    visual_score: float
    audio_score: float
    context_score: float  # Based on transcript/sentiment


class SceneDetectionService:
    """
    Automatic scene detection and cut point identification.
    """
    
    def __init__(self):
        self._scene_threshold = 0.3  # Threshold for scene change detection
        self._min_scene_duration = 2.0  # Minimum seconds per scene
    
    async def detect_scenes(
        self,
        video_path: Path,
        method: str = "content"
    ) -> List[SceneSegment]:
        """
        Detect scene changes in video.
        
        Args:
            video_path: Path to video file
            method: Detection method (content, threshold, histogram)
        """
        if not video_path.exists():
            return []
        
        # Use ffmpeg scene detection
        scenes = await self._detect_with_ffmpeg(video_path)
        
        if not scenes:
            # Fallback: divide into equal segments
            duration = await self._get_video_duration(video_path)
            scenes = self._create_uniform_segments(duration)
        
        return scenes
    
    async def _detect_with_ffmpeg(self, video_path: Path) -> List[SceneSegment]:
        """Detect scenes using ffmpeg."""
        try:
            # Run ffmpeg scene detection
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i", str(video_path),
                    "-vf", f"select='gt(scene,{self._scene_threshold})',showinfo",
                    "-f", "null",
                    "-"
                ],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            # Parse output for scene changes
            scenes = []
            current_time = 0.0
            scene_id = 0
            
            # Parse stderr for scene change timestamps
            for line in result.stderr.split('\n'):
                if 'pts_time:' in line:
                    # Extract timestamp
                    try:
                        time_str = line.split('pts_time:')[1].split()[0]
                        timestamp = float(time_str)
                        
                        # Create scene segment
                        if timestamp > current_time + self._min_scene_duration:
                            segment = SceneSegment(
                                start_time=current_time,
                                end_time=timestamp,
                                duration=timestamp - current_time,
                                scene_id=scene_id,
                                change_type=SceneChangeType.CUT,
                                visual_hash="",
                                keyframe_path=None
                            )
                            scenes.append(segment)
                            
                            current_time = timestamp
                            scene_id += 1
                    except (ValueError, IndexError, KeyError) as e:
                        # FIX: Skip malformed scene data but log it
                        logger.debug(f"Skipping malformed scene data: {e}")
                        continue
                    except Exception as e:
                        # FIX: Log unexpected errors
                        logger.warning(f"Unexpected error parsing scene: {e}")
                        continue
            
            # Add final segment
            duration = await self._get_video_duration(video_path)
            if current_time < duration:
                scenes.append(SceneSegment(
                    start_time=current_time,
                    end_time=duration,
                    duration=duration - current_time,
                    scene_id=scene_id,
                    change_type=None,
                    visual_hash="",
                    keyframe_path=None
                ))
            
            return scenes
            
        except Exception as e:
            logger.error(f"Scene detection failed: {e}")
            return []
    
    async def _get_video_duration(self, video_path: Path) -> float:
        """Get video duration in seconds."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(video_path)
                ],
                capture_output=True,
                text=True,
                timeout=FFPROBE_TIMEOUT
            )
            return float(result.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired) as e:
            # FIX: Expected errors (invalid duration, timeout)
            logger.debug(f"Failed to get duration: {e}")
            return 0.0
        except Exception as e:
            # FIX: Unexpected errors
            logger.warning(f"Unexpected error getting duration: {e}")
            return 0.0
    
    def _create_uniform_segments(self, duration: float, segment_length: float = DEFAULT_SCENE_LENGTH) -> List[SceneSegment]:
        """Create uniform segments as fallback."""
        segments = []
        num_segments = int(duration / segment_length)
        
        for i in range(num_segments):
            start = i * segment_length
            end = min((i + 1) * segment_length, duration)
            
            segments.append(SceneSegment(
                start_time=start,
                end_time=end,
                duration=end - start,
                scene_id=i,
                change_type=None,
                visual_hash="",
                keyframe_path=None
            ))
        
        return segments
    
    async def find_optimal_cut_points(
        self,
        video_path: Path,
        transcript_segments: Optional[List[Dict[str, Any]]] = None,
        audio_pauses: Optional[List[Tuple[float, float]]] = None
    ) -> List[CutPoint]:
        """
        Find optimal cut points combining visual and audio analysis.
        
        Args:
            video_path: Video file path
            transcript_segments: Transcript with timestamps
            audio_pauses: Detected audio pause regions
        """
        cut_points = []
        
        # Get scene changes
        scenes = await self.detect_scenes(video_path)
        
        # Add scene boundaries as cut points
        for scene in scenes[:-1]:  # Exclude last scene end
            cut_points.append(CutPoint(
                timestamp=scene.end_time,
                confidence=0.8,
                cut_type="scene_change",
                visual_score=0.8,
                audio_score=0.0,
                context_score=0.0
            ))
        
        # Add audio pause points
        if audio_pauses:
            for pause_start, pause_end in audio_pauses:
                # Use middle of pause
                cut_time = (pause_start + pause_end) / 2
                cut_points.append(CutPoint(
                    timestamp=cut_time,
                    confidence=0.6,
                    cut_type="audio_pause",
                    visual_score=0.0,
                    audio_score=0.7,
                    context_score=0.0
                ))
        
        # Add transcript-based cuts (at sentence boundaries)
        if transcript_segments:
            for segment in transcript_segments:
                end_time = segment.get("end", 0)
                text = segment.get("text", "")
                
                # Check if segment ends with sentence terminator
                if text.rstrip().endswith(('.', '!', '?')):
                    cut_points.append(CutPoint(
                        timestamp=end_time,
                        confidence=0.7,
                        cut_type="sentence_boundary",
                        visual_score=0.0,
                        audio_score=0.0,
                        context_score=0.8
                    ))
        
        # Sort by timestamp and remove duplicates
        cut_points.sort(key=lambda x: x.timestamp)
        
        # Merge close points
        merged = self._merge_close_points(cut_points, min_distance=1.0)
        
        # Score and rank
        scored = self._score_cut_points(merged)
        
        return scored
    
    def _merge_close_points(
        self,
        points: List[CutPoint],
        min_distance: float
    ) -> List[CutPoint]:
        """Merge cut points that are too close together."""
        if not points:
            return []
        
        merged = [points[0]]
        
        for point in points[1:]:
            if point.timestamp - merged[-1].timestamp < min_distance:
                # Keep the higher confidence one
                if point.confidence > merged[-1].confidence:
                    merged[-1] = point
            else:
                merged.append(point)
        
        return merged
    
    def _score_cut_points(self, points: List[CutPoint]) -> List[CutPoint]:
        """Score and rank cut points."""
        for point in points:
            # Calculate composite score
            composite = (
                point.visual_score * 0.4 +
                point.audio_score * 0.3 +
                point.context_score * 0.3
            )
            
            # Boost confidence based on composite
            point.confidence = min(1.0, point.confidence + composite * 0.2)
        
        # Sort by confidence
        return sorted(points, key=lambda x: x.confidence, reverse=True)
    
    async def extract_keyframes(
        self,
        video_path: Path,
        timestamps: List[float]
    ) -> List[Path]:
        """Extract keyframe images at specified timestamps."""
        keyframes = []
        
        for ts in timestamps:
            try:
                import uuid
                output_path = Path(f"/tmp/keyframe_{uuid.uuid4().hex}.jpg")
                
                subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-ss", str(ts),
                        "-i", str(video_path),
                        "-vframes", "1",
                        "-q:v", "2",
                        str(output_path)
                    ],
                    capture_output=True,
                    timeout=30
                )
                
                if output_path.exists():
                    keyframes.append(output_path)
                    
            except Exception as e:
                logger.warning(f"Keyframe extraction failed at {ts}: {e}")
        
        return keyframes
    
    def suggest_clip_boundaries(
        self,
        cut_points: List[CutPoint],
        target_duration: float = 30.0,
        max_clips: int = 5
    ) -> List[Tuple[float, float]]:
        """Suggest optimal clip boundaries based on cut points."""
        if not cut_points:
            return []
        
        # Sort by timestamp
        sorted_points = sorted(cut_points, key=lambda x: x.timestamp)
        
        # Generate clip suggestions
        suggestions = []
        
        # Start from beginning
        current_start = 0.0
        
        for point in sorted_points:
            duration = point.timestamp - current_start
            
            if duration >= target_duration * 0.8:  # Within 80% of target
                suggestions.append((current_start, point.timestamp))
                current_start = point.timestamp
                
                if len(suggestions) >= max_clips:
                    break
        
        return suggestions
    
    def get_scene_statistics(self, scenes: List[SceneSegment]) -> Dict[str, Any]:
        """Get statistics about detected scenes."""
        if not scenes:
            return {}
        
        durations = [s.duration for s in scenes]
        
        return {
            "total_scenes": len(scenes),
            "total_duration": sum(durations),
            "avg_scene_duration": np.mean(durations),
            "shortest_scene": min(durations),
            "longest_scene": max(durations),
            "scene_changes": len([s for s in scenes if s.change_type is not None])
        }


# Global instance
_scene_service: Optional[SceneDetectionService] = None


def get_scene_detection_service() -> SceneDetectionService:
    """Get global scene detection service."""
    global _scene_service
    if _scene_service is None:
        _scene_service = SceneDetectionService()
    return _scene_service


# Convenience functions
async def detect_video_scenes(video_path: Path) -> List[SceneSegment]:
    """Detect scenes in video."""
    return await get_scene_detection_service().detect_scenes(video_path)


async def find_cut_points(video_path: Path, transcript: Optional[List] = None) -> List[CutPoint]:
    """Find optimal cut points."""
    return await get_scene_detection_service().find_optimal_cut_points(video_path, transcript)
