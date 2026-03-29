"""
Broll Service - manages and selects B-roll assets for viral video enhancement.
"""
import logging
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..config import Config

logger = logging.getLogger(__name__)

class BrollService:
    """Service for managing B-roll assets and matching them to content."""
    
    def __init__(self):
        self.config = Config()
        self.broll_dir = Path(self.config.temp_dir) / "stock_broll"
        self.broll_dir.mkdir(parents=True, exist_ok=True)
        
        # Mapping of keywords to local stock files (placeholders for now)
        self.theme_map = {
            "satisfying": ["gta_stunts.mp4", "minecraft_parkour.mp4", "kinetic_sand.mp4"],
            "motivational": ["sunset_workout.mp4", "business_meeting.mp4"],
            "educational": ["library_books.mp4", "writing_code.mp4"],
            "lifestyle": ["couple_cooking.mp4", "morning_routine.mp4"],
            "cyberpunk": ["neon_city.mp4", "digital_circuit.mp4"],
            "cinematic": ["mountain_drone.mp4", "cinematic_clouds.mp4"],
            "general": ["beach_waves.mp4", "city_timelapse.mp4"]
        }

    def get_broll_for_keyword(self, keyword: str) -> Optional[Path]:
        """
        Select a B-roll clip based on a keyword or theme.
        Returns Path to the local file if found.
        """
        keyword = keyword.lower()
        
        # Check direct matches or fallback to random stock
        for key, files in self.theme_map.items():
            if key in keyword:
                filename = random.choice(files)
                path = self.broll_dir / filename
                if path.exists():
                    return path
        
        # Ultimate fallback: random file from broll_dir
        all_files = list(self.broll_dir.glob("*.mp4"))
        if all_files:
            return random.choice(all_files)
            
        return None

    def get_broll_for_opportunity(self, opportunity: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processes a BRollOpportunity from AI analysis and returns a suggestion with local_path.
        """
        search_term = opportunity.get("search_term", "general")
        local_path = self.get_broll_for_keyword(search_term)
        
        if local_path:
            return {
                "local_path": str(local_path),
                "timestamp": opportunity.get("timestamp", 0),
                "duration": opportunity.get("duration", 3.0),
                "context": opportunity.get("context", "")
            }
        return None

    def _search_pexels(self, query: str) -> Optional[str]:
        """Search Pexels for a 9:16 video matching the query."""
        import requests
        if not self.config.pexels_api_key:
            logger.warning("PEXELS_API_KEY not set — stock search disabled")
            return None
            
        url = "https://api.pexels.com/videos/search"
        headers = {"Authorization": self.config.pexels_api_key}
        params = {
            "query": query,
            "per_page": 5,
            "orientation": "portrait"
        }
        
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            videos = data.get("videos", [])
            if not videos:
                return None
            
            # Prefer 1080p if available
            best_video = videos[0]
            video_files = best_video.get("video_files", [])
            # Filter for 9:16 (portrait) and MP4
            for vf in video_files:
                if vf.get("width") and vf.get("height"):
                    if vf["height"] > vf["width"] and vf.get("file_type") == "video/mp4":
                        return vf["link"]
            return video_files[0]["link"] if video_files else None
        except Exception as e:
            logger.error(f"Pexels search error: {e}")
            return None

    def _download_pexels_video(self, url: str, query: str) -> Optional[Path]:
        """Download a video from Pexels to the local cache."""
        import requests
        safe_query = "".join([c if c.isalnum() else "_" for c in query]).lower()
        target_path = self.broll_dir / f"pexels_{safe_query}.mp4"
        
        if target_path.exists():
            return target_path
            
        try:
            logger.info(f"📥 Downloading stock: {query} -> {target_path}")
            resp = requests.get(url, stream=True, timeout=30)
            resp.raise_for_status()
            with open(target_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return target_path
        except Exception as e:
            logger.error(f"Pexels download fail: {e}")
            return None

    async def prepare_default_stock(self):
        """
        Placeholder to ensure some default stock exists for demo/dev.
        """
        logger.info("Ensuring default B-roll stock exists...")
        pass
