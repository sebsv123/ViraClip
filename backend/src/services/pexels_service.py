"""
Pexels B-Roll Service — Feature A
Async prefetch of CC-licensed vertical video clips from Pexels.
Crops 16:9 → 9:16, mutes original audio, ready for overlay.
Requires PEXELS_API_KEY and BROLL_ENABLED=true in env.
"""
import asyncio
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
import httpx
from .broll_compositor import compose_overlay

logger = logging.getLogger(__name__)

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
_TIMEOUT = httpx.Timeout(30.0)


async def search_pexels_broll(
    keyword: str,
    api_key: str,
    max_results: int = 3,
) -> list[dict]:
    """
    Search Pexels for portrait-friendly video clips matching keyword.
    Returns list of dicts with 'id', 'url', 'duration', 'width', 'height'.
    """
    params = {
        "query": keyword,
        "orientation": "portrait",
        "size": "medium",
        "per_page": max(max_results, 5),
    }
    headers = {"Authorization": api_key}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(PEXELS_VIDEO_SEARCH, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning(f"[Pexels] Search failed for '{keyword}': {exc}")
        return []

    results = []
    for video in data.get("videos", [])[:max_results]:
        best_file = _pick_best_file(video.get("video_files", []))
        if best_file:
            results.append({
                "id": video["id"],
                "url": best_file["link"],
                "duration": video.get("duration", 0),
                "width": best_file.get("width", 0),
                "height": best_file.get("height", 0),
            })
    logger.info(f"[Pexels] '{keyword}': {len(results)} clips found")
    return results


def _pick_best_file(video_files: list[dict]) -> Optional[dict]:
    """Pick the best quality portrait or landscape HD file."""
    portrait = [f for f in video_files if f.get("quality") == "hd"
                and f.get("height", 0) >= 720]
    if portrait:
        return sorted(portrait, key=lambda f: f.get("height", 0), reverse=True)[0]
    hd = [f for f in video_files if f.get("quality") in ("hd", "sd")]
    if hd:
        return hd[0]
    return video_files[0] if video_files else None


async def download_and_crop_broll(
    video_url: str,
    output_path: Path,
    target_duration: float = 10.0,
) -> bool:
    """
    Download a Pexels clip, crop to 9:16 (1080×1920), mute audio,
    and trim to target_duration seconds.
    Returns True on success.
    """
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Download
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            tmp_path.write_bytes(resp.content)

        # Crop 16:9 → 9:16 and mute using FFmpeg
        # vf: crop the tallest centered 9:16 slice, then scale to 1080×1920
        cmd = [
            "ffmpeg", "-y",
            "-i", str(tmp_path),
            "-t", str(target_duration),
            "-vf", (
                "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,"
                "scale=1080:1920:force_original_aspect_ratio=disable,"
                "setsar=1"
            ),
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0:
            logger.error(f"[Pexels] FFmpeg crop failed: {result.stderr.decode()[:300]}")
            return False

        logger.info(f"[Pexels] B-Roll saved: {output_path.name} ({output_path.stat().st_size // 1024}KB)")
        return True

    except Exception as exc:
        logger.error(f"[Pexels] download_and_crop_broll failed: {exc}")
        return False
    finally:
        tmp_path.unlink(missing_ok=True)


async def prefetch_broll_for_clip(
    theme: str,
    api_key: str,
    output_dir: Path,
    clip_duration: float = 10.0,
) -> Optional[Path]:
    """
    High-level: search Pexels for `theme`, download first working clip.
    Returns Path to the cropped 9:16 B-Roll file, or None if unavailable.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = await search_pexels_broll(theme, api_key, max_results=3)

    for candidate in candidates:
        out = output_dir / f"broll_{candidate['id']}.mp4"
        if out.exists() and out.stat().st_size > 50_000:
            logger.info(f"[Pexels] Cache hit: {out.name}")
            return out
        ok = await download_and_crop_broll(candidate["url"], out, target_duration=clip_duration)
        if ok:
            return out

    logger.warning(f"[Pexels] No usable B-Roll found for theme '{theme}'")
    return None


def overlay_broll_on_clip(
    main_clip: Path,
    broll_clip: Path,
    output_path: Path,
    broll_start: float = 0.3,
    broll_end: float = 0.6,
) -> bool:
    """
    Overlay B-Roll on the main clip for the interval [broll_start, broll_end]
    (as fractions of total duration).

    Delegates to broll_compositor.compose_overlay for format-adaptive scaling.
    """
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(main_clip)],
            capture_output=True, text=True, timeout=15,
        )
        duration = float(probe.stdout.strip() or "30")
        start_s  = duration * broll_start
        broll_dur = duration * (broll_end - broll_start)

        ok = compose_overlay(
            main_path=main_clip,
            broll_path=broll_clip,
            output_path=output_path,
            timestamp=start_s,
            duration=broll_dur,
            fade=0.3,
        )
        if ok:
            logger.info(f"[Pexels] B-Roll overlaid on {main_clip.name}")
        return ok
    except Exception as exc:
        logger.error(f"[Pexels] overlay_broll_on_clip error: {exc}")
        return False
