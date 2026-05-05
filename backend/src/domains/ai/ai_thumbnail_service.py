"""
AI-Powered Thumbnail Generation Service
Automatically generates viral-optimized thumbnails from video clips.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import subprocess

logger = logging.getLogger(__name__)

def _get_ffmpeg_exe() -> str:
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg as _iio
        return _iio.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

class ThumbnailStyle(Enum):
    """Thumbnail style presets."""
    FACE_FOCUS = "face_focus"           # Close-up of speaker face
    ACTION_SHOT = "action_shot"         # Dynamic moment
    TEXT_OVERLAY = "text_overlay"       # With headline text
    SPLIT_SCREEN = "split_screen"       # Before/after or comparison
    MINIMAL = "minimal"                 # Clean and simple
    HIGH_CONTRAST = "high_contrast"     # Bold colors


@dataclass
class ThumbnailAnalysis:
    """Analysis of optimal thumbnail frame."""
    timestamp: float
    face_detected: bool
    face_position: Optional[Tuple[int, int, int, int]]  # x, y, w, h
    brightness_score: float
    contrast_score: float
    emotion_score: float
    clarity_score: float
    overall_score: float


@dataclass
class GeneratedThumbnail:
    """Generated thumbnail result."""
    thumbnail_id: str
    video_path: Path
    timestamp: float
    style: ThumbnailStyle
    output_path: Path
    dimensions: Tuple[int, int]
    file_size_kb: float
    quality_score: float
    viral_potential: float
    variants: List[Path]


class AIThumbnailService:
    """
    AI-powered thumbnail generation and optimization.
    """
    
    def __init__(self, output_dir: Path = Path("/app/temp/thumbnails")):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Style configurations
        self.style_configs = {
            ThumbnailStyle.FACE_FOCUS: {
                "crop_ratio": "9:16",
                "zoom": 1.3,
                "enhance_face": True,
                "add_border": False
            },
            ThumbnailStyle.ACTION_SHOT: {
                "crop_ratio": "16:9",
                "zoom": 1.0,
                "motion_blur": True,
                "saturation_boost": 1.2
            },
            ThumbnailStyle.TEXT_OVERLAY: {
                "crop_ratio": "9:16",
                "text_position": "bottom",
                "font_size": 48,
                "text_color": "#FFFFFF",
                "shadow": True
            },
            ThumbnailStyle.SPLIT_SCREEN: {
                "crop_ratio": "1:1",
                "split_type": "vertical",
                "border_width": 4
            },
            ThumbnailStyle.MINIMAL: {
                "crop_ratio": "9:16",
                "filters": ["smooth", "brightness_1.1"],
                "clean": True
            },
            ThumbnailStyle.HIGH_CONTRAST: {
                "crop_ratio": "9:16",
                "contrast": 1.3,
                "saturation": 1.2,
                "sharpness": 1.2
            }
        }
    
    async def analyze_optimal_frames(
        self,
        video_path: Path,
        num_frames: int = 10
    ) -> List[ThumbnailAnalysis]:
        """
        Analyze video to find optimal thumbnail frames.
        
        Args:
            video_path: Path to video file
            num_frames: Number of candidate frames to analyze
        """
        if not video_path.exists():
            return []
        
        # Get video duration
        duration = await self._get_video_duration(video_path)
        if not duration:
            return []
        
        # Sample frames throughout video
        timestamps = [duration * (i + 1) / (num_frames + 1) for i in range(num_frames)]
        
        analyses = []
        
        for ts in timestamps:
            try:
                # Extract frame
                frame_path = await self._extract_frame(video_path, ts)
                
                if frame_path:
                    # Analyze frame
                    analysis = await self._analyze_frame(frame_path, ts)
                    analyses.append(analysis)
                    
                    # Clean up temp frame
                    frame_path.unlink(missing_ok=True)
                    
            except Exception as e:
                logger.warning(f"Failed to analyze frame at {ts}: {e}")
        
        # Sort by overall score
        analyses.sort(key=lambda x: x.overall_score, reverse=True)
        
        return analyses
    
    async def generate_thumbnail(
        self,
        video_path: Path,
        style: ThumbnailStyle = ThumbnailStyle.FACE_FOCUS,
        custom_text: Optional[str] = None,
        timestamp: Optional[float] = None
    ) -> Optional[GeneratedThumbnail]:
        """
        Generate optimized thumbnail from video.
        
        Args:
            video_path: Source video path
            style: Thumbnail style preset
            custom_text: Optional text overlay
            timestamp: Specific timestamp, or None for auto-selection
        """
        if not video_path.exists():
            return None
        
        import uuid
        
        thumbnail_id = str(uuid.uuid4())[:8]
        
        # Find optimal timestamp if not provided
        if timestamp is None:
            analyses = await self.analyze_optimal_frames(video_path)
            if analyses:
                timestamp = analyses[0].timestamp
            else:
                # Default to 1 second in
                timestamp = 1.0
        
        # Extract frame at timestamp
        frame_path = await self._extract_frame(video_path, timestamp, high_quality=True)
        
        if not frame_path:
            return None
        
        try:
            # Apply style transformations
            output_path = self.output_dir / f"thumb_{thumbnail_id}.jpg"
            
            success = await self._apply_style(
                frame_path,
                output_path,
                style,
                custom_text
            )
            
            if not success:
                return None
            
            # Get file info
            file_size = output_path.stat().st_size / 1024  # KB
            
            # Generate variants
            variants = await self._generate_variants(
                frame_path,
                thumbnail_id,
                style
            )
            
            # Calculate scores
            quality_score = await self._calculate_quality_score(output_path)
            viral_potential = self._estimate_viral_potential(style, quality_score)
            
            # Clean up temp frame
            frame_path.unlink(missing_ok=True)
            
            return GeneratedThumbnail(
                thumbnail_id=thumbnail_id,
                video_path=video_path,
                timestamp=timestamp,
                style=style,
                output_path=output_path,
                dimensions=(1080, 1920),  # 9:16 vertical
                file_size_kb=file_size,
                quality_score=quality_score,
                viral_potential=viral_potential,
                variants=variants
            )
            
        except Exception as e:
            logger.error(f"Thumbnail generation failed: {e}")
            return None
    
    async def _get_video_duration(self, video_path: Path) -> Optional[float]:
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
                timeout=10
            )
            return float(result.stdout.strip())
        except:
            return None
    
    async def _extract_frame(
        self,
        video_path: Path,
        timestamp: float,
        high_quality: bool = False
    ) -> Optional[Path]:
        """Extract frame at specific timestamp."""
        import uuid
        
        frame_path = self.output_dir / f"frame_{uuid.uuid4().hex[:8]}.png"
        
        quality_args = ["-q:v", "2"] if high_quality else ["-q:v", "5"]
        
        try:
            subprocess.run(
                [
                    _get_ffmpeg_exe(), "-y",
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-vframes", "1",
                    *quality_args,
                    str(frame_path)
                ],
                capture_output=True,
                timeout=30
            )
            
            if frame_path.exists():
                return frame_path
            
        except Exception as e:
            logger.warning(f"Frame extraction failed: {e}")
        
        return None
    
    async def _analyze_frame(
        self,
        frame_path: Path,
        timestamp: float
    ) -> ThumbnailAnalysis:
        """Analyze frame quality for thumbnail suitability."""
        # Placeholder analysis - production would use CV/ML
        
        # Simulate analysis based on file properties
        import os
        
        stat = frame_path.stat()
        
        # Larger files often have more detail
        brightness_score = min(1.0, stat.st_size / (1024 * 1024 * 2))
        contrast_score = 0.7  # Assume decent contrast
        clarity_score = min(1.0, stat.st_size / (1024 * 1024))
        
        # Assume no face detection for now
        face_detected = False
        face_position = None
        emotion_score = 0.5
        
        # Calculate overall score
        overall = (
            brightness_score * 0.2 +
            contrast_score * 0.2 +
            clarity_score * 0.3 +
            emotion_score * 0.3
        )
        
        return ThumbnailAnalysis(
            timestamp=timestamp,
            face_detected=face_detected,
            face_position=face_position,
            brightness_score=brightness_score,
            contrast_score=contrast_score,
            emotion_score=emotion_score,
            clarity_score=clarity_score,
            overall_score=overall
        )
    
    async def _apply_style(
        self,
        input_path: Path,
        output_path: Path,
        style: ThumbnailStyle,
        custom_text: Optional[str]
    ) -> bool:
        """Apply style transformations to frame."""
        config = self.style_configs.get(style, {})
        
        # Build ImageMagick command
        cmd = ["convert", str(input_path)]
        
        # Apply filters based on style
        if style == ThumbnailStyle.HIGH_CONTRAST:
            cmd.extend([
                "-brightness-contrast", "0x30",
                "-modulate", "110",
                "-sharpen", "0x1"
            ])
        
        elif style == ThumbnailStyle.FACE_FOCUS:
            cmd.extend([
                "-gravity", "center",
                "-crop", "1080x1920+0+0",
                "+repage",
                "-resize", "1080x1920!"
            ])
        
        elif style == ThumbnailStyle.MINIMAL:
            cmd.extend([
                "-brightness-contrast", "10x0",
                "-blur", "0x0.5",
                "-sharpen", "0x0.5"
            ])
        
        # Resize to standard dimensions
        cmd.extend(["-resize", "1080x1920!"])
        
        # Add text overlay if provided
        if custom_text:
            cmd.extend([
                "-gravity", "south",
                "-pointsize", str(config.get("font_size", 48)),
                "-fill", config.get("text_color", "#FFFFFF"),
                "-stroke", "#000000",
                "-strokewidth", "2",
                "-annotate", "+0+100", custom_text
            ])
        
        # Output
        cmd.extend(["-quality", "95", str(output_path)])
        
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            return output_path.exists()
        except Exception as e:
            logger.error(f"Style application failed: {e}")
            return False
    
    async def _generate_variants(
        self,
        frame_path: Path,
        thumbnail_id: str,
        base_style: ThumbnailStyle
    ) -> List[Path]:
        """Generate style variants of thumbnail."""
        variants = []
        
        # Generate 2-3 variants with different styles
        variant_styles = [ThumbnailStyle.MINIMAL, ThumbnailStyle.HIGH_CONTRAST]
        
        for i, style in enumerate(variant_styles):
            if style == base_style:
                continue
            
            variant_path = self.output_dir / f"thumb_{thumbnail_id}_v{i}.jpg"
            
            success = await self._apply_style(frame_path, variant_path, style, None)
            
            if success:
                variants.append(variant_path)
        
        return variants
    
    async def _calculate_quality_score(self, thumbnail_path: Path) -> float:
        """Calculate quality score of generated thumbnail."""
        try:
            # Use file size as proxy for quality
            size_kb = thumbnail_path.stat().st_size / 1024
            
            # Optimal size: 100-500 KB
            if 100 <= size_kb <= 500:
                return 0.9
            elif size_kb < 100:
                return max(0.5, size_kb / 100)
            else:
                return max(0.7, 1.0 - ((size_kb - 500) / 1000))
                
        except:
            return 0.7
    
    def _estimate_viral_potential(
        self,
        style: ThumbnailStyle,
        quality_score: float
    ) -> float:
        """Estimate viral potential of thumbnail style."""
        # Style effectiveness scores
        style_scores = {
            ThumbnailStyle.FACE_FOCUS: 0.85,
            ThumbnailStyle.HIGH_CONTRAST: 0.80,
            ThumbnailStyle.TEXT_OVERLAY: 0.75,
            ThumbnailStyle.ACTION_SHOT: 0.70,
            ThumbnailStyle.MINIMAL: 0.65,
            ThumbnailStyle.SPLIT_SCREEN: 0.60
        }
        
        style_score = style_scores.get(style, 0.7)
        
        # Combine with quality
        return (style_score * 0.6) + (quality_score * 0.4)
    
    async def batch_generate_thumbnails(
        self,
        clips: List[Path],
        style: ThumbnailStyle = ThumbnailStyle.FACE_FOCUS
    ) -> List[GeneratedThumbnail]:
        """Generate thumbnails for multiple clips."""
        results = []
        
        for clip in clips:
            thumbnail = await self.generate_thumbnail(clip, style)
            if thumbnail:
                results.append(thumbnail)
        
        return results
    
    def get_thumbnail_recommendations(self, niche: str) -> List[ThumbnailStyle]:
        """Get recommended thumbnail styles for a niche."""
        recommendations = {
            "gaming": [ThumbnailStyle.ACTION_SHOT, ThumbnailStyle.HIGH_CONTRAST],
            "education": [ThumbnailStyle.FACE_FOCUS, ThumbnailStyle.TEXT_OVERLAY],
            "fitness": [ThumbnailStyle.ACTION_SHOT, ThumbnailStyle.FACE_FOCUS],
            "cooking": [ThumbnailStyle.MINIMAL, ThumbnailStyle.HIGH_CONTRAST],
            "comedy": [ThumbnailStyle.FACE_FOCUS, ThumbnailStyle.SPLIT_SCREEN],
            "tech": [ThumbnailStyle.MINIMAL, ThumbnailStyle.TEXT_OVERLAY]
        }
        
        return recommendations.get(niche.lower(), [ThumbnailStyle.FACE_FOCUS, ThumbnailStyle.MINIMAL])


# Global instance
_thumbnail_service: Optional[AIThumbnailService] = None


def get_thumbnail_service() -> AIThumbnailService:
    """Get global thumbnail service."""
    global _thumbnail_service
    if _thumbnail_service is None:
        _thumbnail_service = AIThumbnailService()
    return _thumbnail_service


# Convenience functions
async def generate_clip_thumbnail(
    clip_path: Path,
    style: str = "face_focus",
    custom_text: Optional[str] = None
) -> Optional[GeneratedThumbnail]:
    """Generate thumbnail for a clip."""
    service = get_thumbnail_service()
    style_enum = ThumbnailStyle(style) if style in [s.value for s in ThumbnailStyle] else ThumbnailStyle.FACE_FOCUS
    return await service.generate_thumbnail(clip_path, style_enum, custom_text)


def get_recommended_thumbnail_styles(niche: str) -> List[str]:
    """Get recommended thumbnail styles for niche."""
    styles = get_thumbnail_service().get_thumbnail_recommendations(niche)
    return [s.value for s in styles]
