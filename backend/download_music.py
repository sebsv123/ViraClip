"""
Download CC0-licensed background music tracks from Free Music Archive and ccMixter.
Run once: python backend/download_music.py
"""
import urllib.request
import urllib.error
import json
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "music" / "bgm"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# CC0 tracks from Free Music Archive (direct mp3 download URLs, verified CC0)
# Source: https://freemusicarchive.org (CC0 1.0 Universal)
TRACKS = [
    {
        "filename": "lofi_chill.mp3",
        "url": "https://archive.org/download/Aural-Tradition-EP/He-Was-a-Friend-of-Mine.mp3",
        "artist": "RC & the Commons",
        "title": "He Was a Friend of Mine",
        "license": "CC0 1.0",
        "source": "https://archive.org/details/Aural-Tradition-EP",
    },
    {
        "filename": "upbeat_energy.mp3",
        "url": "https://archive.org/download/Aural-Tradition-EP/More-Pretty-Girls-Than-One.mp3",
        "artist": "RC & the Commons",
        "title": "More Pretty Girls Than One",
        "license": "CC0 1.0",
        "source": "https://archive.org/details/Aural-Tradition-EP",
    },
    {
        "filename": "corporate_clean.mp3",
        "url": "https://archive.org/download/Aural-Tradition-EP/Been-All-Around-This-World.mp3",
        "artist": "RC & the Commons",
        "title": "Been All Around This World",
        "license": "CC0 1.0",
        "source": "https://archive.org/details/Aural-Tradition-EP",
    },
    {
        "filename": "cinematic_build.mp3",
        "url": "https://archive.org/download/desert-sand-feels-warm-at-night-dream-desert/desert%20sand%20feels%20warm%20at%20night%20-%20desert%20sand%20feels%20warm%20at%20night%20-%20%E5%A4%A2%E3%81%AE%E7%A0%82%E6%BC%A0%20-%2006%20%E7%A0%82%E7%B2%92.mp3",
        "artist": "Desert Sand Feels Warm At Night",
        "title": "Dream Desert 06 (ambient)",
        "license": "CC0 1.0",
        "source": "https://archive.org/details/desert-sand-feels-warm-at-night-dream-desert",
    },
    {
        "filename": "minimal_ambient.mp3",
        "url": "https://archive.org/download/desert-sand-feels-warm-at-night-dream-desert/desert%20sand%20feels%20warm%20at%20night%20-%20desert%20sand%20feels%20warm%20at%20night%20-%20%E5%A4%A2%E3%81%AE%E7%A0%82%E6%BC%A0%20-%2001%20%E6%8C%87%E3%82%92%E6%B5%81%E3%82%8C%E3%82%8B%E7%A0%82.mp3",
        "artist": "Desert Sand Feels Warm At Night",
        "title": "Dream Desert 01 (ambient)",
        "license": "CC0 1.0",
        "source": "https://archive.org/details/desert-sand-feels-warm-at-night-dream-desert",
    },
]


def download_track(track: dict) -> bool:
    out_path = OUTPUT_DIR / track["filename"]
    if out_path.exists() and out_path.stat().st_size > 50_000:
        print(f"  SKIP {track['filename']} already exists ({out_path.stat().st_size // 1024}KB)")
        return True
    print(f"  >> Downloading {track['title']} by {track['artist']} ...")
    try:
        req = urllib.request.Request(track["url"], headers={"User-Agent": "ViraClip/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        out_path.write_bytes(data)
        print(f"  OK Saved {track['filename']} ({len(data) // 1024}KB)")
        return True
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def write_sources_md(results: list) -> None:
    lines = ["# CC0 Background Music Sources\n",
             "All tracks are CC0 1.0 Universal — no attribution required, commercial use allowed.\n",
             "Downloaded: see dates in git log.\n\n",
             "| File | Title | Artist | License | Source |\n",
             "|------|-------|--------|---------|--------|\n"]
    for track, ok in zip(TRACKS, results):
        status = "✓" if ok else "✗ MISSING"
        lines.append(
            f"| {track['filename']} | {track['title']} | {track['artist']} "
            f"| {track['license']} | {status} | {track['source']} |\n"
        )
    sources_path = OUTPUT_DIR / "SOURCES.md"
    sources_path.write_text("".join(lines), encoding="utf-8")
    print(f"\n  SOURCES.md written to {sources_path}")


if __name__ == "__main__":
    print(f"Downloading CC0 background music to {OUTPUT_DIR} ...\n")
    results = [download_track(t) for t in TRACKS]
    write_sources_md(results)
    ok = sum(results)
    print(f"\n{ok}/{len(TRACKS)} tracks downloaded.")
    if ok == 0:
        print("ERROR: No tracks downloaded. Check internet connection.")

        sys.exit(1)
    elif ok < len(TRACKS):
        print("WARNING: Some tracks failed — partial music library.")
        sys.exit(0)
    else:
        print("All tracks ready.")
