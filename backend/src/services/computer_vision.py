"""
Computer Vision Analysis Service
Visual analysis of video content for engagement optimization.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import subprocess

from ..constants import FFPROBE_TIMEOUT

logger = logging.getLogger(__name__)


class VisualElement(Enum):
    """Visual elements detectable in video."""
    FACE = "face"
    TEXT = "text"
    LOGO = "logo"
    OBJECT = "object"
    SCENE = "scene"
    MOTION = "motion"


@dataclass
class VisualAnalysis:
    """Visual analysis result for a frame."""
    timestamp: float
    faces: List[Dict[str, Any]]  # position, size, emotion
    text_regions: List[Dict[str, Any]]  # OCR results
    dominant_colors: List[Tuple[int, int, int]]
    brightness: float
    contrast: float
    sharpness: float
    motion_score: float
    engagement_prediction: float


@dataclass
class FaceData:
    """Detected face information."""
    x: int
    y: int
    width: int
    height: int
    confidence: float
    emotion: Optional[str]
    looking_at_camera: bool


class ComputerVisionService:
    """
    Computer vision analysis for video content.
    """
    
    def __init__(self):
        self._analysis_cache: Dict[str, List[VisualAnalysis]] = {}
    
    async def analyze_video_visuals(
        self,
        video_path: Path,
        sample_interval: float = 1.0
    ) -> List[VisualAnalysis]:
        """
        Analyze visual elements throughout video.
        
        Args:
            video_path: Path to video file
            sample_interval: Seconds between analysis samples
        """
        if not video_path.exists():
            return []
        
        # Get video duration
        duration = await self._get_duration(video_path)
        if not duration:
            return []
        
        analyses = []
        
        # Sample frames throughout video
        timestamps = [i * sample_interval for i in range(int(duration / sample_interval))]
        
        for ts in timestamps:
            try:
                analysis = await self._analyze_frame_at(video_path, ts)
                if analysis:
                    analyses.append(analysis)
            except Exception as e:
                logger.warning(f"Frame analysis failed at {ts}s: {e}")
        
        # Cache results
        cache_key = str(video_path)
        self._analysis_cache[cache_key] = analyses
        
        return analyses
    
    async def _get_duration(self, video_path: Path) -> Optional[float]:
        """Get video duration."""
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
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            # FIX: Expected errors - video might not have duration metadata
            logger.debug(f"Failed to get frame time: {e}")
            return None
        except Exception as e:
            # FIX: Unexpected errors
            logger.warning(f"Unexpected error getting frame time: {e}")
            return None
    
    async def _analyze_frame_at(
        self,
        video_path: Path,
        timestamp: float
    ) -> Optional[VisualAnalysis]:
        """Analyze single frame at timestamp."""
        # Extract frame
        frame_path = await self._extract_frame(video_path, timestamp)
        
        if not frame_path:
            return None
        
        try:
            # Analyze frame
            faces = await self._detect_faces(frame_path)
            text_regions = await self._detect_text(frame_path)
            colors = await self._extract_colors(frame_path)
            brightness = await self._calculate_brightness(frame_path)
            contrast = await self._calculate_contrast(frame_path)
            sharpness = await self._calculate_sharpness(frame_path)
            
            # Calculate motion (compare with previous if available)
            motion_score = 0.5  # Placeholder
            
            # Predict engagement based on visual elements
            engagement = self._predict_engagement(
                len(faces), brightness, contrast, sharpness, motion_score
            )
            
            # Cleanup
            frame_path.unlink(missing_ok=True)
            
            return VisualAnalysis(
                timestamp=timestamp,
                faces=[f.__dict__ for f in faces],
                text_regions=text_regions,
                dominant_colors=colors[:5],
                brightness=brightness,
                contrast=contrast,
                sharpness=sharpness,
                motion_score=motion_score,
                engagement_prediction=engagement
            )
            
        except Exception as e:
            logger.error(f"Frame analysis error: {e}")
            frame_path.unlink(missing_ok=True)
            return None
    
    async def _extract_frame(
        self,
        video_path: Path,
        timestamp: float
    ) -> Optional[Path]:
        """Extract frame at timestamp."""
        import uuid
        
        frame_path = Path(f"/tmp/frame_{uuid.uuid4().hex}.png")
        
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-q:v", "2",
                    str(frame_path)
                ],
                capture_output=True,
                timeout=30
            )
            
            return frame_path if frame_path.exists() else None
            
        except Exception as e:
            logger.error(f"Frame extraction failed: {e}")
            return None
    
    async def _detect_faces(self, frame_path: Path) -> List[FaceData]:
        """Detect faces in frame."""
        # Placeholder - would use OpenCV or similar
        # Return simulated data
        return [
            FaceData(
                x=100, y=100, width=200, height=250,
                confidence=0.95, emotion="neutral", looking_at_camera=True
            )
        ]
    
    async def _detect_text(self, frame_path: Path) -> List[Dict[str, Any]]:
        """Detect text regions via OCR."""
        # Placeholder - would use Tesseract or cloud OCR
        return []
    
    async def _extract_colors(
        self,
        frame_path: Path,
        num_colors: int = 5
    ) -> List[Tuple[int, int, int]]:
        """Extract dominant colors from frame."""
        # Placeholder - would use color quantization
        return [
            (255, 100, 100),
            (100, 255, 100),
            (100, 100, 255)
        ]
    
    async def _calculate_brightness(self, frame_path: Path) -> float:
        """Calculate average brightness."""
        # Placeholder
        return 0.7
    
    async def _calculate_contrast(self, frame_path: Path) -> float:
        """Calculate contrast level."""
        # Placeholder
        return 0.6
    
    async def _calculate_sharpness(self, frame_path: Path) -> float:
        """Calculate image sharpness."""
        # Placeholder
        return 0.8
    
    def _predict_engagement(
        self,
        face_count: int,
        brightness: float,
        contrast: float,
        sharpness: float,
        motion: float
    ) -> float:
        """Predict engagement based on visual features."""
        # Simple scoring model
        score = 0.5
        
        # Faces increase engagement
        if face_count > 0:
            score += 0.2
        
        # Good brightness
        if 0.4 < brightness < 0.8:
            score += 0.1
        
        # Good contrast
        if contrast > 0.5:
            score += 0.1
        
        # Sharpness
        if sharpness > 0.6:
            score += 0.1
        
        # Motion
        if motion > 0.3:
            score += 0.1
        
        return min(1.0, score)
    
    def find_best_frames(
        self,
        video_path: Path,
        criteria: str = "engagement",
        count: int = 5
    ) -> List[float]:
        """Find best frames for thumbnails based on criteria."""
        cache_key = str(video_path)
        
        if cache_key not in self._analysis_cache:
            return []
        
        analyses = self._analysis_cache[cache_key]
        
        if criteria == "engagement":
            sorted_frames = sorted(
                analyses,
                key=lambda x: x.engagement_prediction,
                reverse=True
            )
        elif criteria == "brightness":
            sorted_frames = sorted(
                analyses,
                key=lambda x: x.brightness,
                reverse=True
            )
        else:
            sorted_frames = analyses
        
        return [a.timestamp for a in sorted_frames[:count]]
    
    def get_visual_summary(self, video_path: Path) -> Dict[str, Any]:
        """Get visual analysis summary."""
        cache_key = str(video_path)
        
        if cache_key not in self._analysis_cache:
            return {"error": "Video not analyzed"}
        
        analyses = self._analysis_cache[cache_key]
        
        if not analyses:
            return {"error": "No analysis data"}
        
        # Calculate averages
        avg_brightness = sum(a.brightness for a in analyses) / len(analyses)
        avg_contrast = sum(a.contrast for a in analyses) / len(analyses)
        avg_sharpness = sum(a.sharpness for a in analyses) / len(analyses)
        avg_engagement = sum(a.engagement_prediction for a in analyses) / len(analyses)
        
        # Count faces
        total_faces = sum(len(a.faces) for a in analyses)
        
        return {
            "total_frames_analyzed": len(analyses),
            "avg_brightness": avg_brightness,
            "avg_contrast": avg_contrast,
            "avg_sharpness": avg_sharpness,
            "avg_engagement_prediction": avg_engagement,
            "total_faces_detected": total_faces,
            "has_face_presence": total_faces > 0,
            "visual_quality_score": (avg_brightness + avg_contrast + avg_sharpness) / 3
        }


# Global instance
_cv_service: Optional[ComputerVisionService] = None


def get_computer_vision_service() -> ComputerVisionService:
    """Get global computer vision service."""
    global _cv_service
    if _cv_service is None:
        _cv_service = ComputerVisionService()
    return _cv_service


# Convenience functions
async def analyze_video_visuals(video_path: Path) -> List[VisualAnalysis]:
    """Analyze video visuals."""
    return await get_computer_vision_service().analyze_video_visuals(video_path)


def get_best_thumbnail_frames(video_path: Path, count: int = 5) -> List[float]:
    """Get best frames for thumbnails."""
    return get_computer_vision_service().find_best_frames(video_path, count=count)
