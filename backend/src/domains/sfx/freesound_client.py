"""
Freesound API client — search and download sound effects with LRU cache.
"""
import os
import logging
import hashlib
from pathlib import Path
from typing import Optional

import aiohttp
import aiofiles

logger = logging.getLogger(__name__)

FREESOUND_BASE = "https://freesound.org/apiv2"
SFX_CACHE_DIR = Path(os.environ.get("SFX_CACHE_DIR", "/app/assets/sfx"))


class FreesoundClient:
    """Freesound API client with local LRU cache."""

    def __init__(self):
        self.api_key = os.getenv("FREESOUND_API_KEY", "")
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def search_and_download(
        self,
        query: str,
        category: str = "transitions",
        max_duration: float = 2.5,
        min_duration: float = 0.2,
    ) -> Optional[str]:
        """Search Freesound, download to local cache, return path."""
        if not self.api_key:
            logger.warning("[Freesound] FREESOUND_API_KEY not set")
            return None

        cache_dir = SFX_CACHE_DIR / category
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Check local cache first (hash-based)
        cache_key = hashlib.md5(query.encode()).hexdigest()[:16]
        cached = sorted(cache_dir.glob(f"{cache_key}_*.mp3"))
        if cached:
            logger.debug(f"[Freesound] Cache HIT: {cached[0].name}")
            return str(cached[0])

        # Search Freesound API
        session = await self._get_session()
        params = {
            "query": query,
            "token": self.api_key,
            "fields": "id,name,previews,duration,avg_rating,num_downloads",
            "filter": f"duration:[{min_duration} TO {max_duration}]",
            "sort": "rating_desc",
            "page_size": 5,
        }

        try:
            async with session.get(
                f"{FREESOUND_BASE}/search/text/", params=params, timeout=10
            ) as resp:
                if resp.status != 200:
                    logger.warning(f"[Freesound] API error {resp.status}: {await resp.text()[:100]}")
                    return None
                data = await resp.json()
        except Exception as e:
            logger.warning(f"[Freesound] Search failed: {e}")
            return None

        results = data.get("results", [])
        if not results:
            logger.debug(f"[Freesound] No results for '{query}'")
            return None

        # Pick best result: weighted by rating (60%) + downloads (40%)
        def _score(r):
            rating = r.get("avg_rating", 0) or 0
            downloads = r.get("num_downloads", 0) or 0
            return rating * 0.6 + min(downloads / 10000, 1) * 0.4

        best = max(results, key=_score)

        # Download HQ preview
        preview_url = best["previews"].get(
            "preview-hq-mp3",
            best["previews"].get("preview-lq-mp3"),
        )
        if not preview_url:
            return None

        try:
            async with session.get(preview_url, timeout=15) as resp:
                if resp.status == 200:
                    sfx_id = best["id"]
                    out_path = cache_dir / f"{cache_key}_{sfx_id}.mp3"
                    data = await resp.read()
                    async with aiofiles.open(out_path, "wb") as f:
                        await f.write(data)
                    logger.info(f"[Freesound] ✅ Downloaded: {best['name']} ({len(data)//1024}KB)")
                    return str(out_path)
        except Exception as e:
            logger.warning(f"[Freesound] Download failed: {e}")

        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
