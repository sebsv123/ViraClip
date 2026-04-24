"""
Freesound Service — Auto-matched music and SFX for B-roll mood.

Uses Freesound API v2 for tag-based search (mood:happy, loop, bpm:120)
and acoustic similarity to match background audio to B-roll mood tags.

Freesound requires attribution for most sounds — the service tracks
license info and returns it with each result for display in UI.
"""

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

FREESOUND_API_BASE = "https://freesound.org/apiv2"
FREESOUND_CLIENT_ID = os.environ.get("FREESOUND_CLIENT_ID", "")
FREESOUND_API_KEY = os.environ.get("FREESOUND_API_KEY", "")
FREESOUND_AUTO_MATCH = os.environ.get("FREESOUND_AUTO_MATCH", "true").lower() == "true"
FREESOUND_SFX_ENABLED = os.environ.get("FREESOUND_SFX_ENABLED", "true").lower() == "true"

# Target loudness for normalization (LUFS)
TARGET_LUFS = -14.0

# Mood → Freesound tag mappings (most-to-least specific)
_MOOD_TAG_MAP: Dict[str, List[str]] = {
    "energetic":  ["mood:happy", "upbeat", "energetic", "driving", "fast"],
    "calm":       ["mood:calm", "relaxing", "ambient", "peaceful", "slow"],
    "sad":        ["mood:sad", "melancholic", "somber", "emotional", "soft"],
    "dramatic":   ["mood:tense", "epic", "cinematic", "intense", "building"],
    "funny":      ["mood:happy", "playful", "comedy", "quirky", "light"],
    "mysterious": ["mood:mysterious", "dark", "suspense", "eerie", "tension"],
    "romantic":   ["mood:romantic", "love", "soft", "emotional", "tender"],
    "inspirational": ["inspirational", "motivational", "uplifting", "hopeful", "mood:happy"],
}

# Default music query filters
_DEFAULT_MUSIC_FILTERS = {
    "duration": "[3.0 TO 15.0]",  # match typical B-roll duration
    "type": "mp3 OR wav OR flac OR ogg",
}

# Default SFX query filters
_DEFAULT_SFX_FILTERS = {
    "duration": "[0.5 TO 5.0]",
    "type": "mp3 OR wav OR flac",
}


@dataclass
class FreesoundResult:
    """A single Freesound result with metadata."""
    id: int
    name: str
    url: str
    download_url: str
    preview_url: Optional[str]
    duration: float
    license: str  # e.g., "Creative Commons 0", "Attribution"
    attribution: Optional[str]  # required text for Attribution licenses
    tags: List[str]
    score: float  # relevance score


