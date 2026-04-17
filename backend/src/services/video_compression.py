"""
Video Compression Optimization Service
Advanced video compression with quality preservation and format optimization.
"""

import subprocess
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class CompressionPreset(Enum):
    """Compression quality presets."""
    ULTRA = "ultra"      # Minimal compression, highest quality
    HIGH = "high"        # Good quality, moderate compression
    BALANCED = "balanced"  # Default balance
    COMPACT = "compact"  # Smaller file, acceptable quality
    AGGRESSIVE = "aggressive"  # Maximum compression


class VideoCodec(Enum):
    """Supported video codecs."""
    H264 = "libx264"
    H265 = "libx265"
    VP9 = "libvpx-vp9"
    AV1 = "libaom-av1"


@dataclass
class CompressionProfile:
    """Compression profile configuration."""
    preset: CompressionPreset
    codec: VideoCodec
    crf: int  # Constant Rate Factor (0-51, lower is better)
    bitrate: Optional[str]
    max_file_size_mb: Optional[float]
    target_quality_score: float  # 0-100
    preserve_resolution: bool
    audio_codec: str
    audio_bitrate: str


@dataclass
class CompressionResult:
    """Result of video compression."""
    success: bool
    input_path: Path
    output_path: Path
    input_size_mb: float
    output_size_mb: float
    compression_ratio: float
    space_saved_mb: float
    quality_score: float
    duration_seconds: float
    error_message: Optional[str]


