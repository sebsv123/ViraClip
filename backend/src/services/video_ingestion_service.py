"""
Multi-Source Video Ingestion Service.

Downloads videos from public URLs (YouTube, TikTok, Instagram Reels,
Twitch clips, Twitter/X, Facebook) using yt-dlp and returns a local
file path ready for the ViraClip processing pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)

# Max file size guard (bytes) — 4 GB
MAX_VIDEO_BYTES = 4 * 1024 ** 3

# Supported platform URL patterns
_PLATFORM_PATTERNS: Dict[str, re.Pattern] = {
    "youtube":   re.compile(r"(?:youtube\.com|youtu\.be)", re.I),
    "tiktok":    re.compile(r"tiktok\.com", re.I),
    "instagram": re.compile(r"instagram\.com", re.I),
    "twitch":    re.compile(r"twitch\.tv/(?:videos|\w+/clip)", re.I),
    "twitter":   re.compile(r"(?:twitter|x)\.com", re.I),
    "facebook":  re.compile(r"facebook\.com|fb\.watch", re.I),
    "vimeo":     re.compile(r"vimeo\.com", re.I),
}


@dataclass
class IngestResult:
    url: str
    local_path: Optional[str]
    platform: str
    title: str = ""
    duration_seconds: float = 0.0
    file_size_bytes: int = 0
    resolution: str = ""
    downloaded_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.local_path is not None and self.error is None


def detect_platform(url: str) -> str:
    """Detect which platform a URL belongs to."""
    for name, pattern in _PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return "unknown"


def _build_ytdlp_opts(
    output_dir: str,
    max_height: int = 1080,
    prefer_format: str = "mp4",
    cookies_file: Optional[str] = None,
) -> List[str]:
    """Build yt-dlp CLI arguments."""
    template = str(Path(output_dir) / "%(id)s.%(ext)s")
    args = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        "-o", template,
        # Best mp4 up to max_height; fallback to any format
        "-f", f"bestvideo[height<={max_height}][ext={prefer_format}]+bestaudio[ext=m4a]"
              f"/bestvideo[height<={max_height}]+bestaudio"
              f"/best[height<={max_height}]"
              f"/best",
        "--merge-output-format", "mp4",
        "--max-filesize", str(MAX_VIDEO_BYTES),
        "--print-json",
    ]
    if cookies_file and Path(cookies_file).exists():
        args += ["--cookies", cookies_file]
    return args


async def ingest_url(
    url: str,
    output_dir: Optional[str] = None,
    max_height: int = 1080,
    cookies_file: Optional[str] = None,
) -> IngestResult:
    """
    Download a video from a public URL using yt-dlp.

    Args:
        url: Public video URL (YouTube, TikTok, Instagram, Twitch, etc.)
        output_dir: Directory to write the downloaded file. Defaults to a temp dir.
        max_height: Maximum video height in pixels (default 1080).
        cookies_file: Optional path to a Netscape cookies.txt for authenticated downloads.

    Returns:
        IngestResult with local_path set on success.
    """
    platform = detect_platform(url)
    _output_dir = output_dir or tempfile.mkdtemp(prefix="viraclip_ingest_")
    Path(_output_dir).mkdir(parents=True, exist_ok=True)

    args = _build_ytdlp_opts(_output_dir, max_height, cookies_file=cookies_file)
    cmd = args + [url]

    logger.info("[ingest] Downloading from %s: %s", platform, url)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)
    except asyncio.TimeoutError:
        return IngestResult(url=url, local_path=None, platform=platform,
                            error="Download timed out (5 min limit)")
    except FileNotFoundError:
        return IngestResult(url=url, local_path=None, platform=platform,
                            error="yt-dlp not installed — run: pip install yt-dlp")
    except Exception as exc:
        return IngestResult(url=url, local_path=None, platform=platform, error=str(exc))

    if proc.returncode != 0:
        err = stderr.decode()[-300:]
        return IngestResult(url=url, local_path=None, platform=platform, error=err)

    # Parse metadata from JSON output
    import json
    title = ""
    duration = 0.0
    video_id = ""
    try:
        for line in stdout.decode().splitlines():
            if line.startswith("{"):
                meta = json.loads(line)
                title = meta.get("title", "")
                duration = float(meta.get("duration") or 0)
                video_id = meta.get("id", "")
                break
    except Exception:
        pass

    # Find downloaded file
    candidates = sorted(
        Path(_output_dir).glob(f"{video_id}.*") if video_id else Path(_output_dir).glob("*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        # Broader search
        candidates = sorted(
            Path(_output_dir).iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        candidates = [c for c in candidates if c.suffix in (".mp4", ".mkv", ".webm", ".mov")]

    if not candidates:
        return IngestResult(url=url, local_path=None, platform=platform,
                            error="Download succeeded but output file not found")

    local_path = str(candidates[0])
    file_size = candidates[0].stat().st_size

    logger.info("[ingest] ✓ %s → %s (%.1fs, %.1f MB)",
                platform, local_path, duration, file_size / 1e6)

    return IngestResult(
        url=url,
        local_path=local_path,
        platform=platform,
        title=title,
        duration_seconds=duration,
        file_size_bytes=file_size,
    )


async def ingest_multiple(
    urls: List[str],
    output_dir: Optional[str] = None,
    max_concurrent: int = 3,
) -> List[IngestResult]:
    """Download multiple URLs concurrently (up to max_concurrent at once)."""
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _guarded(url: str) -> IngestResult:
        async with semaphore:
            return await ingest_url(url, output_dir=output_dir)

    return list(await asyncio.gather(*[_guarded(u) for u in urls]))


def is_ytdlp_available() -> bool:
    """Check whether yt-dlp is installed and callable."""
    import shutil
    return shutil.which("yt-dlp") is not None


async def get_video_info(url: str) -> Dict[str, Any]:
    """Fetch metadata for a URL without downloading (yt-dlp --dump-json)."""
    cmd = ["yt-dlp", "--no-playlist", "--dump-json", "--quiet", url]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode == 0:
            import json
            return json.loads(stdout.decode().splitlines()[0])
    except Exception as exc:
        logger.debug("[ingest] get_video_info failed: %s", exc)
    return {}
