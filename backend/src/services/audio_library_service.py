import os
import random
import logging
from pathlib import Path
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

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
    Manages the selection of royalty-free background music (BGM) 
    and sound effects (SFX) for ViraClip production.
    """
    
    def __init__(self):
        # Base path for audio assets
        self.base_path = Path(__file__).parent.parent / "assets" / "audio"
        self.bgm_path = self.base_path / "bgm"
        self.sfx_path = self.base_path / "sfx"
        
        # Ensure directory structure exists (though created via CLI usually)
        self.bgm_path.mkdir(parents=True, exist_ok=True)
        self.sfx_path.mkdir(parents=True, exist_ok=True)

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
