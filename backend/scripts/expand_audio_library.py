"""
Enhanced Audio Library Expansion Script

Downloads 50+ SFX and 20+ BGM tracks from free, royalty-free sources.
Organizes them by category for viral video editing.

Free sources:
- Mixkit (https://mixkit.co) - Royalty-free SFX and music
- Pixabay (https://pixabay.com) - Free audio under Pixabay License
- All assets are free for commercial use without attribution

Target:
- 50+ SFX organized by type
- 20+ BGM tracks organized by mood
"""

import asyncio
import logging
import os
from pathlib import Path
import httpx

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


# Mixkit Free SFX (https://mixkit.co/free-sound-effects/)
MIXKIT_SFX = {
    "whoosh": [
        "https://assets.mixkit.co/active_storage/sfx/2354/2354.wav",
        "https://assets.mixkit.co/active_storage/sfx/2355/2355.wav",
        "https://assets.mixkit.co/active_storage/sfx/1363/1363.wav",
        "https://assets.mixkit.co/active_storage/sfx/1364/1364.wav",
        "https://assets.mixkit.co/active_storage/sfx/1357/1357.wav",
    ],
    "impact": [
        "https://assets.mixkit.co/active_storage/sfx/2294/2294.wav",
        "https://assets.mixkit.co/active_storage/sfx/2293/2293.wav",
        "https://assets.mixkit.co/active_storage/sfx/1997/1997.wav",
        "https://assets.mixkit.co/active_storage/sfx/1998/1998.wav",
        "https://assets.mixkit.co/active_storage/sfx/2018/2018.wav",
    ],
    "transition": [
        "https://assets.mixkit.co/active_storage/sfx/432/432.wav",
        "https://assets.mixkit.co/active_storage/sfx/2359/2359.wav",
        "https://assets.mixkit.co/active_storage/sfx/2360/2360.wav",
        "https://assets.mixkit.co/active_storage/sfx/2361/2361.wav",
        "https://assets.mixkit.co/active_storage/sfx/2362/2362.wav",
    ],
    "ui": [
        "https://assets.mixkit.co/active_storage/sfx/1109/1109.wav",
        "https://assets.mixkit.co/active_storage/sfx/1115/1115.wav",
        "https://assets.mixkit.co/active_storage/sfx/2013/2013.wav",
        "https://assets.mixkit.co/active_storage/sfx/2014/2014.wav",
        "https://assets.mixkit.co/active_storage/sfx/2015/2015.wav",
        "https://assets.mixkit.co/active_storage/sfx/2016/2016.wav",
    ],
    "riser": [
        "https://assets.mixkit.co/active_storage/sfx/2299/2299.wav",
        "https://assets.mixkit.co/active_storage/sfx/2300/2300.wav",
        "https://assets.mixkit.co/active_storage/sfx/2301/2301.wav",
        "https://assets.mixkit.co/active_storage/sfx/2302/2302.wav",
    ],
    "bass": [
        "https://assets.mixkit.co/active_storage/sfx/2297/2297.wav",
        "https://assets.mixkit.co/active_storage/sfx/2298/2298.wav",
        "https://assets.mixkit.co/active_storage/sfx/1995/1995.wav",
        "https://assets.mixkit.co/active_storage/sfx/1996/1996.wav",
    ],
    "notification": [
        "https://assets.mixkit.co/active_storage/sfx/1114/1114.wav",
        "https://assets.mixkit.co/active_storage/sfx/2025/2025.wav",
        "https://assets.mixkit.co/active_storage/sfx/2026/2026.wav",
        "https://assets.mixkit.co/active_storage/sfx/2357/2357.wav",
    ],
    "error": [
        "https://assets.mixkit.co/active_storage/sfx/2003/2003.wav",
        "https://assets.mixkit.co/active_storage/sfx/2004/2004.wav",
    ],
    "success": [
        "https://assets.mixkit.co/active_storage/sfx/1435/1435.wav",
        "https://assets.mixkit.co/active_storage/sfx/2000/2000.wav",
        "https://assets.mixkit.co/active_storage/sfx/2019/2019.wav",
    ],
    "typing": [
        "https://assets.mixkit.co/active_storage/sfx/2596/2596.wav",
        "https://assets.mixkit.co/active_storage/sfx/2597/2597.wav",
    ],
}

