"""
download_freesound.py — Phase 2.5
===================================
Downloads CC0-licensed SFX from Freesound.org API and saves them to the
local SFX library used by ClapSfxService.

Usage:
    python scripts/download_freesound.py --help
    python scripts/download_freesound.py --preset viral_tiktok
    python scripts/download_freesound.py --query "whoosh" --count 10
    python scripts/download_freesound.py --status

Requirements:
    FREESOUND_API_KEY env var (get free key at https://freesound.org/apiv2/apply/)

Fallback (no API key):
    Downloads a curated list of hand-picked CC0 sounds from freesound.org public
    CDN links — useful for initial bootstrap without registration.
"""

import os
import sys
import json
import logging
import argparse
import asyncio
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SFX_DIR = Path(os.getenv("SFX_LIBRARY_PATH", "/app/assets/sfx_library"))
API_BASE = "https://freesound.org/apiv2"

# ─── Pre-defined search queries grouped by usage type ────────────────────────
SFX_PRESETS = {
    "viral_tiktok": [
        ("whoosh fast", 8),
        ("bass boom impact", 6),
        ("tension riser", 5),
        ("glitch distortion", 5),
        ("ding chime notification", 6),
        ("punch hit impact", 6),
        ("swoosh heavy", 5),
        ("comedic pop", 4),
        ("dramatic drum hit", 4),
        ("air horn", 3),
    ],
    "minimal": [
        ("whoosh", 5),
        ("impact hit", 5),
        ("chime bell", 5),
    ],
}

# ─── Hard-coded fallback CC0 sounds (no API key needed) ──────────────────────
FALLBACK_SOUNDS = [
    {
        "id": "539239",
        "name": "whoosh_fast",
        "filename": "whoosh_fast.mp3",
        "description": "Fast whoosh SFX CC0",
    },
    {
        "id": "362204",
        "name": "bass_boom",
        "filename": "bass_boom.mp3",
        "description": "Bass boom impact CC0",
    },
    {
        "id": "352661",
        "name": "tension_riser",
        "filename": "tension_riser.mp3",
        "description": "Tension riser CC0",
    },
    {
        "id": "341695",
        "name": "ding_chime",
        "filename": "ding_chime.mp3",
        "description": "Ding chime CC0",
    },
    {
        "id": "573381",
        "name": "punch_impact",
        "filename": "punch_impact.mp3",
        "description": "Punch impact hit CC0",
    },
]


# ─── Freesound API client ─────────────────────────────────────────────────────

async def search_freesound(
    query: str,
    count: int = 5,
    api_key: str = "",
) -> list[dict]:
    """Search Freesound for CC0-licensed sounds matching the query."""
    try:
        import httpx

        params = {
            "query": query,
            "filter": "license:\"Creative Commons 0\"",
            "fields": "id,name,previews,license,description,duration,tags",
            "page_size": count,
            "token": api_key,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{API_BASE}/search/text/", params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except Exception as e:
        logger.warning(f"Freesound search failed for '{query}': {e}")
        return []


async def download_sound(
    sound_id: int,
    filename: str,
    api_key: str = "",
    output_dir: Path = SFX_DIR,
) -> Optional[Path]:
    """Download a single sound preview (HQ MP3) from Freesound."""
    try:
        import httpx

        # Fetch sound details to get preview URL
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{API_BASE}/sounds/{sound_id}/",
                params={"token": api_key},
            )
            resp.raise_for_status()
            sound = resp.json()

        # Use HQ preview (MP3 ~128kbps) — doesn't need OAuth
        preview_url = sound.get("previews", {}).get("preview-hq-mp3")
        if not preview_url:
            logger.warning(f"No preview URL for sound {sound_id}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / filename

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(preview_url)
            resp.raise_for_status()
            out_path.write_bytes(resp.content)

        size_kb = out_path.stat().st_size // 1024
        logger.info(f"  ✓ Downloaded: {filename} ({size_kb} KB)")
        return out_path

    except Exception as e:
        logger.warning(f"  ✗ Failed to download sound {sound_id}: {e}")
        return None


async def download_preset(preset_name: str = "viral_tiktok", api_key: str = "") -> dict:
    """Download all sounds for a preset."""
    queries = SFX_PRESETS.get(preset_name)
    if not queries:
        logger.error(f"Unknown preset '{preset_name}'. Options: {list(SFX_PRESETS)}")
        return {}

    logger.info(f"Downloading preset '{preset_name}' ({sum(c for _, c in queries)} sounds target)...")
    results = {"downloaded": 0, "skipped": 0, "failed": 0, "paths": []}

    for query, count in queries:
        logger.info(f"\n→ Searching: '{query}' (up to {count})...")
        sounds = await search_freesound(query, count=count, api_key=api_key)

        for i, sound in enumerate(sounds[:count]):
            sound_id = sound["id"]
            safe_name = query.replace(" ", "_")[:20]
            filename = f"{safe_name}_{i:02d}_{sound_id}.mp3"
            out_path = SFX_DIR / filename

            if out_path.exists():
                logger.info(f"  → Skipped (exists): {filename}")
                results["skipped"] += 1
                results["paths"].append(str(out_path))
                continue

            path = await download_sound(sound_id, filename, api_key=api_key)
            if path:
                results["downloaded"] += 1
                results["paths"].append(str(path))
            else:
                results["failed"] += 1

    return results


async def download_fallback_sounds() -> dict:
    """Download hand-picked CC0 sounds without API key."""
    logger.info("Downloading fallback CC0 sounds (no API key required)...")
    results = {"downloaded": 0, "skipped": 0, "failed": 0}

    try:
        import httpx

        SFX_DIR.mkdir(parents=True, exist_ok=True)

        for sound in FALLBACK_SOUNDS:
            out_path = SFX_DIR / sound["filename"]
            if out_path.exists():
                logger.info(f"  → Skipped (exists): {sound['filename']}")
                results["skipped"] += 1
                continue

            # Try downloading preview directly via freesound CDN
            url = f"https://freesound.org/data/previews/{sound['id'][:3]}/{sound['id']}/{sound['id']}-hq.mp3"
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url, follow_redirects=True)
                    if resp.status_code == 200:
                        out_path.write_bytes(resp.content)
                        size_kb = out_path.stat().st_size // 1024
                        logger.info(f"  ✓ {sound['filename']} ({size_kb} KB)")
                        results["downloaded"] += 1
                    else:
                        logger.warning(f"  ✗ HTTP {resp.status_code} for {sound['filename']}")
                        results["failed"] += 1
            except Exception as e:
                logger.warning(f"  ✗ {sound['filename']}: {e}")
                results["failed"] += 1

    except ImportError:
        logger.error("httpx not available. Install with: pip install httpx")
        return results

    return results


