"""
Download audio files from Mixkit

Mixkit offers 5,000+ royalty-free music tracks and sound effects.
No API key required - direct downloads from CDN.

Categories:
- Music: Upbeat, Cinematic, Ambient, Electronic
- Sound Effects: Transitions, Impacts, UI, Nature
"""

import asyncio
import json
from pathlib import Path
import httpx
import hashlib


# Curated list of Mixkit audio files
# Note: These are example URLs - in production, implement web scraping
# or use Mixkit's catalog if they provide an API

MIXKIT_MUSIC_URLS = {
    "viral_hype": [
        "https://assets.mixkit.co/music/preview/mixkit-epic-orchestra-transition-2290.mp3",
        "https://assets.mixkit.co/music/preview/mixkit-powerful-beat-percussion-trailer-impact-8.mp3",
        "https://assets.mixkit.co/music/preview/mixkit-energetic-upbeat-140.mp3",
    ],
    "cinematic": [
        "https://assets.mixkit.co/music/preview/mixkit-cinematic-atmospheric-ambience-2291.mp3",
        "https://assets.mixkit.co/music/preview/mixkit-tech-house-vibes-130.mp3",
        "https://assets.mixkit.co/music/preview/mixkit-dramatic-and-mystery-trailer-115.mp3",
    ],
    "lofi_chill": [
        "https://assets.mixkit.co/music/preview/mixkit-lofi-study-112.mp3",
        "https://assets.mixkit.co/music/preview/mixkit-a-very-happy-christmas-897.mp3",
        "https://assets.mixkit.co/music/preview/mixkit-sleepy-cat-135.mp3",
    ],
}

MIXKIT_SFX_URLS = {
    "transitions": [
        "https://assets.mixkit.co/sfx/preview/mixkit-quick-jump-arcade-game-239.mp3",
        "https://assets.mixkit.co/sfx/preview/mixkit-arcade-fast-game-over-233.mp3",
        "https://assets.mixkit.co/sfx/preview/mixkit-fast-rocket-whoosh-1714.mp3",
    ],
    "impacts": [
        "https://assets.mixkit.co/sfx/preview/mixkit-hard-typewriter-hit-1364.mp3",
        "https://assets.mixkit.co/sfx/preview/mixkit-arcade-bonus-alert-767.mp3",
        "https://assets.mixkit.co/sfx/preview/mixkit-martial-arts-punch-2052.mp3",
    ],
    "ui_sounds": [
        "https://assets.mixkit.co/sfx/preview/mixkit-positive-notification-951.mp3",
        "https://assets.mixkit.co/sfx/preview/mixkit-arcade-game-jump-coin-216.mp3",
        "https://assets.mixkit.co/sfx/preview/mixkit-software-interface-start-2574.mp3",
    ],
}

OUTPUT_DIR = Path("/app/assets/sounds")


async def download_audio(url: str, category: str) -> bool:
    """Download audio file from Mixkit CDN."""
    # Extract filename from URL
    filename = url.split("/")[-1]
    
    output_path = OUTPUT_DIR / category / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Skip if exists
    if output_path.exists():
        print(f"⏭️  Skipping (exists): {filename}")
        return True
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            
            if response.status_code == 200:
                output_path.write_bytes(response.content)
                size_kb = len(response.content) / 1024
                print(f"✅ Downloaded: {filename} ({size_kb:.1f} KB)")
                return True
            else:
                print(f"❌ Download failed: {filename} (HTTP {response.status_code})")
                return False
                
    except Exception as e:
        print(f"❌ Download error for {filename}: {e}")
        return False


async def download_category(category_name: str, urls: list) -> int:
    """Download all files in a category."""
    print(f"\n📁 Category: {category_name}")
    
    downloaded = 0
    
    for url in urls:
        success = await download_audio(url, category_name)
        if success:
            downloaded += 1
        
        # Be nice to Mixkit's CDN
        await asyncio.sleep(0.5)
    
    print(f"   ✅ Downloaded {downloaded}/{len(urls)} files")
    return downloaded


async def main():
    """Download audio library from Mixkit."""
    print("\n" + "="*60)
    print("Downloading Audio Library from Mixkit")
    print("="*60)
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    total_downloaded = 0
    
    # Download music
    print("\n🎵 Downloading Background Music (BGM)")
    print("-" * 60)
    
    for category, urls in MIXKIT_MUSIC_URLS.items():
        count = await download_category(category, urls)
        total_downloaded += count
    
    # Download SFX
    print("\n🔊 Downloading Sound Effects (SFX)")
    print("-" * 60)
    
    for category, urls in MIXKIT_SFX_URLS.items():
        count = await download_category(category, urls)
        total_downloaded += count
    
    # Summary
    print("\n" + "="*60)
    print("DOWNLOAD COMPLETE")
    print("="*60)
    print(f"Total files downloaded: {total_downloaded}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("\n✅ Mixkit audio ready!")


if __name__ == "__main__":
    asyncio.run(main())