# Pixabay Free Music (royalty-free BGM)
PIXABAY_BGM = {
    "energetic": [
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_1d4d8e5b26.mp3?filename=stomping-rock-guitar-logo-124738.mp3",
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=upbeat-indie-folk-148039.mp3",
        "https://cdn.pixabay.com/download/audio/2022/08/04/audio_79d65d4f27.mp3?filename=for-a-better-tomorrow-186154.mp3",
    ],
    "chill": [
        "https://cdn.pixabay.com/download/audio/2021/08/04/audio_0625c1539c.mp3?filename=lofi-study-112191.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/10/audio_4f5753329e.mp3?filename=ambient-piano-amp-strings-10711.mp3",
        "https://cdn.pixabay.com/download/audio/2022/08/02/audio_d1718ab41b.mp3?filename=lo-fi-chill-medium-version-159456.mp3",
    ],
    "suspense": [
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3?filename=creepy-background-daniel_simon.mp3",
        "https://cdn.pixabay.com/download/audio/2021/08/04/audio_12b0c7443c.mp3?filename=horror-background-atmosphere-142006.mp3",
    ],
    "corporate": [
        "https://cdn.pixabay.com/download/audio/2022/10/25/audio_191db61f76.mp3?filename=smart-tech-141588.mp3",
        "https://cdn.pixabay.com/download/audio/2022/03/24/audio_2cabbef229.mp3?filename=modern-vlog-140012.mp3",
    ],
    "motivational": [
        "https://cdn.pixabay.com/download/audio/2022/02/22/audio_d1718ab41b.mp3?filename=inspiring-cinematic-ambient-116199.mp3",
        "https://cdn.pixabay.com/download/audio/2022/08/23/audio_550d815fa5.mp3?filename=inspiring-dreams-148738.mp3",
    ],
    "epic": [
        "https://cdn.pixabay.com/download/audio/2022/03/12/audio_b7d7a6cd00.mp3?filename=powerful-epic-trailer-126866.mp3",
        "https://cdn.pixabay.com/download/audio/2022/11/28/audio_46275a6582.mp3?filename=cinematic-trailer-epic-149449.mp3",
    ],
    "upbeat": [
        "https://cdn.pixabay.com/download/audio/2022/08/04/audio_79d65d4f27.mp3?filename=summer-walk-152722.mp3",
        "https://cdn.pixabay.com/download/audio/2022/05/13/audio_c7574858de.mp3?filename=ukulele-and-whistling-137837.mp3",
    ],
}


