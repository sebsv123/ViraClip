#!/usr/bin/env python3
"""
Simple audio library expansion using urllib (no external deps)
Downloads free SFX and BGM from GitHub and Pixabay
"""
import os
import urllib.request
from pathlib import Path


def download_file(url: str, dest: Path) -> bool:
    """Download a file using urllib"""
    try:
        print(f"Downloading {dest.name}...")
        urllib.request.urlretrieve(url, dest)
        return True
    except Exception as e:
        print(f"  Failed: {e}")
        return False


def main():
    # Audio library path
    audio_path = Path("/app/assets/sounds")
    sfx_path = audio_path / "sfx"
    bgm_path = audio_path / "bgm"
    
    sfx_path.mkdir(parents=True, exist_ok=True)
    bgm_path.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("ViraClip Audio Library Expansion")
    print("=" * 60)
    
    # Free SFX from GitHub (arnofaure/free-sfx)
    sfx_downloads = {
        "whoosh_01.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Whoosh/whoosh_01.mp3",
        "whoosh_02.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Whoosh/whoosh_02.mp3",
        "impact_01.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Impact/impact_01.mp3",
        "impact_02.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Impact/impact_02.mp3",
        "bass_drop.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Impact/bass_drop.mp3",
        "glitch_01.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Transition/glitch_01.mp3",
        "swipe_01.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Transition/swipe_01.mp3",
        "pop.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/UI/pop.mp3",
        "ding.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/UI/ding.mp3",
        "tension.mp3": "https://github.com/arnofaure/free-sfx/raw/master/SFX/Ambient/tension.mp3",
    }
    
    print(f"\nDownloading {len(sfx_downloads)} SFX files...")
    success_count = 0
    for filename, url in sfx_downloads.items():
        dest = sfx_path / filename
        if not dest.exists():
            if download_file(url, dest):
                success_count += 1
        else:
            print(f"Skipping {filename} (already exists)")
            success_count += 1
    
    print(f"\nSFX: {success_count}/{len(sfx_downloads)} files")
    
    # Check existing BGM
    existing_bgm = list(bgm_path.glob("*.mp3"))
    print(f"BGM: {len(existing_bgm)} files already present")
    
    print("\n" + "=" * 60)
    print(f"Audio Library Status:")
    print(f"  SFX: {len(list(sfx_path.glob('*.mp3')))} files")
    print(f"  BGM: {len(list(bgm_path.glob('*.mp3')))} files")
    print("=" * 60)
    
    print("\nNote: For more audio files, download from:")
    print("  - Mixkit: https://mixkit.co/free-sound-effects/")
    print("  - Pixabay: https://pixabay.com/sound-effects/")
    print("  - FreeSFX: https://www.freesfx.co.uk/")


if __name__ == "__main__":
    main()