class VideoCompressionService:
    """
    Intelligent video compression with quality analysis.
    """
    
    # Preset configurations
    PRESET_CONFIGS = {
        CompressionPreset.ULTRA: CompressionProfile(
            preset=CompressionPreset.ULTRA,
            codec=VideoCodec.H264,
            crf=18,
            bitrate=None,
            max_file_size_mb=None,
            target_quality_score=95,
            preserve_resolution=True,
            audio_codec="aac",
            audio_bitrate="192k"
        ),
        CompressionPreset.HIGH: CompressionProfile(
            preset=CompressionPreset.HIGH,
            codec=VideoCodec.H264,
            crf=23,
            bitrate=None,
            max_file_size_mb=None,
            target_quality_score=90,
            preserve_resolution=True,
            audio_codec="aac",
            audio_bitrate="128k"
        ),
        CompressionPreset.BALANCED: CompressionProfile(
            preset=CompressionPreset.BALANCED,
            codec=VideoCodec.H264,
            crf=28,
            bitrate="8M",
            max_file_size_mb=50,
            target_quality_score=80,
            preserve_resolution=True,
            audio_codec="aac",
            audio_bitrate="128k"
        ),
        CompressionPreset.COMPACT: CompressionProfile(
            preset=CompressionPreset.COMPACT,
            codec=VideoCodec.H265,
            crf=30,
            bitrate="5M",
            max_file_size_mb=32,
            target_quality_score=70,
            preserve_resolution=False,
            audio_codec="aac",
            audio_bitrate="96k"
        ),
        CompressionPreset.AGGRESSIVE: CompressionProfile(
            preset=CompressionPreset.AGGRESSIVE,
            codec=VideoCodec.H265,
            crf=35,
            bitrate="2M",
            max_file_size_mb=16,
            target_quality_score=60,
            preserve_resolution=False,
            audio_codec="aac",
            audio_bitrate="64k"
        )
    }
    
    def __init__(self):
        self._history: List[CompressionResult] = []
    
    async def compress_clip(
        self,
        input_path: Path,
        output_path: Path,
        preset: CompressionPreset = CompressionPreset.BALANCED,
        target_platform: Optional[str] = None
    ) -> CompressionResult:
        """
        Compress a video clip with optimal settings.
        
        Args:
            input_path: Path to input video
            output_path: Path for output video
            preset: Compression quality preset
            target_platform: Target platform for optimization
        """
        if not input_path.exists():
            return CompressionResult(
                success=False,
                input_path=input_path,
                output_path=output_path,
                input_size_mb=0,
                output_size_mb=0,
                compression_ratio=0,
                space_saved_mb=0,
                quality_score=0,
                duration_seconds=0,
                error_message="Input file not found"
            )
        
        profile = self.PRESET_CONFIGS[preset]
        
        # Adjust for platform if specified
        if target_platform:
            profile = self._adjust_for_platform(profile, target_platform)
        
        input_size = input_path.stat().st_size / (1024 * 1024)
        
        try:
            # Build FFmpeg command
            cmd = self._build_ffmpeg_command(input_path, output_path, profile)
            
            # Execute compression
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode != 0:
                raise Exception(f"FFmpeg failed: {result.stderr}")
            
            # Analyze result
            output_size = output_path.stat().st_size / (1024 * 1024)
            duration = await self._get_video_duration(output_path)
            quality_score = self._estimate_quality_score(input_path, output_path, profile)
            
            compression_result = CompressionResult(
                success=True,
                input_path=input_path,
                output_path=output_path,
                input_size_mb=input_size,
                output_size_mb=output_size,
                compression_ratio=input_size / max(output_size, 0.001),
                space_saved_mb=input_size - output_size,
                quality_score=quality_score,
                duration_seconds=duration,
                error_message=None
            )
            
            self._history.append(compression_result)
            
            logger.info(
                f"Compressed {input_path.name}: {input_size:.1f}MB -> {output_size:.1f}MB "
                f"({compression_result.compression_ratio:.1f}x, quality: {quality_score:.0f}%)"
            )
            
            return compression_result
            
        except Exception as e:
            logger.error(f"Compression failed: {e}")
            
            return CompressionResult(
                success=False,
                input_path=input_path,
                output_path=output_path,
                input_size_mb=input_size,
                output_size_mb=0,
                compression_ratio=0,
                space_saved_mb=0,
                quality_score=0,
                duration_seconds=0,
                error_message=str(e)
            )
    
    def _build_ffmpeg_command(
        self,
        input_path: Path,
        output_path: Path,
        profile: CompressionProfile
    ) -> List[str]:
        """Build FFmpeg command for compression."""
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-i", str(input_path),
            "-c:v", profile.codec.value,
            "-crf", str(profile.crf),
            "-preset", "medium",  # Encoding speed preset
            "-c:a", profile.audio_codec,
            "-b:a", profile.audio_bitrate,
            "-movflags", "+faststart",  # Web optimization
            "-pix_fmt", "yuv420p",  # Compatibility
        ]
        
        # Add bitrate if specified
        if profile.bitrate:
            cmd.extend(["-b:v", profile.bitrate])
        
        # Add max file size constraint
        if profile.max_file_size_mb:
            max_bits = int(profile.max_file_size_mb * 8 * 1024 * 1024)
            cmd.extend(["-fs", str(max_bits)])
        
        # Add output path
        cmd.append(str(output_path))
        
        return cmd
    
    def _adjust_for_platform(
        self,
        profile: CompressionProfile,
        platform: str
    ) -> CompressionProfile:
        """Adjust profile for specific platform requirements."""
        platform_limits = {
            "tiktok": {"max_size": 287, "max_duration": 180},
            "youtube_shorts": {"max_size": 256, "max_duration": 60},
            "instagram_reels": {"max_size": 100, "max_duration": 90},
            "twitter": {"max_size": 512, "max_duration": 140},
        }
        
        limits = platform_limits.get(platform.lower())
        if not limits:
            return profile
        
        # Adjust if needed
        adjusted = CompressionProfile(
            preset=profile.preset,
            codec=profile.codec,
            crf=profile.crf,
            bitrate=profile.bitrate,
            max_file_size_mb=min(profile.max_file_size_mb or float('inf'), limits["max_size"]),
            target_quality_score=profile.target_quality_score,
            preserve_resolution=profile.preserve_resolution,
            audio_codec=profile.audio_codec,
            audio_bitrate=profile.audio_bitrate
        )
        
        return adjusted
    
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
                text=True
            )
            return float(result.stdout.strip())
        except:
            return 0.0
    
    def _estimate_quality_score(
        self,
        input_path: Path,
        output_path: Path,
        profile: CompressionProfile
    ) -> float:
        """Estimate quality score after compression."""
        # Get file sizes
        input_size = input_path.stat().st_size
        output_size = output_path.stat().st_size
        
        # Calculate size ratio
        size_ratio = output_size / max(input_size, 1)
        
        # Base quality from CRF
        crf_quality = max(0, min(100, 100 - (profile.crf * 2)))
        
        # Adjust based on size ratio
        # Smaller files may have lost more quality
        if size_ratio < 0.3:  # Less than 30% of original
            size_penalty = (0.3 - size_ratio) * 50
        else:
            size_penalty = 0
        
        quality = max(0, crf_quality - size_penalty)
        
        return min(100, quality)
    
    async def optimize_for_platform(
        self,
        input_path: Path,
        platform: str,
        output_dir: Path
    ) -> CompressionResult:
        """
        Compress video specifically for a platform.
        
        Automatically selects best settings for the target platform.
        """
        # Generate output filename
        output_path = output_dir / f"{input_path.stem}_{platform}{input_path.suffix}"
        
        # Select preset based on platform
        preset_map = {
            "tiktok": CompressionPreset.BALANCED,
            "youtube_shorts": CompressionPreset.HIGH,
            "instagram_reels": CompressionPreset.BALANCED,
            "facebook": CompressionPreset.BALANCED,
            "twitter": CompressionPreset.COMPACT,
            "linkedin": CompressionPreset.HIGH
        }
        
        preset = preset_map.get(platform.lower(), CompressionPreset.BALANCED)
        
        return await self.compress_clip(input_path, output_path, preset, platform)
    
    async def batch_compress(
        self,
        clips: List[Path],
        output_dir: Path,
        preset: CompressionPreset = CompressionPreset.BALANCED
    ) -> List[CompressionResult]:
        """Compress multiple clips."""
        results = []
        
        for clip in clips:
            output_path = output_dir / f"compressed_{clip.name}"
            result = await self.compress_clip(clip, output_path, preset)
            results.append(result)
        
        return results
    
    def get_compression_stats(self) -> Dict[str, Any]:
        """Get compression statistics."""
        if not self._history:
            return {"total_compressed": 0}
        
        successful = [r for r in self._history if r.success]
        
        if not successful:
            return {
                "total_compressed": len(self._history),
                "successful": 0,
                "failed": len(self._history)
            }
        
        total_input = sum(r.input_size_mb for r in successful)
        total_output = sum(r.output_size_mb for r in successful)
        total_saved = sum(r.space_saved_mb for r in successful)
        
        return {
            "total_compressed": len(self._history),
            "successful": len(successful),
            "failed": len(self._history) - len(successful),
            "total_input_mb": total_input,
            "total_output_mb": total_output,
            "total_saved_mb": total_saved,
            "avg_compression_ratio": total_input / max(total_output, 0.001),
            "avg_quality_score": sum(r.quality_score for r in successful) / len(successful),
            "best_compression": max((r.compression_ratio for r in successful), default=0),
            "worst_quality": min((r.quality_score for r in successful), default=100)
        }
    
    def recommend_preset(self, video_path: Path, target_size_mb: Optional[float] = None) -> CompressionPreset:
        """Recommend compression preset based on video and requirements."""
        if not video_path.exists():
            return CompressionPreset.BALANCED
        
        current_size = video_path.stat().st_size / (1024 * 1024)
        
        # If target size specified
        if target_size_mb:
            ratio_needed = target_size_mb / current_size
            
            if ratio_needed < 0.2:
                return CompressionPreset.AGGRESSIVE
            elif ratio_needed < 0.5:
                return CompressionPreset.COMPACT
            elif ratio_needed < 0.8:
                return CompressionPreset.BALANCED
            else:
                return CompressionPreset.HIGH
        
        # Based on current size
        if current_size > 100:  # Large file
            return CompressionPreset.COMPACT
        elif current_size > 50:
            return CompressionPreset.BALANCED
        else:
            return CompressionPreset.HIGH


# Global instance
_compression_service: Optional[VideoCompressionService] = None


def get_compression_service() -> VideoCompressionService:
    """Get global compression service."""
    global _compression_service
    if _compression_service is None:
        _compression_service = VideoCompressionService()
    return _compression_service


# Convenience functions
async def compress_video(
    input_path: Path,
    output_path: Path,
    quality: str = "balanced"
) -> CompressionResult:
    """Compress a video with specified quality."""
    preset = CompressionPreset(quality) if quality in [p.value for p in CompressionPreset] else CompressionPreset.BALANCED
    return await get_compression_service().compress_clip(input_path, output_path, preset)


def get_compression_recommendation(video_path: Path, target_size_mb: Optional[float] = None) -> str:
    """Get recommended compression preset."""
    preset = get_compression_service().recommend_preset(video_path, target_size_mb)
    return preset.value
