import os
import random
import logging
import json
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class AudioAsset:
    """Metadata for an audio asset."""
    path: str
    category: str
    mood: Optional[str] = None
    duration: float = 0.0
    file_size: int = 0

# Mapping from AI-detected niches to musical styles
NICHE_BGM_MAPPING = {
    "finance": ["professional", "steady", "minimal"],
    "motivational": ["inspiring", "orchestral", "powerful"],
    "tech": ["digital", "modern", "synth"],
    "comedy": ["upbeat", "quirky", "fast"],
    "gaming": ["epic", "high-energy", "electronic"],
    "fitness": ["high-intensity", "aggressive", "rhythmic"],
    "education": ["calm", "acoustic", "lofi"],
    "lifestyle": ["chillhop", "acoustic", "warm"],
    "cyberpunk": ["synthwave", "glitch", "futuristic"],
    "cinematic": ["orchestral", "epic", "atmospheric"],
    "suspense": ["dark", "minimal", "tense"],
    "travel": ["ambient", "world", "vibrant"],
    "marketing": ["corporate", "clean", "progressive"],
    "religion": ["spiritual", "peaceful", "ethereal"],
    "sports": ["energetic", "rock", "stadium"],
    "general": ["lofi", "ambient", "neutral"]
}

class AudioLibraryService:
    """
    Enhanced audio library with auto-indexing and categorization.
    Manages BGM (background music) and SFX (sound effects) for viral clips.
    """
    
    def __init__(self):
        # Use environment variable for base path (supports Docker)
        base_env = os.environ.get("AUDIO_LIBRARY_PATH", "/app/assets/sounds")
        self.base_path = Path(base_env)
        self.bgm_path = self.base_path / "bgm"
        self.sfx_path = self.base_path / "sfx"
        
        # Ensure directory structure exists
        self.bgm_path.mkdir(parents=True, exist_ok=True)
        self.sfx_path.mkdir(parents=True, exist_ok=True)
        
        # Cache file for metadata
        self.cache_file = self.base_path / "audio_library_cache.json"
        
        # In-memory index
        self.bgm_index: Dict[str, List[AudioAsset]] = {}
        self.sfx_index: Dict[str, List[AudioAsset]] = {}
        
        # Auto-index on init
        self._load_or_build_index()

    def get_bgm_for_niche(self, niche: str) -> Optional[Path]:
        """
        Selects a random BGM track matching the niche's style.
        Looks into subfolders named after styles (e.g., bgm/professional/*.mp3).
        """
        niche = niche.lower()
        styles = NICHE_BGM_MAPPING.get(niche, NICHE_BGM_MAPPING["general"])
        
        # Collect all candidate files from matching style folders
        candidates = []
        for style in styles:
            style_dir = self.bgm_path / style
            if style_dir.exists() and style_dir.is_dir():
                candidates.extend(list(style_dir.glob("*.mp3")) + list(style_dir.glob("*.wav")))
        
        # Fallback to general if no specific style matches found
        if not candidates:
            general_dir = self.bgm_path / "general"
            if general_dir.exists():
                candidates.extend(list(general_dir.glob("*.mp3")) + list(general_dir.glob("*.wav")))
                
        if not candidates:
            logger.warning(f"No BGM candidates found for niche '{niche}' in {self.bgm_path}")
            return None
            
        return random.choice(candidates)

    def get_sfx_path(self, sfx_type: str) -> Optional[Path]:
        """
        Returns the path to a specific SFX type (e.g., 'pop', 'ding', 'swoosh').
        """
        # Look for files like 'pop.mp3', 'pop_1.wav', etc.
        candidates = list(self.sfx_path.glob(f"{sfx_type}*"))
        if not candidates:
            logger.debug(f"SFX type '{sfx_type}' not found in {self.sfx_path}")
            return None
            
        return random.choice(candidates)

    def get_all_sfx(self) -> Dict[str, Path]:
        """Returns a map of standard SFX types to their current paths."""
        return {
            "pop": self.get_sfx_path("pop"),
            "ding": self.get_sfx_path("ding"),
            "swoosh": self.get_sfx_path("swoosh"),
            "camera_shutter": self.get_sfx_path("shutter")
        }
    
    def _load_or_build_index(self):
        """Load index from cache or rebuild."""
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r') as f:
                    cache_data = json.load(f)
                
                # Rebuild index from cache
                for item in cache_data.get("bgm", []):
                    asset = AudioAsset(**item)
                    mood = asset.mood or "general"
                    if mood not in self.bgm_index:
                        self.bgm_index[mood] = []
                    self.bgm_index[mood].append(asset)
                
                for item in cache_data.get("sfx", []):
                    asset = AudioAsset(**item)
                    category = asset.category
                    if category not in self.sfx_index:
                        self.sfx_index[category] = []
                    self.sfx_index[category].append(asset)
                
                logger.info(f"Audio library loaded from cache: {len(cache_data.get('bgm', []))} BGM, {len(cache_data.get('sfx', []))} SFX")
                return
            except Exception as e:
                logger.warning(f"Failed to load audio cache: {e}")
        
        # Build index from scratch
        self._rebuild_index()
    
    def _rebuild_index(self):
        """Rebuild the audio index by scanning directories."""
        logger.info("Rebuilding audio library index...")
        
        self.bgm_index.clear()
        self.sfx_index.clear()
        
        # Index BGM (organized by mood folders)
        if self.bgm_path.exists():
            for mood_dir in self.bgm_path.iterdir():
                if mood_dir.is_dir():
                    mood = mood_dir.name
                    for audio_file in mood_dir.glob("*"):
                        if audio_file.suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a"]:
                            asset = self._create_asset(audio_file, "bgm", mood)
                            if mood not in self.bgm_index:
                                self.bgm_index[mood] = []
                            self.bgm_index[mood].append(asset)
        
        # Index SFX (organized by category folders)
        if self.sfx_path.exists():
            for category_dir in self.sfx_path.iterdir():
                if category_dir.is_dir():
                    category = category_dir.name
                    for audio_file in category_dir.glob("*"):
                        if audio_file.suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a"]:
                            asset = self._create_asset(audio_file, category, None)
                            if category not in self.sfx_index:
                                self.sfx_index[category] = []
                            self.sfx_index[category].append(asset)
            
            # Also check root sfx folder for uncategorized files
            for audio_file in self.sfx_path.glob("*"):
                if audio_file.is_file() and audio_file.suffix.lower() in [".mp3", ".wav", ".ogg", ".m4a"]:
                    asset = self._create_asset(audio_file, "general", None)
                    if "general" not in self.sfx_index:
                        self.sfx_index["general"] = []
                    self.sfx_index["general"].append(asset)
        
        bgm_count = sum(len(assets) for assets in self.bgm_index.values())
        sfx_count = sum(len(assets) for assets in self.sfx_index.values())
        
        logger.info(f"Audio library indexed: {bgm_count} BGM tracks, {sfx_count} SFX files")
        logger.info(f"BGM moods: {list(self.bgm_index.keys())}")
        logger.info(f"SFX categories: {list(self.sfx_index.keys())}")
        
        # Save cache
        self._save_cache()
    
    def _create_asset(self, path: Path, category: str, mood: Optional[str]) -> AudioAsset:
        """Create audio asset with metadata."""
        duration = self._get_duration(path)
        file_size = path.stat().st_size
        
        return AudioAsset(
            path=str(path),
            category=category,
            mood=mood,
            duration=duration,
            file_size=file_size
        )
    
    def _get_duration(self, path: Path) -> float:
        """Get audio duration using ffprobe."""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception as e:
            logger.debug(f"Failed to get duration for {path}: {e}")
        return 0.0
    
    def _save_cache(self):
        """Save index to cache file."""
        try:
            cache_data = {
                "bgm": [],
                "sfx": []
            }
            
            for mood, assets in self.bgm_index.items():
                for asset in assets:
                    cache_data["bgm"].append(asdict(asset))
            
            for category, assets in self.sfx_index.items():
                for asset in assets:
                    cache_data["sfx"].append(asdict(asset))
            
            with open(self.cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2)
            
            logger.debug(f"Audio library cache saved to {self.cache_file}")
        except Exception as e:
            logger.warning(f"Failed to save audio cache: {e}")
    
    def get_bgm_by_mood(self, mood: str, energy: float = 0.5) -> Optional[Path]:
        """Get random BGM track by mood."""
        mood = mood.lower()
        
        # Check if mood exists in index
        if mood in self.bgm_index and self.bgm_index[mood]:
            asset = random.choice(self.bgm_index[mood])
            return Path(asset.path)
        
        # Fallback to general
        if "general" in self.bgm_index and self.bgm_index["general"]:
            asset = random.choice(self.bgm_index["general"])
            return Path(asset.path)
        
        logger.warning(f"No BGM found for mood '{mood}'")
        return None
    
    def get_sfx(self, category: str, keyword: Optional[str] = None) -> Optional[Path]:
        """Get random SFX from category."""
        category = category.lower()
        
        if category in self.sfx_index and self.sfx_index[category]:
            asset = random.choice(self.sfx_index[category])
            return Path(asset.path)
        
        # Try general category as fallback
        if "general" in self.sfx_index and self.sfx_index["general"]:
            asset = random.choice(self.sfx_index["general"])
            return Path(asset.path)
        
        logger.debug(f"No SFX found for category '{category}'")
        return None
    
    def get_random_sfx(self) -> Optional[Path]:
        """Get random SFX from any category."""
        all_sfx = []
        for assets in self.sfx_index.values():
            all_sfx.extend(assets)
        
        if all_sfx:
            asset = random.choice(all_sfx)
            return Path(asset.path)
        
        return None
    
    def get_library_stats(self) -> Dict:
        """Get statistics about the audio library."""
        bgm_count = sum(len(assets) for assets in self.bgm_index.values())
        sfx_count = sum(len(assets) for assets in self.sfx_index.values())
        
        return {
            "bgm_total": bgm_count,
            "bgm_moods": list(self.bgm_index.keys()),
            "sfx_total": sfx_count,
            "sfx_categories": list(self.sfx_index.keys()),
            "cache_exists": self.cache_file.exists()
        }


# Singleton
_library_instance: Optional[AudioLibraryService] = None


def get_audio_library() -> AudioLibraryService:
    """Get or create singleton audio library instance."""
    global _library_instance
    if _library_instance is None:
        _library_instance = AudioLibraryService()
    return _library_instance
