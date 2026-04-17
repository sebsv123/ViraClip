"""
Download audio files from Pixabay

Pixabay offers 200,000+ royalty-free music tracks and sound effects.
Free tier: 100 requests/minute

Categories:
- Music (BGM): cinematic, corporate, happy, chill, dramatic, etc.
- Sound Effects: transitions, impacts, ambient, UI sounds
"""

import asyncio
import json
import os
from pathlib import Path
import httpx
import hashlib


# Audio categories to download
MUSIC_CATEGORIES = {
    "viral_hype": ["energetic", "upbeat", "intense", "powerful"],
    "cinematic": ["cinematic", "dramatic", "epic", "tension"],
    "lofi_chill": ["chill", "lo-fi", "relaxing", "ambient"],
    "corporate": ["corporate", "inspirational", "uplifting", "positive"],
    "emotional": ["emotional", "sentimental", "sad", "hopeful"],
}

SFX_CATEGORIES = {
    "transitions": ["whoosh", "swipe", "transition", "glitch"],
    "impacts": ["impact", "boom", "punch", "hit"],
    "ui_sounds": ["click", "pop", "ding", "notification"],
    "ambient": ["ambient", "nature", "city", "room tone"],
}

# Pixabay API configuration
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
PIXABAY_BASE_URL = "https://pixabay.com/api/"
OUTPUT_DIR = Path("/app/assets/sounds")


async def search_pixabay_audio(
    query: str,
    audio_type: str = "music",
    per_page: int = 10
) -> list:
    """
    Search Pixabay for audio files.
    
    Args:
        query: Search term
        audio_type: "music" or "effects"
        per_page: Results per page (max 200)
        
    Returns:
        List of audio items
    """
    if not PIXABAY_API_KEY:
        print("⚠️ PIXABAY_API_KEY not set, skipping Pixabay")
        return []
    
    url = f"{PIXABAY_BASE_URL}?key={PIXABAY_API_KEY}"
    params = {
        "q": query,
        "audio_type": audio_type,
        "per_page": per_page,
        "safesearch": "true",
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(PIXABAY_BASE_URL, params=params)
            
            if response.status_code == 200:
                data = response.json()
                return data.get("hits", [])
            else:
                print(f"❌ Pixabay API error {response.status_code}")
                return []
                
    except Exception as e:
        print(f"❌ Pixabay search failed: {e}")
        return []


async def download_audio_file(
    url: str,
    filename: str,
    category: str
) -> bool:
    """Download audio file from URL."""
    output_path = OUTPUT_DIR / category / filename
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Skip if already exists
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


async def download_category(
    category_name: str,
    keywords: list,
    audio_type: str,
    target_count: int = 10
) -> int:
    """
    Download audio files for a category.
    
    Args:
        category_name: Category folder name
        keywords: List of search keywords
        audio_type: "music" or "effects"
        target_count: Target number of files to download
        
    Returns:
        Number of files downloaded
    """
    print(f"\n📁 Category: {category_name} ({audio_type})")
    print(f"   Keywords: {', '.join(keywords)}")
    
    downloaded = 0
    seen_urls = set()
    
    for keyword in keywords:
        if downloaded >= target_count:
            break
        
        print(f"   Searching: {keyword}...")
        results = await search_pixabay_audio(keyword, audio_type, per_page=5)
        
        for item in results:
            if downloaded >= target_count:
                break
            
            # Get download URL (prefer 128k MP3)
            download_url = item.get("previewURL")  # Free tier gets preview URL
            
            if not download_url or download_url in seen_urls:
                continue
            
            seen_urls.add(download_url)
            
            # Generate filename
            tags = item.get("tags", keyword)
            duration = item.get("duration", 0)
            file_id = hashlib.md5(download_url.encode()).hexdigest()[:8]
            filename = f"{category_name}_{tags.replace(' ', '_')}_{duration}s_{file_id}.mp3"
            filename = filename.replace(",", "_")  # Clean filename
            
            # Download
            success = await download_audio_file(download_url, filename, category_name)
            if success:
                downloaded += 1
        
        # Rate limiting
        await asyncio.sleep(0.6)  # 100 requests/min = 1 per 0.6s
    
    print(f"   ✅ Downloaded {downloaded}/{target_count} files")
    return downloaded


async def main():
    """Download audio library from Pixabay."""
    print("\n" + "="*60)
    print("Downloading Audio Library from Pixabay")
    print("="*60)
    
    if not PIXABAY_API_KEY:
        print("\n❌ ERROR: PIXABAY_API_KEY not configured")
        print("Get your free API key at: https://pixabay.com/api/docs/")
        return
    
    # Create output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    total_downloaded = 0
    
    # Download music (BGM)
    print("\n🎵 Downloading Background Music (BGM)")
    print("-" * 60)
    
    for category, keywords in MUSIC_CATEGORIES.items():
        count = await download_category(category, keywords, "music", target_count=10)
        total_downloaded += count
    
    # Download sound effects (SFX)
    print("\n🔊 Downloading Sound Effects (SFX)")
    print("-" * 60)
    
    for category, keywords in SFX_CATEGORIES.items():
        count = await download_category(category, keywords, "effects", target_count=10)
        total_downloaded += count
    
    # Generate index
    print("\n📝 Generating audio index...")
    await generate_audio_index()
    
    # Summary
    print("\n" + "="*60)
    print("DOWNLOAD COMPLETE")
    print("="*60)
    print(f"Total files downloaded: {total_downloaded}")
    print(f"Output directory: {OUTPUT_DIR}")
    print("\n✅ Audio library ready!")


async def generate_audio_index():
    """Generate JSON index of all downloaded files."""
    index = {
        "bgm": {},
        "sfx": {},
        "total_count": 0,
    }
    
    # Scan all categories
    for category_name in list(MUSIC_CATEGORIES.keys()) + list(SFX_CATEGORIES.keys()):
        category_dir = OUTPUT_DIR / category_name
        
        if not category_dir.exists():
            continue
        
        files = list(category_dir.glob("*.mp3"))
        
        if files:
            category_type = "bgm" if category_name in MUSIC_CATEGORIES else "sfx"
            index[category_type][category_name] = [f.name for f in files]
            index["total_count"] += len(files)
    
    # Write index
    index_path = OUTPUT_DIR / "audio_index.json"
    index_path.write_text(json.dumps(index, indent=2))
    
    print(f"✅ Audio index saved: {index_path}")
    print(f"   Total indexed: {index['total_count']} files")


if __name__ == "__main__":
    asyncio.run(main())