class FreesoundService:
    """
    Freesound API client for mood-matched audio retrieval.

    Usage:
        service = FreesoundService()
        result = await service.search_by_mood("energetic", duration=5.0)
        if result:
            path = await service.download(result, output_dir="/tmp/audio")
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or FREESOUND_API_KEY
        self.client_id = FREESOUND_CLIENT_ID or self.api_key  # reuse if no separate client_id
        self._session: Optional[httpx.AsyncClient] = None

    async def _get_session(self) -> httpx.AsyncClient:
        if self._session is None:
            self._session = httpx.AsyncClient(
                base_url=FREESOUND_API_BASE,
                headers={"Authorization": f"Token {self.api_key}"} if self.api_key else {},
                timeout=httpx.Timeout(30.0, connect=10.0),
            )
        return self._session

    # ──────────────────────────────────────────────────────────────────────────
    # 1. SEARCH
    # ──────────────────────────────────────────────────────────────────────────

    async def search_by_mood(
        self,
        mood: str,
        duration: float = 5.0,
        target_duration: Optional[float] = None,
        loop: bool = True,
        limit: int = 5,
    ) -> Optional[FreesoundResult]:
        """
        Search Freesound for music matching a mood tag.

        Args:
            mood: e.g., "energetic", "calm", "sad", "dramatic"
            duration: preferred duration in seconds (search window ±30%)
            target_duration: if set, overrides duration for exact matching
            loop: prefer loopable sounds (adds "loop" tag)
            limit: max results to fetch before picking best

        Returns:
            Best matching FreesoundResult, or None if no match / no API key.
        """
        if not self.api_key:
            logger.debug("[freesound] No API key configured, skipping mood search")
            return None

        tags = _MOOD_TAG_MAP.get(mood.lower(), [f"mood:{mood.lower()}", mood.lower()])
        tag_query = " OR ".join(tags)

        # Build duration filter (±30% tolerance)
        target = target_duration or duration
        dur_min = max(1.0, target * 0.7)
        dur_max = target * 1.3
        filters = dict(_DEFAULT_MUSIC_FILTERS)
        filters["duration"] = f"[{dur_min:.1f} TO {dur_max:.1f}]"

        # Add loop tag if requested
        if loop:
            tag_query = f"({tag_query}) AND loop"

        results = await self._search(tag_query, filters, sort="score", limit=limit)
        if not results:
            # Fallback: relax duration constraint
            filters["duration"] = "[2.0 TO 30.0]"
            results = await self._search(tag_query, filters, sort="score", limit=limit)

        if results:
            # Pick best: prefer longer = closer to target, higher score
            best = max(results, key=lambda r: (r.score, -abs(r.duration - target)))
            return best
        return None

    async def search_sfx(
        self,
        keyword: str,
        duration: float = 2.0,
        limit: int = 3,
    ) -> Optional[FreesoundResult]:
        """
        Search Freesound for sound effects matching a keyword.

        Args:
            keyword: e.g., "whoosh", "pop", "click", "ambience"
            duration: preferred duration in seconds
            limit: max results to fetch

        Returns:
            Best matching FreesoundResult, or None.
        """
        if not self.api_key or not FREESOUND_SFX_ENABLED:
            return None

        # Build query: keyword + sfx tag
        tag_query = f"{keyword} AND (sfx OR sound-effect)"
        filters = dict(_DEFAULT_SFX_FILTERS)
        filters["duration"] = f"[{max(0.3, duration * 0.5):.1f} TO {duration * 1.5:.1f}]"

        results = await self._search(tag_query, filters, sort="score", limit=limit)
        if results:
            return max(results, key=lambda r: r.score)
        return None

    async def _search(
        self,
        query: str,
        filters: Dict[str, str],
        sort: str = "score",
        limit: int = 10,
    ) -> List[FreesoundResult]:
        """Internal search helper."""
        session = await self._get_session()
        filter_str = " AND ".join(f"{k}:{v}" for k, v in filters.items())
        params = {
            "query": query,
            "filter": filter_str,
            "sort": sort,
            "fields": "id,name,url,download,previews,duration,license,tags,username",
            "page_size": min(limit, 15),
        }

        try:
            resp = await session.get("/search/text/", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("[freesound] Search failed: %s", exc)
            return []

        results: List[FreesoundResult] = []
        for item in data.get("results", []):
            try:
                # Build attribution text for non-CC0 licenses
                license_name = item.get("license", "Unknown")
                username = item.get("username", "unknown")
                name = item.get("name", "untitled")
                if "cc0" in license_name.lower() or "zero" in license_name.lower():
                    attribution = None  # No attribution needed
                else:
                    attribution = f'"{name}" by {username} — {item.get("url", "")}'

                # Preview URL (hq mp3)
                previews = item.get("previews", {})
                preview_url = previews.get("preview-hq-mp3") or previews.get("preview-lq-mp3")

                results.append(FreesoundResult(
                    id=item["id"],
                    name=name,
                    url=item.get("url", ""),
                    download_url=item.get("download", ""),
                    preview_url=preview_url,
                    duration=float(item.get("duration", 0)),
                    license=license_name,
                    attribution=attribution,
                    tags=item.get("tags", []),
                    score=float(item.get("score", 0)),
                ))
            except Exception as exc:
                logger.debug("[freesound] Skipping malformed result: %s", exc)
                continue

        return results

    # ──────────────────────────────────────────────────────────────────────────
    # 2. DOWNLOAD & NORMALIZE
    # ──────────────────────────────────────────────────────────────────────────

    async def download(
        self,
        result: FreesoundResult,
        output_dir: str,
        normalize: bool = True,
    ) -> Optional[Path]:
        """
        Download a Freesound result to disk, optionally normalizing loudness.

        Args:
            result: FreesoundResult to download
            output_dir: directory to save file
            normalize: apply loudnorm to -14 LUFS (broadcast standard)

        Returns:
            Path to downloaded (and possibly normalized) file, or None on failure.
        """
        if not result.download_url:
            logger.warning("[freesound] No download URL for sound %d", result.id)
            return None

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Filename: freesound_{id}_{sanitized_name}.mp3
        safe_name = "".join(c if c.isalnum() else "_" for c in result.name)[:40]
        base_path = out_dir / f"freesound_{result.id}_{safe_name}"
        raw_path = base_path.with_suffix(".raw.mp3")
        final_path = base_path.with_suffix(".mp3")

        # Skip if already exists
        if final_path.exists():
            return final_path

        session = await self._get_session()
        try:
            async with session.stream("GET", result.download_url) as resp:
                resp.raise_for_status()
                with open(raw_path, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        f.write(chunk)
        except Exception as exc:
            logger.warning("[freesound] Download failed for %d: %s", result.id, exc)
            return None

        if normalize:
            ok = await self._normalize_audio(raw_path, final_path)
            if ok:
                raw_path.unlink(missing_ok=True)
                return final_path
            else:
                # Fallback: use raw file renamed
                raw_path.rename(final_path)
                return final_path
        else:
            raw_path.rename(final_path)
            return final_path

    async def _normalize_audio(self, input_path: Path, output_path: Path) -> bool:
        """Apply loudnorm filter to reach target LUFS."""
        # Two-pass loudnorm: first measure, then apply
        cmd_measure = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-"
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd_measure,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            stderr_decoded = stderr.decode("utf-8", errors="ignore")

            # Parse measured values from stderr JSON
            json_start = stderr_decoded.find("{")
            json_end = stderr_decoded.rfind("}") + 1
            measured = json.loads(stderr_decoded[json_start:json_end])

            # Build second-pass filter
            filter_str = (
                f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11:"
                f"measured_I={measured['input_i']}:"
                f"measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:"
                f"measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}"
            )

            cmd_apply = [
                "ffmpeg", "-y", "-i", str(input_path),
                "-af", filter_str,
                "-c:a", "aac", "-b:a", "192k",
                "-vn",  # no video
                str(output_path),
            ]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_apply,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc2.wait()
            return proc2.returncode == 0 and output_path.exists()
        except Exception as exc:
            logger.debug("[freesound] Normalization failed: %s", exc)
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # 3. HIGH-LEVEL HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def fetch_for_broll(
        self,
        mood: str,
        duration: float,
        output_dir: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Full pipeline: search by mood → download → normalize → return metadata.

        Returns dict with keys: path, license, attribution, name, preview_url
        or None if anything fails.
        """
        if not self.api_key:
            return None

        result = await self.search_by_mood(mood, duration=duration)
        if not result:
            return None

        path = await self.download(result, output_dir, normalize=True)
        if not path:
            return None

        return {
            "path": str(path),
            "license": result.license,
            "attribution": result.attribution,
            "name": result.name,
            "preview_url": result.preview_url,
            "duration": result.duration,
            "source": "freesound",
            "sound_id": result.id,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Singleton instance for convenient import
# ──────────────────────────────────────────────────────────────────────────────

_freesound_service: Optional[FreesoundService] = None


def get_freesound_service() -> FreesoundService:
    global _freesound_service
    if _freesound_service is None:
        _freesound_service = FreesoundService()
    return _freesound_service
