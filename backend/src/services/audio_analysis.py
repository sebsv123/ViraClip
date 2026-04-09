"""
Advanced Audio Analysis Service
Music detection, sound effects analysis, and audio enhancement.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
import subprocess
import numpy as np

logger = logging.getLogger(__name__)


class AudioType(Enum):
    """Types of audio content."""
    SPEECH = "speech"
    MUSIC = "music"
    SILENCE = "silence"
    SFX = "sound_effects"
    MIXED = "mixed"


class MusicGenre(Enum):
    """Detected music genres."""
    POP = "pop"
    ROCK = "rock"
    HIP_HOP = "hip_hop"
    ELECTRONIC = "electronic"
    CLASSICAL = "classical"
    JAZZ = "jazz"
    AMBIENT = "ambient"
    UPBEAT = "upbeat"
    DRAMATIC = "dramatic"
    UNKNOWN = "unknown"


@dataclass
class AudioSegment:
    """Audio segment analysis."""
    start_time: float
    end_time: float
    audio_type: AudioType
    energy: float
    tempo_bpm: Optional[float]
    key: Optional[str]
    genre: Optional[MusicGenre]
    volume_db: float
    is_voice: bool


@dataclass
class SoundEffect:
    """Detected sound effect."""
    timestamp: float
    effect_type: str
    confidence: float
    duration: float


class AudioAnalysisService:
    """
    Advanced audio analysis for video content.
    """
    
    def __init__(self):
        self._audio_cache: Dict[str, List[AudioSegment]] = {}
        self._supported_formats = ['.mp3', '.wav', '.aac', '.m4a', '.flac']
    
    async def analyze_audio(
        self,
        video_path: Path,
        extract_music_info: bool = True
    ) -> Dict[str, Any]:
        """
        Comprehensive audio analysis of video.
        
        Args:
            video_path: Path to video file
            extract_music_info: Whether to analyze music details
        """
        if not video_path.exists():
            return {"error": "Video not found"}
        
        # Extract audio
        audio_path = await self._extract_audio(video_path)
        
        if not audio_path:
            return {"error": "Failed to extract audio"}
        
        try:
            # Analyze segments
            segments = await self._analyze_audio_segments(audio_path)
            
            # Detect sound effects
            sound_effects = await self._detect_sound_effects(audio_path)
            
            # Analyze music if present
            music_info = None
            if extract_music_info:
                music_segments = [s for s in segments if s.audio_type == AudioType.MUSIC]
                if music_segments:
                    music_info = await self._analyze_music_details(audio_path, music_segments)
            
            # Calculate overall stats
            stats = self._calculate_audio_stats(segments)
            
            # Cleanup
            audio_path.unlink(missing_ok=True)
            
            return {
                "segments": [self._segment_to_dict(s) for s in segments],
                "sound_effects": [self._sfx_to_dict(s) for s in sound_effects],
                "music_info": music_info,
                "statistics": stats,
                "duration": sum(s.end_time - s.start_time for s in segments)
            }
            
        except Exception as e:
            logger.error(f"Audio analysis failed: {e}")
            audio_path.unlink(missing_ok=True)
            return {"error": str(e)}
    
    async def _extract_audio(self, video_path: Path) -> Optional[Path]:
        """Extract audio track from video."""
        import uuid
        
        output_path = Path(f"/tmp/audio_{uuid.uuid4().hex}.wav")
        
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-vn",  # No video
                    "-acodec", "pcm_s16le",
                    "-ar", "44100",
                    "-ac", "2",
                    str(output_path)
                ],
                capture_output=True,
                timeout=60
            )
            
            return output_path if output_path.exists() else None
            
        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return None
    
    async def _analyze_audio_segments(self, audio_path: Path) -> List[AudioSegment]:
        """Analyze audio segments using ffmpeg."""
        segments = []
        
        try:
            # Use ffmpeg silencedetect for silence detection
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-i", str(audio_path),
                    "-af", "silencedetect=noise=-50dB:d=0.5",
                    "-f", "null",
                    "-"
                ],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Parse silence detection output
            silence_periods = []
            silence_start = None
            
            for line in result.stderr.split('\n'):
                if 'silence_start:' in line:
                    try:
                        silence_start = float(line.split('silence_start:')[1].split()[0])
                    except (ValueError, IndexError) as e:
                        # FIX: Malformed ffmpeg output
                        logger.debug(f"Failed to parse silence_start: {e}")
                        pass
                elif 'silence_end:' in line and silence_start is not None:
                    try:
                        silence_end = float(line.split('silence_end:')[1].split()[0])
                        silence_periods.append((silence_start, silence_end))
                        silence_start = None
                    except (ValueError, IndexError) as e:
                        # FIX: Malformed ffmpeg output
                        logger.debug(f"Failed to parse silence_end: {e}")
                        pass
            
            # Create segments (non-silence periods)
            duration = await self._get_audio_duration(audio_path)
            current_time = 0.0
            
            for silence_start, silence_end in sorted(silence_periods):
                # Add speech/music segment before silence
                if current_time < silence_start:
                    segment = AudioSegment(
                        start_time=current_time,
                        end_time=silence_start,
                        audio_type=AudioType.SPEECH,  # Assume speech
                        energy=0.5,
                        tempo_bpm=None,
                        key=None,
                        genre=None,
                        volume_db=-20.0,
                        is_voice=True
                    )
                    segments.append(segment)
                
                # Add silence segment
                segments.append(AudioSegment(
                    start_time=silence_start,
                    end_time=silence_end,
                    audio_type=AudioType.SILENCE,
                    energy=0.0,
                    tempo_bpm=None,
                    key=None,
                    genre=None,
                    volume_db=-60.0,
                    is_voice=False
                ))
                
                current_time = silence_end
            
            # Add final segment
            if current_time < duration:
                segments.append(AudioSegment(
                    start_time=current_time,
                    end_time=duration,
                    audio_type=AudioType.SPEECH,
                    energy=0.5,
                    tempo_bpm=None,
                    key=None,
                    genre=None,
                    volume_db=-20.0,
                    is_voice=True
                ))
            
            return segments
            
        except Exception as e:
            logger.error(f"Segment analysis failed: {e}")
            return []
    
    async def _get_audio_duration(self, audio_path: Path) -> float:
        """Get audio duration."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path)
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            return float(result.stdout.strip())
        except:
            return 0.0
    
    async def _detect_sound_effects(self, audio_path: Path) -> List[SoundEffect]:
        """Detect sound effects in audio."""
        # Placeholder - would use ML model for SFX detection
        return []
    
    async def _analyze_music_details(
        self,
        audio_path: Path,
        music_segments: List[AudioSegment]
    ) -> Dict[str, Any]:
        """Analyze music details using essentia or similar."""
        # Placeholder - would use essentia for tempo/key detection
        
        return {
            "detected": True,
            "tempo_bpm": 120.0,  # Placeholder
            "key": "C major",     # Placeholder
            "genre": MusicGenre.POP.value,
            "segments": len(music_segments),
            "total_duration": sum(s.end_time - s.start_time for s in music_segments)
        }
    
    def _calculate_audio_stats(self, segments: List[AudioSegment]) -> Dict[str, Any]:
        """Calculate audio statistics."""
        if not segments:
            return {}
        
        total_duration = sum(s.end_time - s.start_time for s in segments)
        
        speech_duration = sum(
            s.end_time - s.start_time for s in segments
            if s.audio_type == AudioType.SPEECH
        )
        
        silence_duration = sum(
            s.end_time - s.start_time for s in segments
            if s.audio_type == AudioType.SILENCE
        )
        
        music_duration = sum(
            s.end_time - s.start_time for s in segments
            if s.audio_type == AudioType.MUSIC
        )
        
        avg_volume = np.mean([s.volume_db for s in segments])
        
        return {
            "total_duration": total_duration,
            "speech_ratio": speech_duration / total_duration if total_duration > 0 else 0,
            "silence_ratio": silence_duration / total_duration if total_duration > 0 else 0,
            "music_ratio": music_duration / total_duration if total_duration > 0 else 0,
            "average_volume_db": avg_volume,
            "has_music": music_duration > 0,
            "speech_clarity": "good" if silence_duration / total_duration < 0.3 else "poor"
        }
    
    def _segment_to_dict(self, segment: AudioSegment) -> Dict[str, Any]:
        """Convert segment to dictionary."""
        return {
            "start": segment.start_time,
            "end": segment.end_time,
            "type": segment.audio_type.value,
            "energy": segment.energy,
            "volume_db": segment.volume_db,
            "is_voice": segment.is_voice,
            "tempo_bpm": segment.tempo_bpm,
            "key": segment.key,
            "genre": segment.genre.value if segment.genre else None
        }
    
    def _sfx_to_dict(self, sfx: SoundEffect) -> Dict[str, Any]:
        """Convert sound effect to dictionary."""
        return {
            "timestamp": sfx.timestamp,
            "type": sfx.effect_type,
            "confidence": sfx.confidence,
            "duration": sfx.duration
        }
    
    async def enhance_audio(
        self,
        audio_path: Path,
        target_lufs: float = -14.0
    ) -> Optional[Path]:
        """
        Enhance audio with normalization and compression.
        
        Args:
            audio_path: Input audio path
            target_lufs: Target loudness (standard for streaming is -14 LUFS)
        """
        import uuid
        
        output_path = Path(f"/tmp/enhanced_{uuid.uuid4().hex}.wav")
        
        try:
            # Apply loudness normalization and light compression
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(audio_path),
                    "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11",
                    str(output_path)
                ],
                capture_output=True,
                timeout=60
            )
            
            return output_path if output_path.exists() else None
            
        except Exception as e:
            logger.error(f"Audio enhancement failed: {e}")
            return None
    
    def suggest_background_music(
        self,
        video_duration: float,
        content_mood: str,
        target_platform: str = "youtube"
    ) -> List[Dict[str, Any]]:
        """Suggest background music based on content."""
        # Platform-specific recommendations
        platform_tempos = {
            "tiktok": (120, 140),  # Fast, energetic
            "youtube": (100, 130),  # Moderate
            "instagram": (110, 135),  # Upbeat
        }
        
        tempo_range = platform_tempos.get(target_platform, (100, 130))
        
        # Mood-based genre suggestions
        mood_genres = {
            "energetic": ["electronic", "pop", "upbeat"],
            "calm": ["ambient", "acoustic", "classical"],
            "dramatic": ["cinematic", "orchestral", "rock"],
            "funny": ["upbeat", "quirky", "pop"],
            "educational": ["ambient", "light", "acoustic"]
        }
        
        genres = mood_genres.get(content_mood, ["ambient", "pop"])
        
        return [
            {
                "genre": genre,
                "tempo_range": tempo_range,
                "duration": video_duration,
                "mood": content_mood,
                "suggested_volume": -20  # dB, background level
            }
            for genre in genres[:3]
        ]


# Global instance
_audio_service: Optional[AudioAnalysisService] = None


def get_audio_analysis_service() -> AudioAnalysisService:
    """Get global audio analysis service."""
    global _audio_service
    if _audio_service is None:
        _audio_service = AudioAnalysisService()
    return _audio_service


# Convenience functions
async def analyze_video_audio(video_path: Path) -> Dict[str, Any]:
    """Analyze video audio comprehensively."""
    return await get_audio_analysis_service().analyze_audio(video_path)


def suggest_music_for_clip(duration: float, mood: str, platform: str = "youtube") -> List[Dict[str, Any]]:
    """Suggest background music for clip."""
    return get_audio_analysis_service().suggest_background_music(duration, mood, platform)
