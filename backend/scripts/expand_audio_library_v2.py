"""
Audio Library Expansion Script v2

Orchestrates audio downloads from multiple sources:
1. Pixabay (200,000+ tracks, requires API key)
2. Mixkit (5,000+ tracks, no API key needed)
3. Existing local files

Generates unified index and verifies no duplicates.

Target: 50 BGM + 50 SFX = 100 total files
"""

import asyncio
import json
import hashlib
from pathlib import Path
import subprocess
import sys


OUTPUT_DIR = Path("/app/assets/sounds")
INDEX_FILE = OUTPUT_DIR / "audio_index.json"


async def run_downloader(script_name: str) -> bool:
    """Run a downloader script."""
    script_path = Path(__file__).parent / script_name
    
    print(f"\n{'='*60}")
    print(f"Running: {script_name}")
    print(f"{'='*60}")
    
    try:
        # Run script
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            print(stdout.decode())
            print(f"✅ {script_name} completed successfully")
            return True
        else:
            print(f"❌ {script_name} failed:")
            print(stderr.decode())
            return False
            
    except Exception as e:
        print(f"❌ Error running {script_name}: {e}")
        return False


def scan_audio_files() -> dict:
    """Scan all audio files and categorize them."""
    index = {
        "bgm": {},
        "sfx": {},
        "total_count": 0,
        "by_category": {},
    }
    
    if not OUTPUT_DIR.exists():
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        return index
    
    # Scan all subdirectories
    for category_dir in OUTPUT_DIR.iterdir():
        if not category_dir.is_dir():
            continue
        
        category_name = category_dir.name
        files = list(category_dir.glob("*.mp3"))
        
        if not files:
            continue
        
        # Categorize as BGM or SFX based on folder name
        is_sfx = any(kw in category_name.lower() for kw in [
            "transition", "impact", "ui", "ambient", "sfx", "sound"
        ])
        
        category_type = "sfx" if is_sfx else "bgm"
        
        # Add to index
        if category_name not in index[category_type]:
            index[category_type][category_name] = []
        
        for file_path in files:
            file_info = {
                "filename": file_path.name,
                "size_kb": file_path.stat().st_size / 1024,
                "path": str(file_path.relative_to(OUTPUT_DIR)),
            }
            index[category_type][category_name].append(file_info)
            index["total_count"] += 1
        
        index["by_category"][category_name] = len(files)
    
    return index


def remove_duplicates() -> int:
    """Remove duplicate files based on content hash."""
    print("\n🔍 Checking for duplicates...")
    
    seen_hashes = {}
    duplicates_removed = 0
    
    for audio_file in OUTPUT_DIR.rglob("*.mp3"):
        # Calculate hash
        with open(audio_file, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()
        
        if file_hash in seen_hashes:
            # Duplicate found
            print(f"   Removing duplicate: {audio_file.name}")
            audio_file.unlink()
            duplicates_removed += 1
        else:
            seen_hashes[file_hash] = audio_file
    
    if duplicates_removed > 0:
        print(f"✅ Removed {duplicates_removed} duplicate files")
    else:
        print("✅ No duplicates found")
    
    return duplicates_removed


def print_summary(index: dict):
    """Print download summary."""
    print("\n" + "="*60)
    print("AUDIO LIBRARY SUMMARY")
    print("="*60)
    
    # BGM breakdown
    print("\n🎵 Background Music (BGM):")
    bgm_total = 0
    for category, files in index["bgm"].items():
        count = len(files)
        bgm_total += count
        print(f"   - {category}: {count} files")
    print(f"   TOTAL BGM: {bgm_total}")
    
    # SFX breakdown
    print("\n🔊 Sound Effects (SFX):")
    sfx_total = 0
    for category, files in index["sfx"].items():
        count = len(files)
        sfx_total += count
        print(f"   - {category}: {count} files")
    print(f"   TOTAL SFX: {sfx_total}")
    
    # Grand total
    print(f"\n📊 GRAND TOTAL: {index['total_count']} files")
    print(f"   Target: 100 files (50 BGM + 50 SFX)")
    
    if index["total_count"] >= 100:
        print("\n✅ TARGET REACHED!")
    else:
        remaining = 100 - index["total_count"]
        print(f"\n⚠️ {remaining} files short of target")


async def main():
    """Main orchestration function."""
    print("\n" + "#"*60)
    print("# ViraClip Audio Library Expansion v2")
    print("#"*60)
    
    # Step 1: Download from Pixabay
    print("\n📥 Step 1: Downloading from Pixabay")
    await run_downloader("download_pixabay_audio.py")
    
    # Step 2: Download from Mixkit
    print("\n📥 Step 2: Downloading from Mixkit")
    await run_downloader("download_mixkit_audio.py")
    
    # Step 3: Remove duplicates
    print("\n🧹 Step 3: Removing duplicates")
    remove_duplicates()
    
    # Step 4: Scan and index all files
    print("\n📝 Step 4: Generating unified index")
    index = scan_audio_files()
    
    # Write index
    INDEX_FILE.write_text(json.dumps(index, indent=2))
    print(f"✅ Index saved: {INDEX_FILE}")
    
    # Step 5: Print summary
    print_summary(index)
    
    print("\n" + "="*60)
    print("✅ AUDIO LIBRARY EXPANSION COMPLETE!")
    print("="*60)
    print(f"\nOutput directory: {OUTPUT_DIR}")
    print(f"Index file: {INDEX_FILE}")
    print("\n💡 Tip: Add more sources to reach 100+ files:")
    print("   - Incompetech (Kevin MacLeod)")
    print("   - YouTube Audio Library (via yt-dlp)")
    print("   - Free Music Archive")


if __name__ == "__main__":
    asyncio.run(main())