def print_status():
    """Show current SFX library status."""
    if not SFX_DIR.exists():
        print(f"SFX library directory not found: {SFX_DIR}")
        return

    sounds = list(SFX_DIR.glob("*.mp3")) + list(SFX_DIR.glob("*.wav"))
    total_size = sum(f.stat().st_size for f in sounds) // (1024 * 1024)

    print(f"\n📁 SFX Library: {SFX_DIR}")
    print(f"   Files:      {len(sounds)}")
    print(f"   Total size: {total_size} MB")

    # Check CLAP embeddings cache
    cache_file = SFX_DIR / "embeddings_cache.json"
    if cache_file.exists():
        cache = json.loads(cache_file.read_text())
        print(f"   CLAP cache: {len(cache)} embeddings")
    else:
        print("   CLAP cache: none (run after download to build cache)")

    if sounds:
        print(f"\n   Last 5 files:")
        for f in sorted(sounds)[-5:]:
            size_kb = f.stat().st_size // 1024
            print(f"     {f.name:<40} {size_kb:>5} KB")


def main():
    parser = argparse.ArgumentParser(
        description="Download CC0 SFX from Freesound.org for ViraClip CLAP matching"
    )
    parser.add_argument("--preset", default="viral_tiktok",
                        choices=list(SFX_PRESETS), help="Sound preset to download")
    parser.add_argument("--query", help="Single search query (overrides preset)")
    parser.add_argument("--count", type=int, default=5, help="Sounds per query")
    parser.add_argument("--status", action="store_true", help="Show library status")
    parser.add_argument("--fallback", action="store_true",
                        help="Download fallback sounds without API key")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    api_key = os.getenv("FREESOUND_API_KEY", "")

    if args.fallback or not api_key:
        if not api_key:
            logger.warning("FREESOUND_API_KEY not set — using fallback downloads")
        result = asyncio.run(download_fallback_sounds())
    elif args.query:
        async def _single():
            sounds = await search_freesound(args.query, args.count, api_key)
            downloaded = 0
            for i, s in enumerate(sounds):
                fn = f"{args.query.replace(' ', '_')}_{i:02d}_{s['id']}.mp3"
                if await download_sound(s["id"], fn, api_key):
                    downloaded += 1
            return {"downloaded": downloaded}
        result = asyncio.run(_single())
    else:
        result = asyncio.run(download_preset(args.preset, api_key))

    print(f"\n✅ Done: {result.get('downloaded', 0)} downloaded, "
          f"{result.get('skipped', 0)} skipped, "
          f"{result.get('failed', 0)} failed")
    print(f"📁 SFX library: {SFX_DIR}")
    print("💡 Next: rebuild CLAP embeddings cache with clap_sfx_service.py build_cache()")


if __name__ == "__main__":
    main()
