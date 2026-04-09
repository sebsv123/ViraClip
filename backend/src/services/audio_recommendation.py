"""
Audio Recommendation Service
AI-powered music and SFX recommendation for video clips.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..constants import FFPROBE_TIMEOUT, DEFAULT_VIDEO_DURATION

logger = logging.getLogger(__name__)


class AudioType(Enum):
    """Types of audio recommendations."""
    BACKGROUND_MUSIC = "background_music"
    SFX = "sound_effects"
    TRANSITION_SFX = "transition_sfx"
    AMBIENT = "ambient"
    BEAT_DROP = "beat_drop"


class MusicGenre(Enum):
    """Music genres for recommendation."""
    UPBEAT_POP = "upbeat_pop"
    ELECTRONIC = "electronic"
    LOFI = "lofi"
    CINEMATIC = "cinematic"
    HIPHOP = "hiphop"
    ROCK = "rock"
    ACOUSTIC = "acoustic"
    EPIC = "epic"
    TRENDING = "trending"


@dataclass
class AudioRecommendation:
    """Audio recommendation result."""
    recommendation_id: str
    audio_type: AudioType
    genre: MusicGenre
    title: str
    artist: str
    duration: float
    bpm: int
    mood: str
    energy_level: float  # 0-1
    match_score: float  # 0-1
    file_url: Optional[str]
    preview_url: Optional[str]
    license_type: str
    credits_cost: int
    tags: List[str]


@dataclass
class VideoAudioProfile:
    """Audio profile extracted from video."""
    duration: float
    has_voiceover: bool
    dominant_mood: str
    energy_curve: List[float]
    scene_changes: List[float]
    recommended_bpm_range: tuple
    suitable_genres: List[MusicGenre]


class AudioRecommendationService:
    """
    AI-powered audio recommendation engine for video clips.
    """
    
    def __init__(self):
        self._music_library: List[Dict[str, Any]] = []
        self._sfx_library: List[Dict[str, Any]] = []
        self._recommendation_cache: Dict[str, List[AudioRecommendation]] = {}
        self._initialize_library()
    
    def _initialize_library(self):
        """Initialize music and SFX library."""
        # Simulated music library
        self._music_library = [
            {
                "id": "track_001",
                "title": "Viral Energy",
                "artist": "AudioFlow",
                "genre": MusicGenre.UPBEAT_POP,
                "duration": 30.0,
                "bpm": 128,
                "mood": "energetic",
                "energy": 0.9,
                "tags": ["viral", "upbeat", "trending"],
                "license": "premium",
                "cost": 10
            },
            {
                "id": "track_002",
                "title": "Chill Vibes",
                "artist": "LoFi Studio",
                "genre": MusicGenre.LOFI,
                "duration": 60.0,
                "bpm": 85,
                "mood": "calm",
                "energy": 0.3,
                "tags": ["chill", "study", "background"],
                "license": "free",
                "cost": 0
            },
            {
                "id": "track_003",
                "title": "Epic Moment",
                "artist": "Cinematic Sounds",
                "genre": MusicGenre.CINEMATIC,
                "duration": 45.0,
                "bpm": 110,
                "mood": "dramatic",
                "energy": 0.8,
                "tags": ["epic", "dramatic", "emotional"],
                "license": "premium",
                "cost": 15
            },
            {
                "id": "track_004",
                "title": "Tech Beats",
                "artist": "Future Audio",
                "genre": MusicGenre.ELECTRONIC,
                "duration": 30.0,
                "bpm": 140,
                "mood": "futuristic",
                "energy": 0.95,
                "tags": ["electronic", "tech", "modern"],
                "license": "premium",
                "cost": 12
            },
            {
                "id": "track_005",
                "title": "TikTok Hit",
                "artist": "Trending Music",
                "genre": MusicGenre.TRENDING,
                "duration": 15.0,
                "bpm": 120,
                "mood": "fun",
                "energy": 0.85,
                "tags": ["trending", "viral", "dance"],
                "license": "standard",
                "cost": 5
            },
        ]
        
        # SFX library
        self._sfx_library = [
            {"id": "sfx_001", "name": "Whoosh", "category": "transition", "duration": 1.0},
            {"id": "sfx_002", "name": "Pop", "category": "emphasis", "duration": 0.5},
            {"id": "sfx_003", "name": "Ding", "category": "notification", "duration": 0.8},
            {"id": "sfx_004", "name": "Bass Drop", "category": "beat_drop", "duration": 2.0},
            {"id": "sfx_005", "name": "Glitch", "category": "effect", "duration": 0.3},
        ]
    
    async def analyze_video_for_audio(
        self,
        video_path: Path,
        transcript: Optional[str] = None
    ) -> VideoAudioProfile:
        """
        Analyze video content to determine optimal audio profile.
        
        Args:
            video_path: Path to video file
            transcript: Optional transcript text
        """
        # Extract video metadata
        duration = await self._get_video_duration(video_path)
        
        # Detect voiceover
        has_voiceover = await self._detect_voiceover(video_path)
        
        # Analyze mood from visual content
        dominant_mood = await self._analyze_visual_mood(video_path)
        
        # Generate energy curve
        energy_curve = await self._generate_energy_curve(video_path)
        
        # Detect scene changes for beat matching
        scene_changes = await self._detect_scene_changes(video_path)
        
        # Determine BPM range
        if dominant_mood in ["energetic", "exciting", "fast-paced"]:
            bpm_range = (120, 150)
            suitable_genres = [MusicGenre.UPBEAT_POP, MusicGenre.ELECTRONIC, MusicGenre.HIPHOP]
        elif dominant_mood in ["calm", "relaxed", "peaceful"]:
            bpm_range = (60, 100)
            suitable_genres = [MusicGenre.LOFI, MusicGenre.ACOUSTIC]
        elif dominant_mood in ["dramatic", "emotional", "intense"]:
            bpm_range = (90, 130)
            suitable_genres = [MusicGenre.CINEMATIC, MusicGenre.EPIC]
        else:
            bpm_range = (100, 140)
            suitable_genres = [MusicGenre.TRENDING, MusicGenre.UPBEAT_POP]
        
        return VideoAudioProfile(
            duration=duration,
            has_voiceover=has_voiceover,
            dominant_mood=dominant_mood,
            energy_curve=energy_curve,
            scene_changes=scene_changes,
            recommended_bpm_range=bpm_range,
            suitable_genres=suitable_genres
        )
    
    async def recommend_music(
        self,
        video_path: Path,
        video_profile: VideoAudioProfile,
        count: int = 5,
        exclude_vocals: bool = True
    ) -> List[AudioRecommendation]:
        """
        Recommend background music for video.
        
        Args:
            video_path: Video file path
            video_profile: Audio profile from analysis
            count: Number of recommendations
            exclude_vocals: Prefer instrumental tracks
        """
        recommendations = []
        import uuid
        
        for track in self._music_library:
            # Calculate match score
            score = 0.0
            
            # Genre match
            if track["genre"] in video_profile.suitable_genres:
                score += 0.3
            
            # BPM match
            min_bpm, max_bpm = video_profile.recommended_bpm_range
            if min_bpm <= track["bpm"] <= max_bpm:
                score += 0.2
            
            # Mood match
            mood_match = self._calculate_mood_match(
                track["mood"], 
                video_profile.dominant_mood
            )
            score += mood_match * 0.2
            
            # Energy match
            avg_energy = sum(video_profile.energy_curve) / len(video_profile.energy_curve) if video_profile.energy_curve else 0.5
            energy_diff = abs(track["energy"] - avg_energy)
            score += (1 - energy_diff) * 0.15
            
            # Duration fit
            if track["duration"] >= video_profile.duration:
                score += 0.15
            
            if score > 0.5:  # Minimum threshold
                recommendations.append(AudioRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    audio_type=AudioType.BACKGROUND_MUSIC,
                    genre=track["genre"],
                    title=track["title"],
                    artist=track["artist"],
                    duration=track["duration"],
                    bpm=track["bpm"],
                    mood=track["mood"],
                    energy_level=track["energy"],
                    match_score=score,
                    file_url=f"/api/audio/library/{track['id']}",
                    preview_url=f"/api/audio/preview/{track['id']}",
                    license_type=track["license"],
                    credits_cost=track["cost"],
                    tags=track["tags"]
                ))
        
        # Sort by match score
        recommendations.sort(key=lambda x: x.match_score, reverse=True)
        
        # Cache results
        cache_key = str(video_path)
        self._recommendation_cache[cache_key] = recommendations[:count]
        
        return recommendations[:count]
    
    async def recommend_sfx(
        self,
        video_path: Path,
        scene_changes: List[float],
        key_moments: Optional[List[float]] = None
    ) -> List[AudioRecommendation]:
        """
        Recommend sound effects for key moments.
        
        Args:
            video_path: Video file path
            scene_changes: Timestamps of scene changes
            key_moments: Optional additional key moments
        """
        recommendations = []
        import uuid
        
        # Add SFX for scene transitions
        for i, timestamp in enumerate(scene_changes[:5]):  # Limit to first 5
            sfx = self._sfx_library[i % len(self._sfx_library)]
            
            recommendations.append(AudioRecommendation(
                recommendation_id=str(uuid.uuid4()),
                audio_type=AudioType.TRANSITION_SFX,
                genre=MusicGenre.TRENDING,
                title=sfx["name"],
                artist="SFX Library",
                duration=sfx["duration"],
                bpm=0,
                mood="transition",
                energy_level=0.7,
                match_score=0.9,
                file_url=f"/api/sfx/library/{sfx['id']}",
                preview_url=f"/api/sfx/preview/{sfx['id']}",
                license_type="free",
                credits_cost=0,
                tags=[sfx["category"], "transition"],
            ))
        
        # Add beat drop for key moments
        if key_moments:
            beat_drop = next(
                (s for s in self._sfx_library if s["category"] == "beat_drop"),
                None
            )
            if beat_drop:
                recommendations.append(AudioRecommendation(
                    recommendation_id=str(uuid.uuid4()),
                    audio_type=AudioType.BEAT_DROP,
                    genre=MusicGenre.ELECTRONIC,
                    title=beat_drop["name"],
                    artist="SFX Library",
                    duration=beat_drop["duration"],
                    bpm=0,
                    mood="dramatic",
                    energy_level=0.95,
                    match_score=0.85,
                    file_url=f"/api/sfx/library/{beat_drop['id']}",
                    preview_url=f"/api/sfx/preview/{beat_drop['id']}",
                    license_type="free",
                    credits_cost=0,
                    tags=["beat_drop", "emphasis"],
                ))
        
        return recommendations
    
    async def generate_beat_matched_cuts(
        self,
        video_path: Path,
        music_bpm: int,
        video_duration: float
    ) -> List[float]:
        """
        Generate optimal cut points matched to music beat.
        
        Args:
            video_path: Video file path
            music_bpm: Beats per minute of selected music
            video_duration: Video duration in seconds
        """
        # Calculate beat interval
        beat_interval = 60.0 / music_bpm
        
        # Generate cut points on beats (every 4 beats typically)
        cuts_per_phrase = 4  # 4/4 time, cut every measure
        phrase_interval = beat_interval * cuts_per_phrase
        
        cut_points = []
        current_time = 0.0
        
        while current_time < video_duration:
            # Add some variation (not always exactly on beat)
            variation = 0.0  # Could add small random offset
            cut_points.append(min(current_time + variation, video_duration))
            current_time += phrase_interval
        
        return cut_points[:-1]  # Exclude last if it's the end
    
    async def _get_video_duration(self, video_path: Path) -> float:
        """Get video duration."""
        import subprocess
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True, text=True, timeout=FFPROBE_TIMEOUT
            )
            return float(result.stdout.strip())
        except (ValueError, subprocess.TimeoutExpired, FileNotFoundError) as e:
            # FIX: Expected errors - return default duration
            logger.debug(f"Failed to get video duration, using default: {e}")
            return DEFAULT_VIDEO_DURATION
        except Exception as e:
            # FIX: Unexpected errors
            logger.warning(f"Unexpected error getting video duration: {e}")
            return DEFAULT_VIDEO_DURATION
    
    async def _detect_voiceover(self, video_path: Path) -> bool:
        """Detect if video has voiceover."""
        # Placeholder - would use audio analysis
        return False
    
    async def _analyze_visual_mood(self, video_path: Path) -> str:
        """Analyze visual mood from video."""
        # Placeholder - would use computer vision
        return "energetic"
    
    async def _generate_energy_curve(self, video_path: Path) -> List[float]:
        """Generate energy curve from video."""
        # Placeholder - would analyze motion, color, etc.
        return [0.5, 0.7, 0.6, 0.8, 0.5]
    
    async def _detect_scene_changes(self, video_path: Path) -> List[float]:
        """Detect scene change timestamps."""
        # Placeholder - would use scene detection
        return [5.0, 10.0, 15.0, 20.0]
    
    def _calculate_mood_match(self, track_mood: str, video_mood: str) -> float:
        """Calculate mood compatibility."""
        mood_compatibility = {
            ("energetic", "energetic"): 1.0,
            ("energetic", "exciting"): 0.9,
            ("calm", "calm"): 1.0,
            ("calm", "peaceful"): 0.9,
            ("dramatic", "dramatic"): 1.0,
            ("dramatic", "emotional"): 0.8,
        }
        return mood_compatibility.get((track_mood, video_mood), 0.5)
    
    def get_trending_audio(self, platform: str = "tiktok") -> List[AudioRecommendation]:
        """Get trending audio for specific platform."""
        trending = [
            track for track in self._music_library
            if "trending" in track["tags"] or "viral" in track["tags"]
        ]
        
        import uuid
        return [
            AudioRecommendation(
                recommendation_id=str(uuid.uuid4()),
                audio_type=AudioType.BACKGROUND_MUSIC,
                genre=track["genre"],
                title=track["title"],
                artist=track["artist"],
                duration=track["duration"],
                bpm=track["bpm"],
                mood=track["mood"],
                energy_level=track["energy"],
                match_score=0.9,
                file_url=f"/api/audio/library/{track['id']}",
                preview_url=f"/api/audio/preview/{track['id']}",
                license_type=track["license"],
                credits_cost=track["cost"],
                tags=track["tags"]
            )
            for track in trending[:5]
        ]
    
    def get_audio_stats(self) -> Dict[str, Any]:
        """Get audio library statistics."""
        return {
            "music_tracks": len(self._music_library),
            "sfx_tracks": len(self._sfx_library),
            "total_recommendations_made": sum(
                len(v) for v in self._recommendation_cache.values()
            ),
            "genres_available": len(set(t["genre"] for t in self._music_library))
        }


# Global instance
_audio_rec_service: Optional[AudioRecommendationService] = None


def get_audio_recommendation_service() -> AudioRecommendationService:
    """Get global audio recommendation service."""
    global _audio_rec_service
    if _audio_rec_service is None:
        _audio_rec_service = AudioRecommendationService()
    return _audio_rec_service


# Convenience functions
async def recommend_music_for_video(video_path: Path, count: int = 5) -> List[AudioRecommendation]:
    """Get music recommendations for video."""
    service = get_audio_recommendation_service()
    profile = await service.analyze_video_for_audio(video_path)
    return await service.recommend_music(video_path, profile, count)


async def get_beat_matched_cuts(video_path: Path, bpm: int) -> List[float]:
    """Get beat-matched cut points."""
    service = get_audio_recommendation_service()
    duration = await service._get_video_duration(video_path)
    return await service.generate_beat_matched_cuts(video_path, bpm, duration)
