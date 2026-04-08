"""
Download Viral Audio Assets

Downloads SFX and BGM from free GitHub repositories and organizes them
into the ViraClip audio library structure.

Sources:
- https://github.com/arnofaure/free-sfx (100 curated SFX)
- https://github.com/soundeffectapp/Free-Sound-Effects-Library (via CDN)
- Free music archives (royalty-free BGM)
"""

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import List, Dict
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Audio asset sources
SFX_SOURCES = {
    "whoosh": [
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Whoosh/whoosh_01.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Whoosh/whoosh_02.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Whoosh/whoosh_03.mp3",
    ],
    "impact": [
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Impact/impact_01.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Impact/impact_02.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Impact/bass_drop.mp3",
    ],
    "transition": [
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Transition/glitch_01.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Transition/swipe_01.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Transition/scratch.mp3",
    ],
    "ui": [
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/UI/pop.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/UI/ding.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/UI/chime.mp3",
    ],
    "ambient": [
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Ambient/tension.mp3",
        "https://github.com/arnofaure/free-sfx/raw/master/SFX/Ambient/riser.mp3",
    ],
}

# Fallback URLs if GitHub is unavailable
FALLBACK_SFX = {
    "whoosh_1": "https://assets.mixkit.co/sfx/preview/mixkit-fast-whoosh-1357.mp3",
    "whoosh_2": "https://assets.mixkit.co/sfx/preview/mixkit-swoosh-transition-1363.mp3",
    "impact_1": "https://assets.mixkit.co/sfx/preview/mixkit-heavy-cinematic-impact-2294.mp3",
    "pop": "https://assets.mixkit.co/sfx/preview/mixkit-select-click-1109.mp3",
    "glitch": "https://assets.mixkit.co/sfx/preview/mixkit-glitch-short-432.mp3",
}

# Free BGM sources (royalty-free)
BGM_SOURCES = {
    "energetic": [
        "https://cdn.pixabay.com/download/audio/2022/03/15/audio_1d4d8e5b26.mp3",  # Energetic rock
    ],
    "chill": [
        "https://cdn.pixabay.com/download/audio/2021/08/04/audio_0625c1539c.mp3",  # Lofi chill
    ],
    "suspense": [
        "https://cdn.pixabay.com/download/audio/2022/05/27/audio_1808fbf07a.mp3",  # Suspense
    ],
}


class ViralAudioDownloader:
    """Downloads and organizes viral audio assets."""
    
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.sfx_dir = output_dir / "sfx"
        self.bgm_dir = output_dir / "bgm"
        
        self.client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    
    async def download_all(self):
        """Download all audio assets."""
        logger.info("Starting viral audio download...")
        
        # Download SFX
        logger.info("Downloading SFX...")
        sfx_tasks = []
        
        for category, urls in SFX_SOURCES.items():
            category_dir = self.sfx_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            
            for i, url in enumerate(urls):
                filename = f"{category}_{i+1:02d}.mp3"
                output_path = category_dir / filename
                sfx_tasks.append(self._download_file(url, output_path))
        
        # Download fallback SFX
        for name, url in FALLBACK_SFX.items():
            output_path = self.sfx_dir / f"{name}.mp3"
            sfx_tasks.append(self._download_file(url, output_path))
        
        sfx_results = await asyncio.gather(*sfx_tasks, return_exceptions=True)
        sfx_success = sum(1 for r in sfx_results if r is True)
        logger.info(f"SFX downloaded: {sfx_success}/{len(sfx_tasks)}")
        
        # Download BGM
        logger.info("Downloading BGM...")
        bgm_tasks = []
        
        for mood, urls in BGM_SOURCES.items():
            mood_dir = self.bgm_dir / mood
            mood_dir.mkdir(parents=True, exist_ok=True)
            
            for i, url in enumerate(urls):
                filename = f"{mood}_{i+1:02d}.mp3"
                output_path = mood_dir / filename
                bgm_tasks.append(self._download_file(url, output_path))
        
        bgm_results = await asyncio.gather(*bgm_tasks, return_exceptions=True)
        bgm_success = sum(1 for r in bgm_results if r is True)
        logger.info(f"BGM downloaded: {bgm_success}/{len(bgm_tasks)}")
        
        logger.info("✅ Viral audio download complete!")
        logger.info(f"   SFX: {sfx_success} files in {self.sfx_dir}")
        logger.info(f"   BGM: {bgm_success} files in {self.bgm_dir}")
    
    async def _download_file(self, url: str, output_path: Path) -> bool:
        """Download a single file."""
        if output_path.exists():
            logger.debug(f"Skip (exists): {output_path.name}")
            return True
        
        try:
            response = await self.client.get(url)
            
            if response.status_code == 200:
                output_path.write_bytes(response.content)
                logger.info(f"✓ Downloaded: {output_path.name}")
                return True
            else:
                logger.warning(f"✗ Failed ({response.status_code}): {url}")
                return False
        
        except Exception as e:
            logger.warning(f"✗ Error downloading {url}: {e}")
            return False
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


async def main():
    """Main entry point."""
    # Determine output directory
    if os.path.exists("/app/assets/sounds"):
        output_dir = Path("/app/assets/sounds")  # Docker
    else:
        output_dir = Path(__file__).parent.parent / "assets" / "sounds"  # Local dev
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Output directory: {output_dir}")
    
    downloader = ViralAudioDownloader(output_dir)
    
    try:
        await downloader.download_all()
    finally:
        await downloader.close()
    
    logger.info("Done! Run the audio library service to index the files.")


if __name__ == "__main__":
    asyncio.run(main())
