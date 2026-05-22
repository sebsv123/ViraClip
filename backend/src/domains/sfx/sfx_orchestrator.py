"""
SFX Orchestrator — coordinates SFX profile selection, Freesound download, and mixing.
"""
import asyncio
import hashlib
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .freesound_client import FreesoundClient
from .sfx_mixer import apply_sfx

logger = logging.getLogger(__name__)

# ── Built-in SFX categories with Freesound queries ──────────────────────────
# Each category maps to 1-2 search queries that reliably return good results.
SFX_CATEGORIES: Dict[str, List[str]] = {
    "transition": [
        "whoosh fast",
        "swish airy",
    ],
    "emphasis": [
        "ding notification",
        "pop bright",
    ],
    "hook": [
        "impact cinematic",
        "stinger dramatic",
    ],
}

# Max SFX per 10 seconds of clip duration
MAX_SFX_PER_10S = 3


def _select_sfx_for_profile(
    profile: str,
    duration: float,
    jump_cuts: List[float],
    energy: float,
) -> List[Dict[str, Any]]:
    """
    Select SFX placements based on profile, clip duration, jump cuts, and energy.

    Rotates through available queries per category to avoid repeating the same
    asset more than 2 times per clip. Limits total SFX to max 3 per 10s.

    Returns a list of SFX dicts with keys: category, freesound_query, time_offset,
    volume_db, duration.
    """
    if profile == "none":
        return []

    max_sfx = max(1, int(math.ceil(duration / 10.0) * MAX_SFX_PER_10S))

    sfx_list: List[Dict[str, Any]] = []
    # Track query usage to avoid repeating the same asset >2 times
    query_usage: Dict[str, int] = {}

    def _pick_query(category: str) -> str:
        """Pick the least-used query for this category, rotating to avoid repeats."""
        queries = SFX_CATEGORIES.get(category, ["whoosh fast"])
        # Sort by usage count (ascending) so least-used is picked first
        sorted_q = sorted(queries, key=lambda q: query_usage.get(q, 0))
        chosen = sorted_q[0]
        query_usage[chosen] = query_usage.get(chosen, 0) + 1
        return chosen

    # 1. Place SFX at jump cuts (transition category)
    for t in jump_cuts:
        if len(sfx_list) >= max_sfx:
            break
        if t < 0 or t > duration:
            continue
        query = _pick_query("transition")
        sfx_list.append({
            "category": "transition",
            "freesound_query": query,
            "time_offset": t,
            "volume_db": -20 if profile == "subtle" else -14,
            "duration": 0.8,
            "fade_out_ms": 200,
        })

    # 2. Place emphasis SFX at energy peaks (every ~3s if energy is high)
    if energy >= 0.5:
        step = 3.0 if profile == "modern" else 5.0
        t = step
        while t < duration and len(sfx_list) < max_sfx:
            # Avoid placing too close to existing SFX
            if not any(abs(s["time_offset"] - t) < 1.5 for s in sfx_list):
                query = _pick_query("emphasis")
                sfx_list.append({
                    "category": "emphasis",
                    "freesound_query": query,
                    "time_offset": t,
                    "volume_db": -22 if profile == "subtle" else -16,
                    "duration": 0.5,
                    "fade_out_ms": 150,
                })
            t += step

    # 3. Hook SFX at the very beginning (first 1.5s) if no jump cut there
    if len(sfx_list) < max_sfx:
        has_early = any(abs(s["time_offset"]) < 1.5 for s in sfx_list)
        if not has_early:
            query = _pick_query("hook")
            sfx_list.append({
                "category": "hook",
                "freesound_query": query,
                "time_offset": 0.3,
                "volume_db": -18 if profile == "subtle" else -12,
                "duration": 1.2,
                "fade_out_ms": 300,
            })

    logger.info(
        "[SFX] Profile=%s: %d SFX placed (max=%d, duration=%.1fs, energy=%.2f, query_usage=%s)",
        profile, len(sfx_list), max_sfx, duration, energy, query_usage,
    )
    return sfx_list


