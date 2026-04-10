#!/usr/bin/env python3
"""
B-Roll Asset Bank Seeder
========================
Downloads ~60 portrait B-roll clips from Pexels + Coverr into
/app/assets/broll/<category>/ (or BROLL_ASSET_BANK env var).

Run once to pre-populate the local asset bank so that
contextual_broll.py::_find_local() hits on the first lookup
for common keywords.

Usage:
    python scripts/seed_broll_bank.py
    # or inside Docker:
    docker exec <worker> python scripts/seed_broll_bank.py

Requirements:
    PEXELS_API_KEY   — used for video downloads
    COVERR_API_KEY   — optional, supplements Pexels
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("seed_broll")

ASSET_BANK = Path(os.environ.get("BROLL_ASSET_BANK", "/app/assets/broll"))
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "")
COVERR_KEY = os.environ.get("COVERR_API_KEY", "")
TARGET_DURATION = 6.0   # seconds per clip
CLIPS_PER_CAT   = 3     # clips to download per category
TIMEOUT         = httpx.Timeout(60.0)

CATEGORIES: dict[str, list[str]] = {
    "nature":     ["nature", "forest", "ocean", "mountain", "sunset"],
    "city":       ["city", "street", "skyline", "traffic", "urban"],
    "business":   ["business", "office", "meeting", "work", "laptop"],
    "tech":       ["technology", "computer", "coding", "robot", "data"],
    "food":       ["food", "cooking", "restaurant", "coffee", "fruits"],
    "sport":      ["sport", "gym", "running", "fitness", "exercise"],
    "travel":     ["travel", "airplane", "beach", "map", "adventure"],
    "people":     ["people", "crowd", "woman", "man", "friends"],
    "finance":    ["money", "finance", "stock market", "bank", "coins"],
    "motivation": ["motivation", "success", "goal", "achievement", "team"],
    "abstract":   ["abstract", "light", "blur", "particles", "motion"],
    "health":     ["health", "doctor", "medicine", "wellness", "hospital"],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _crop_to_portrait(src: Path, dest: Path, duration: float = TARGET_DURATION) -> bool:
    """FFmpeg: crop to 9:16, scale to 1080×1920, mute audio, trim."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-t", str(duration),
        "-vf", (
            "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
            "scale=1080:1920:force_original_aspect_ratio=disable,"
            "setsar=1"
        ),
        "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(dest),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        return r.returncode == 0 and dest.exists() and dest.stat().st_size > 10_000
    except Exception as exc:
        logger.debug("FFmpeg crop failed: %s", exc)
        return False


async def _search_pexels(keyword: str, client: httpx.AsyncClient) -> list[str]:
    if not PEXELS_KEY:
        return []
    try:
        resp = await client.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_KEY},
            params={"query": keyword, "per_page": 5, "orientation": "portrait"},
        )
        resp.raise_for_status()
        urls = []
        for video in resp.json().get("videos", []):
            for vf in video.get("video_files", []):
                if vf.get("file_type") == "video/mp4" and vf.get("height", 0) >= 720:
                    urls.append(vf["link"])
                    break
        return urls[:CLIPS_PER_CAT]
    except Exception as exc:
        logger.debug("Pexels error for '%s': %s", keyword, exc)
        return []


async def _search_coverr(keyword: str, client: httpx.AsyncClient) -> list[str]:
    if not COVERR_KEY:
        return []
    try:
        resp = await client.get(
            "https://api.coverr.co/videos",
            params={"keywords": keyword, "token": COVERR_KEY, "per_page": 5},
        )
        resp.raise_for_status()
        urls = []
        for item in resp.json().get("hits", []):
            url = item.get("urls", {}).get("mp4_download") or item.get("url")
            if url:
                urls.append(url)
        return urls[:CLIPS_PER_CAT]
    except Exception as exc:
        logger.debug("Coverr error for '%s': %s", keyword, exc)
        return []


async def _download_url(url: str, dest: Path, client: httpx.AsyncClient) -> bool:
    try:
        async with client.stream("GET", url, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in resp.aiter_bytes(8192):
                    f.write(chunk)
        return dest.exists() and dest.stat().st_size > 50_000
    except Exception as exc:
        logger.debug("Download failed %s: %s", url[:60], exc)
        dest.unlink(missing_ok=True)
        return False


async def seed_category(cat: str, keywords: list[str], client: httpx.AsyncClient) -> int:
    cat_dir = ASSET_BANK / cat
    cat_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    for kw in keywords:
        if downloaded >= CLIPS_PER_CAT:
            break

        safe_kw = "".join(c if c.isalnum() else "_" for c in kw).lower()
        dest = cat_dir / f"{safe_kw}.mp4"

        if dest.exists() and dest.stat().st_size > 50_000:
            logger.info("  [skip] %s/%s.mp4 (already exists)", cat, safe_kw)
            downloaded += 1
            continue

        # Search Pexels + Coverr in parallel
        pexels_urls, coverr_urls = await asyncio.gather(
            _search_pexels(kw, client),
            _search_coverr(kw, client),
        )
        urls = pexels_urls + coverr_urls

        for url in urls:
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = Path(tmp.name)

            ok_dl = await _download_url(url, tmp_path, client)
            if not ok_dl:
                tmp_path.unlink(missing_ok=True)
                continue

            ok_crop = _crop_to_portrait(tmp_path, dest)
            tmp_path.unlink(missing_ok=True)

            if ok_crop:
                size_kb = dest.stat().st_size // 1024
                logger.info("  [ok]   %s/%s.mp4 (%d KB)", cat, safe_kw, size_kb)
                downloaded += 1
                break
            else:
                dest.unlink(missing_ok=True)

    return downloaded


async def main() -> None:
    if not PEXELS_KEY and not COVERR_KEY:
        logger.error("Set PEXELS_API_KEY and/or COVERR_API_KEY before running this script.")
        sys.exit(1)

    ASSET_BANK.mkdir(parents=True, exist_ok=True)
    logger.info("Seeding B-roll bank at: %s", ASSET_BANK)
    logger.info("Sources: Pexels=%s, Coverr=%s",
                "yes" if PEXELS_KEY else "no",
                "yes" if COVERR_KEY else "no")

    total = 0
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for cat, keywords in CATEGORIES.items():
            logger.info("Category: %s", cat)
            count = await seed_category(cat, keywords, client)
            total += count
            logger.info("  → %d clip(s) ready", count)

    logger.info("\nDone. Total clips seeded: %d", total)


if __name__ == "__main__":
    asyncio.run(main())