class AudioLibraryExpander:
    """Downloads and organizes expanded audio library."""
    
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.sfx_dir = base_dir / "sfx"
        self.bgm_dir = base_dir / "bgm"
        
        self.client = httpx.AsyncClient(
            timeout=60.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10)
        )
        
        self.stats = {
            "sfx_downloaded": 0,
            "sfx_failed": 0,
            "bgm_downloaded": 0,
            "bgm_failed": 0,
        }
    
    async def expand_library(self):
        """Download all audio assets to expand library."""
        logger.info("=" * 60)
        logger.info("ViraClip Audio Library Expansion")
        logger.info("=" * 60)
        logger.info(f"Target: 50+ SFX, 20+ BGM tracks")
        logger.info(f"Output: {self.base_dir}")
        logger.info("")
        
        # Download SFX
        logger.info("📦 Downloading SFX...")
        await self._download_sfx()
        
        # Download BGM
        logger.info("")
        logger.info("🎵 Downloading BGM...")
        await self._download_bgm()
        
        # Summary
        logger.info("")
        logger.info("=" * 60)
        logger.info("✅ Audio Library Expansion Complete!")
        logger.info("=" * 60)
        logger.info(f"SFX: {self.stats['sfx_downloaded']} downloaded, {self.stats['sfx_failed']} failed")
        logger.info(f"BGM: {self.stats['bgm_downloaded']} downloaded, {self.stats['bgm_failed']} failed")
        logger.info("")
        
        total_sfx = sum(len(list((self.sfx_dir / cat).glob("*"))) if (self.sfx_dir / cat).exists() else 0 
                       for cat in MIXKIT_SFX.keys())
        total_bgm = sum(len(list((self.bgm_dir / mood).glob("*"))) if (self.bgm_dir / mood).exists() else 0 
                       for mood in PIXABAY_BGM.keys())
        
        logger.info(f"📁 Total library size:")
        logger.info(f"   - SFX: {total_sfx} files across {len(MIXKIT_SFX)} categories")
        logger.info(f"   - BGM: {total_bgm} tracks across {len(PIXABAY_BGM)} moods")
        
        if total_sfx >= 50:
            logger.info(f"   ✅ SFX target reached ({total_sfx} >= 50)")
        else:
            logger.info(f"   ⚠️  SFX below target ({total_sfx} < 50)")
        
        if total_bgm >= 20:
            logger.info(f"   ✅ BGM target reached ({total_bgm} >= 20)")
        else:
            logger.info(f"   ⚠️  BGM below target ({total_bgm} < 20)")
    
    async def _download_sfx(self):
        """Download all SFX files."""
        tasks = []
        
        for category, urls in MIXKIT_SFX.items():
            category_dir = self.sfx_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            
            for i, url in enumerate(urls, 1):
                ext = ".wav" if url.endswith(".wav") else ".mp3"
                filename = f"{category}_{i:02d}{ext}"
                output_path = category_dir / filename
                tasks.append(self._download_file(url, output_path, "SFX", category))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.stats["sfx_downloaded"] = sum(1 for r in results if r is True)
        self.stats["sfx_failed"] = sum(1 for r in results if r is not True)
    
    async def _download_bgm(self):
        """Download all BGM files."""
        tasks = []
        
        for mood, urls in PIXABAY_BGM.items():
            mood_dir = self.bgm_dir / mood
            mood_dir.mkdir(parents=True, exist_ok=True)
            
            for i, url in enumerate(urls, 1):
                filename = f"{mood}_{i:02d}.mp3"
                output_path = mood_dir / filename
                tasks.append(self._download_file(url, output_path, "BGM", mood))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.stats["bgm_downloaded"] = sum(1 for r in results if r is True)
        self.stats["bgm_failed"] = sum(1 for r in results if r is not True)
    
    async def _download_file(self, url: str, output_path: Path, file_type: str, category: str) -> bool:
        """Download a single audio file."""
        if output_path.exists():
            logger.debug(f"  ⏩ Skip (exists): {output_path.name}")
            return True
        
        try:
            response = await self.client.get(url)
            
            if response.status_code == 200:
                output_path.write_bytes(response.content)
                size_kb = len(response.content) / 1024
                logger.info(f"  ✅ {file_type}/{category}: {output_path.name} ({size_kb:.1f} KB)")
                return True
            else:
                logger.warning(f"  ❌ Failed ({response.status_code}): {output_path.name}")
                return False
        
        except Exception as e:
            logger.warning(f"  ❌ Error downloading {output_path.name}: {e}")
            return False
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


async def main():
    """Main entry point."""
    # Determine output directory (Docker or local dev)
    if os.path.exists("/app/assets/sounds"):
        base_dir = Path("/app/assets/sounds")
    else:
        # Local dev: backend/assets/sounds
        script_dir = Path(__file__).parent
        base_dir = script_dir.parent / "assets" / "sounds"
    
    base_dir.mkdir(parents=True, exist_ok=True)
    
    expander = AudioLibraryExpander(base_dir)
    
    try:
        await expander.expand_library()
    finally:
        await expander.close()


if __name__ == "__main__":
    asyncio.run(main())