class SFXOrchestrator:
    """Orchestrates the full SFX pipeline: profile → fetch → mix."""

    def __init__(self, freesound_client: Optional[FreesoundClient] = None):
        self.freesound = freesound_client or FreesoundClient()
        self.profile = os.getenv("SFX_PROFILE", "subtle").lower()
        self.enabled = self.profile != "none"
        self.elevenlabs_enabled = (
            os.getenv("ELEVENLABS_SFX_ENABLED", "false").lower() == "true"
            and bool(os.getenv("ELEVENLABS_API_KEY", "").strip())
        )

    async def _elevenlabs_generate(self, keyword: str, sfx_dir: Path) -> Optional[str]:
        """Generate SFX via ElevenLabs Sound Generation API with Redis cache."""
        if not self.elevenlabs_enabled:
            return None

        api_key = os.getenv("ELEVENLABS_API_KEY", "")
        normalized = hashlib.md5(keyword.lower().encode()).hexdigest()
        cache_path = sfx_dir / f"elevenlabs_{normalized}.mp3"

        # Check module-level cache first
        if normalized in _elevenlabs_cache:
            cached = _elevenlabs_cache[normalized]
            if Path(cached).exists():
                logger.info(f"[SFX] ElevenLabs cache hit: '{keyword}'")
                return cached

        # Check disk cache
        if cache_path.exists():
            _elevenlabs_cache[normalized] = str(cache_path)
            logger.info(f"[SFX] ElevenLabs disk cache: '{keyword}'")
            return str(cache_path)

        try:
            async with httpx.AsyncClient(timeout=ELEVENLABS_HTTP_TIMEOUT) as client:
                resp = await client.post(
                    "https://api.elevenlabs.io/v1/sound-generation",
                    headers={"xi-api-key": api_key},
                    json={
                        "text": f"{keyword} sound effect",
                        "duration_seconds": 2.0,
                        "prompt_influence": 0.3,
                    },
                )
                resp.raise_for_status()
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(resp.content)
                _elevenlabs_cache[normalized] = str(cache_path)
                logger.info(f"[SFX] ElevenLabs generated '{keyword}' → {cache_path}")
                return str(cache_path)
        except Exception as e:
            logger.warning(f"[SFX] ElevenLabs generation failed for '{keyword}': {e}")
            return None

    async def plan_and_fetch(
        self,
        transcript_segments: List[Dict[str, Any]],
        jump_cuts: List[float],
        clip_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate SFX plan from profile and download all assets from Freesound."""
        if not self.enabled:
            logger.debug("[SFX] Disabled (SFX_PROFILE=none)")
            return []

        clip_metadata = clip_metadata or {}
        duration = clip_metadata.get("duration", 60)
        energy = clip_metadata.get("energy", 0.5)

        # Build SFX plan from profile
        plan = _select_sfx_for_profile(
            profile=self.profile,
            duration=duration,
            jump_cuts=jump_cuts,
            energy=energy,
        )

        if not plan:
            logger.info("[SFX] Profile '%s' produced empty plan", self.profile)
            return []

        # Download each SFX — Freesound → ElevenLabs fallback
        sfx_dir = Path("/tmp/sfx_cache")
        sfx_dir.mkdir(parents=True, exist_ok=True)
        for sfx in plan:
            query = sfx.get("freesound_query", "")
            category = sfx.get("category", "transition")
            path = await self.freesound.search_and_download(
                query=query,
                category=category,
            )
            sfx["local_path"] = path
            if path:
                logger.info(f"[SFX] ✅ {category}: '{query}' → {path}")
            else:
                logger.warning(f"[SFX] ⚠️ Not found: '{query}'")

        # Filter to only valid SFX
        valid = [s for s in plan if s.get("local_path")]
        logger.info("[SFX] Plan: %d/%d SFX ready", len(valid), len(plan))
        return valid

    async def process_clip(
        self,
        input_path: str,
        output_path: str,
        transcript_segments: List[Dict[str, Any]],
        jump_cuts: List[float],
        clip_metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Full pipeline: profile → fetch → mix for a single clip."""
        sfx_plan = await self.plan_and_fetch(
            transcript_segments=transcript_segments,
            jump_cuts=jump_cuts,
            clip_metadata=clip_metadata,
        )

        if not sfx_plan:
            return input_path

        return await apply_sfx(
            input_video=input_path,
            sfx_plan=sfx_plan,
            output_path=output_path,
        )

    async def close(self):
        await self.freesound.close()
