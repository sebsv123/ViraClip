"""
Platform Export Presets System
Optimized export settings for each social media platform.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from src import gpu_utils

logger = logging.getLogger(__name__)


class PlatformType(Enum):
    """Supported social media platforms."""
    TIKTOK = "tiktok"
    YOUTUBE_SHORTS = "youtube_shorts"
    INSTAGRAM_REELS = "instagram_reels"
    FACEBOOK_STORIES = "facebook_stories"
    SNAPCHAT = "snapchat"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"


@dataclass
class VideoSpecs:
    """Video technical specifications."""
    resolution: str  # e.g., "1080x1920"
    aspect_ratio: str  # e.g., "9:16"
    fps: int
    min_fps: int
    max_fps: int
    video_codec: str
    audio_codec: str
    video_bitrate: str
    audio_bitrate: str
    max_file_size_mb: int
    max_duration_sec: int
    recommended_duration_sec: int
    pixel_format: str


@dataclass
class PlatformPreset:
    """Complete preset for a platform."""
    platform: PlatformType
    name: str
    description: str
    specs: VideoSpecs
    safe_zones: Dict[str, int]  # pixels from edges
    caption_settings: Dict[str, Any]
    audio_settings: Dict[str, Any]
    thumbnail_specs: Optional[Dict[str, Any]]
    hashtag_limit: int
    caption_char_limit: int
    best_upload_times: List[str]
    engagement_tips: List[str]


class PlatformExportPresets:
    """
    Export presets optimized for each social platform.
    """
    
    PRESETS = {
        PlatformType.TIKTOK: PlatformPreset(
            platform=PlatformType.TIKTOK,
            name="TikTok Optimized",
            description="Maximum quality and engagement for TikTok",
            specs=VideoSpecs(
                resolution="1080x1920",
                aspect_ratio="9:16",
                fps=30,
                min_fps=24,
                max_fps=60,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="8M",
                audio_bitrate="192k",
                max_file_size_mb=287,
                max_duration_sec=180,
                recommended_duration_sec=21,
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 120,      # Status bar area
                "bottom": 280,   # UI controls area
                "left": 60,
                "right": 60
            },
            caption_settings={
                "position": "bottom",
                "safe_bottom_margin": 280,
                "font_size": 24,
                "max_lines": 3,
                "word_highlight": True,
                "allowed_chars": 2200
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -14,
                "voice_boost_db": 2,
                "music_duck_db": -12
            },
            thumbnail_specs={
                "resolution": "1080x1920",
                "aspect": "9:16",
                "format": "jpg"
            },
            hashtag_limit=10,
            caption_char_limit=2200,
            best_upload_times=[
                "Tuesday 09:00", "Thursday 12:00", "Friday 05:00",
                "Sunday 11:00", "Wednesday 14:00"
            ],
            engagement_tips=[
                "Post during off-peak hours for better visibility",
                "Use trending sounds and hashtags",
                "First 3 seconds are critical for retention",
                "Respond to comments within first hour"
            ]
        ),
        
        PlatformType.YOUTUBE_SHORTS: PlatformPreset(
            platform=PlatformType.YOUTUBE_SHORTS,
            name="YouTube Shorts Optimized",
            description="Optimized for YouTube Shorts algorithm",
            specs=VideoSpecs(
                resolution="1080x1920",
                aspect_ratio="9:16",
                fps=30,
                min_fps=24,
                max_fps=60,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="10M",  # Higher bitrate for YT
                audio_bitrate="192k",
                max_file_size_mb=256,
                max_duration_sec=60,
                recommended_duration_sec=58,  # Almost max
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 100,
                "bottom": 200,
                "left": 100,
                "right": 100
            },
            caption_settings={
                "position": "bottom",
                "safe_bottom_margin": 200,
                "font_size": 26,
                "max_lines": 2,
                "word_highlight": True,
                "allowed_chars": 100
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -14,
                "voice_boost_db": 1,
                "music_duck_db": -10
            },
            thumbnail_specs={
                "resolution": "1920x1080",
                "aspect": "16:9",
                "format": "jpg"
            },
            hashtag_limit=15,
            caption_char_limit=100,
            best_upload_times=[
                "Monday 14:00", "Tuesday 14:00", "Wednesday 12:00",
                "Friday 12:00", "Sunday 09:00"
            ],
            engagement_tips=[
                "Use Shorts-specific hashtags (#Shorts)",
                "Link to longer videos in comments",
                "Create series for binge-watching",
                "Hook must be in first 1 second"
            ]
        ),
        
        PlatformType.INSTAGRAM_REELS: PlatformPreset(
            platform=PlatformType.INSTAGRAM_REELS,
            name="Instagram Reels Optimized",
            description="Perfect for Instagram Reels engagement",
            specs=VideoSpecs(
                resolution="1080x1920",
                aspect_ratio="9:16",
                fps=30,
                min_fps=24,
                max_fps=60,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="6M",
                audio_bitrate="128k",
                max_file_size_mb=100,
                max_duration_sec=90,
                recommended_duration_sec=30,
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 150,      # Username area
                "bottom": 250,   # Controls + caption
                "left": 80,
                "right": 80
            },
            caption_settings={
                "position": "bottom",
                "safe_bottom_margin": 250,
                "font_size": 22,
                "max_lines": 2,
                "word_highlight": True,
                "allowed_chars": 2200
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -16,
                "voice_boost_db": 3,
                "music_duck_db": -15
            },
            thumbnail_specs={
                "resolution": "1080x1920",
                "aspect": "9:16",
                "format": "jpg"
            },
            hashtag_limit=30,
            caption_char_limit=2200,
            best_upload_times=[
                "Monday 06:00", "Tuesday 11:00", "Wednesday 14:00",
                "Friday 11:00", "Saturday 10:00"
            ],
            engagement_tips=[
                "Use 3-5 hashtags, mix popular and niche",
                "Post consistently (daily preferred)",
                "Use Reels-first audio when possible",
                "Collab with other creators"
            ]
        ),
        
        PlatformType.FACEBOOK_STORIES: PlatformPreset(
            platform=PlatformType.FACEBOOK_STORIES,
            name="Facebook Stories Optimized",
            description="Optimized for Facebook Stories",
            specs=VideoSpecs(
                resolution="1080x1920",
                aspect_ratio="9:16",
                fps=30,
                min_fps=24,
                max_fps=30,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="4M",
                audio_bitrate="128k",
                max_file_size_mb=50,
                max_duration_sec=60,
                recommended_duration_sec=20,
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 120,
                "bottom": 180,
                "left": 60,
                "right": 60
            },
            caption_settings={
                "position": "center",  # Stories allow center text
                "safe_bottom_margin": 180,
                "font_size": 28,
                "max_lines": 2,
                "word_highlight": False,
                "allowed_chars": 100
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -16,
                "voice_boost_db": 2,
                "music_duck_db": -10
            },
            thumbnail_specs=None,  # No thumbnails for stories
            hashtag_limit=10,
            caption_char_limit=100,
            best_upload_times=[
                "Tuesday 13:00", "Wednesday 13:00", "Thursday 09:00",
                "Friday 15:00", "Saturday 13:00"
            ],
            engagement_tips=[
                "Use stickers and polls for engagement",
                "Link to full content",
                "Stories disappear in 24h - use highlights",
                "Post at peak times for your audience"
            ]
        ),
        
        PlatformType.SNAPCHAT: PlatformPreset(
            platform=PlatformType.SNAPCHAT,
            name="Snapchat Spotlight Optimized",
            description="For Snapchat Spotlight and Stories",
            specs=VideoSpecs(
                resolution="1080x1920",
                aspect_ratio="9:16",
                fps=30,
                min_fps=24,
                max_fps=60,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="5M",
                audio_bitrate="128k",
                max_file_size_mb=32,
                max_duration_sec=60,
                recommended_duration_sec=15,
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 140,
                "bottom": 200,
                "left": 50,
                "right": 50
            },
            caption_settings={
                "position": "bottom",
                "safe_bottom_margin": 200,
                "font_size": 24,
                "max_lines": 2,
                "word_highlight": False,
                "allowed_chars": 100
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -16,
                "voice_boost_db": 4,  # Snapchat needs more boost
                "music_duck_db": -12
            },
            thumbnail_specs=None,
            hashtag_limit=5,
            caption_char_limit=100,
            best_upload_times=[
                "Friday 18:00", "Saturday 12:00", "Sunday 15:00"
            ],
            engagement_tips=[
                "Vertical video is essential",
                "Sound is crucial on Snapchat",
                "First frame must capture attention",
                "Use native Snapchat filters sparingly"
            ]
        ),
        
        PlatformType.TWITTER: PlatformPreset(
            platform=PlatformType.TWITTER,
            name="Twitter/X Video Optimized",
            description="Optimized for Twitter/X video",
            specs=VideoSpecs(
                resolution="1080x1920",  # Supports both 9:16 and 16:9
                aspect_ratio="9:16",
                fps=30,
                min_fps=24,
                max_fps=60,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="5M",
                audio_bitrate="128k",
                max_file_size_mb=512,
                max_duration_sec=140,
                recommended_duration_sec=45,
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 100,
                "bottom": 150,
                "left": 60,
                "right": 60
            },
            caption_settings={
                "position": "bottom",
                "safe_bottom_margin": 150,
                "font_size": 24,
                "max_lines": 2,
                "word_highlight": True,
                "allowed_chars": 280
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -14,
                "voice_boost_db": 2,
                "music_duck_db": -10
            },
            thumbnail_specs={
                "resolution": "1200x675",
                "aspect": "16:9",
                "format": "jpg"
            },
            hashtag_limit=2,
            caption_char_limit=280,
            best_upload_times=[
                "Monday 12:00", "Wednesday 12:00", "Friday 10:00",
                "Saturday 09:00", "Sunday 10:00"
            ],
            engagement_tips=[
                "Twitter prefers 16:9 but accepts 9:16",
                "Keep videos under 2:20 for timeline",
                "First frame is your thumbnail",
                "Reply to mentions quickly"
            ]
        ),
        
        PlatformType.LINKEDIN: PlatformPreset(
            platform=PlatformType.LINKEDIN,
            name="LinkedIn Video Optimized",
            description="Professional settings for LinkedIn video",
            specs=VideoSpecs(
                resolution="1920x1080",  # LinkedIn prefers horizontal
                aspect_ratio="16:9",
                fps=30,
                min_fps=24,
                max_fps=60,
                video_codec=gpu_utils.get_video_encoder(),
                audio_codec="aac",
                video_bitrate="8M",
                audio_bitrate="192k",
                max_file_size_mb=5000,
                max_duration_sec=600,  # 10 minutes
                recommended_duration_sec=120,
                pixel_format="yuv420p"
            ),
            safe_zones={
                "top": 80,
                "bottom": 100,
                "left": 100,
                "right": 100
            },
            caption_settings={
                "position": "bottom",
                "safe_bottom_margin": 100,
                "font_size": 24,
                "max_lines": 2,
                "word_highlight": False,  # More professional without
                "allowed_chars": 3000
            },
            audio_settings={
                "normalize": True,
                "target_lufs": -16,
                "voice_boost_db": 1,
                "music_duck_db": -8
            },
            thumbnail_specs={
                "resolution": "1280x720",
                "aspect": "16:9",
                "format": "jpg"
            },
            hashtag_limit=3,
            caption_char_limit=3000,
            best_upload_times=[
                "Tuesday 08:00", "Wednesday 08:00", "Thursday 08:00",
                "Tuesday 12:00", "Wednesday 12:00"
            ],
            engagement_tips=[
                "LinkedIn prefers 16:9 horizontal format",
                "Add SRT captions file for accessibility",
                "Professional tone performs better",
                "Engage with comments within 1 hour"
            ]
        ),
    }
    
    def get_preset(self, platform: PlatformType) -> PlatformPreset:
        """Get preset for a specific platform."""
        return self.PRESETS.get(platform, self.PRESETS[PlatformType.TIKTOK])
    
    def get_preset_by_name(self, platform_name: str) -> PlatformPreset:
        """Get preset by platform name string."""
        try:
            platform = PlatformType(platform_name.lower().replace(" ", "_"))
            return self.get_preset(platform)
        except ValueError:
            logger.warning(f"Unknown platform: {platform_name}, using TikTok")
            return self.PRESETS[PlatformType.TIKTOK]
    
    def get_ffmpeg_settings(self, platform: PlatformType) -> Dict[str, Any]:
        """Get FFmpeg encoding settings for a platform."""
        preset = self.get_preset(platform)
        specs = preset.specs
        
        return {
            "video_codec": specs.video_codec,
            "audio_codec": specs.audio_codec,
            "video_bitrate": specs.video_bitrate,
            "audio_bitrate": specs.audio_bitrate,
            "fps": specs.fps,
            "resolution": specs.resolution,
            "pixel_format": specs.pixel_format,
            "extra_args": [
                "-pix_fmt", specs.pixel_format,
                "-movflags", "+faststart",  # Web optimization
                "-tune", "fastdecode",
            ]
        }
    
    def validate_video_for_platform(
        self,
        video_path: Path,
        platform: PlatformType
    ) -> Dict[str, Any]:
        """
        Validate if a video meets platform requirements.
        
        Returns dict with validation results and recommendations.
        """
        preset = self.get_preset(platform)
        issues = []
        recommendations = []
        
        try:
            import subprocess
            import json
            
            # Get video info
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration,size:stream=width,height,r_frame_rate",
                    "-of", "json",
                    str(video_path)
                ],
                capture_output=True,
                text=True
            )
            
            info = json.loads(result.stdout)
            
            # Check duration
            duration = float(info.get("format", {}).get("duration", 0))
            if duration > preset.specs.max_duration_sec:
                issues.append(f"Duration {duration:.1f}s exceeds limit of {preset.specs.max_duration_sec}s")
                recommendations.append(f"Trim to {preset.specs.max_duration_sec} seconds")
            
            # Check file size
            size_bytes = int(info.get("format", {}).get("size", 0))
            size_mb = size_bytes / (1024 * 1024)
            if size_mb > preset.specs.max_file_size_mb:
                issues.append(f"File size {size_mb:.1f}MB exceeds limit of {preset.specs.max_file_size_mb}MB")
                recommendations.append("Reduce bitrate or resolution")
            
            # Check resolution
            stream = info.get("streams", [{}])[0]
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            
            target_res = preset.specs.resolution.split("x")
            target_width, target_height = int(target_res[0]), int(target_res[1])
            
            if width != target_width or height != target_height:
                recommendations.append(f"Resize to {preset.specs.resolution}")
            
            return {
                "valid": len(issues) == 0,
                "platform": platform.value,
                "issues": issues,
                "recommendations": recommendations,
                "current_specs": {
                    "duration": duration,
                    "size_mb": size_mb,
                    "resolution": f"{width}x{height}"
                }
            }
            
        except Exception as e:
            return {
                "valid": False,
                "error": str(e),
                "issues": ["Failed to validate video"],
                "recommendations": []
            }


# Global instance
_presets_system: Optional[PlatformExportPresets] = None


def get_platform_presets() -> PlatformExportPresets:
    """Get global platform presets instance."""
    global _presets_system
    if _presets_system is None:
        _presets_system = PlatformExportPresets()
    return _presets_system


def get_export_settings(
    platform_name: str,
    video_path: Optional[Path] = None
) -> Dict[str, Any]:
    """
    Convenience function to get complete export settings.
    
    Args:
        platform_name: Name of target platform
        video_path: Optional video to validate
    
    Returns:
        Dict with complete export configuration
    """
    system = get_platform_presets()
    preset = system.get_preset_by_name(platform_name)
    
    settings = {
        "platform": preset.platform.value,
        "name": preset.name,
        "ffmpeg_settings": system.get_ffmpeg_settings(preset.platform),
        "safe_zones": preset.safe_zones,
        "caption_settings": preset.caption_settings,
        "audio_settings": preset.audio_settings,
        "limits": {
            "max_duration_sec": preset.specs.max_duration_sec,
            "recommended_duration": preset.specs.recommended_duration_sec,
            "max_file_size_mb": preset.specs.max_file_size_mb,
            "hashtag_limit": preset.hashtag_limit,
            "caption_limit": preset.caption_char_limit
        },
        "best_practices": {
            "upload_times": preset.best_upload_times,
            "tips": preset.engagement_tips
        }
    }
    
    # Validate if video provided
    if video_path:
        validation = system.validate_video_for_platform(video_path, preset.platform)
        settings["validation"] = validation
    
    return settings
