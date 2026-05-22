"""
Pexels Client — Port of short-video-maker's PexelsAPI logic.

Provides a robust Pexels video search client with:
- Joker terms fallback (nature, globe, space, ocean)
- Retry on timeout (3 retries)
- HD quality filtering
- Exact dimension matching for orientation
- Duration buffer (+3s)
- Shuffle search terms for variety
- Graceful degradation: returns empty list on failure
"""

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)
from src.services.metrics_aggregator import record_event

# ── In-memory query cache ─────────────────────────────────────────────────────
# Prevents the same Pexels query from being fired multiple times within the
# same server session. Keyed by (query, page). FIFO eviction at 200 entries.
_query_cache: dict[tuple[str, int], list] = {}
_query_cache_order: list[tuple[str, int]] = []
_MAX_CACHE_SIZE = 200
_EVICT_BATCH = 50


def _cache_get(key: tuple[str, int]) -> Optional[list]:
    return _query_cache.get(key)


def _cache_set(key: tuple[str, int], value: list) -> None:
    global _query_cache, _query_cache_order
    # Evict oldest entries if cache is full
    if len(_query_cache) >= _MAX_CACHE_SIZE:
        for _old_key in _query_cache_order[:_EVICT_BATCH]:
            _query_cache.pop(_old_key, None)
        _query_cache_order = _query_cache_order[_EVICT_BATCH:]
    _query_cache[key] = value
    _query_cache_order.append(key)


# ── Constants ported from short-video-maker ──────────────────────────────────
# ⛔ BLOCKED for insurance/finance content: JOKER_TERMS are generic stock
# keywords ["nature", "globe", "space", "ocean"] that are completely irrelevant
# for insurance/finance transcripts. When the primary query returns no results,
# these joker terms would inject generic nature/space footage unrelated to
# insurance concepts. The search_videos() method checks for insurance content
# and skips JOKER_TERMS when detected.
JOKER_TERMS = ["nature", "globe", "space", "ocean"]

DURATION_BUFFER_SECONDS = 3.0
DEFAULT_TIMEOUT_MS = 5000
RETRY_TIMES = 3
PEXELS_API_BASE = "https://api.pexels.com/videos/search"

# Orientation dimension constraints (width x height)
ORIENTATION_DIMENSIONS = {
    "portrait":  (576, 1024),   # 9:16
    "landscape": (1024, 576),   # 16:9
    "square":    (640, 640),    # 1:1
}


@dataclass
class PexelsVideo:
    """A single Pexels video result."""
    id: int
    url: str          # direct download link
    width: int
    height: int
    duration: float   # seconds


class PexelsClient:
    """
    Robust Pexels video search client.

    Ported from short-video-maker's PexelsAPI class.
    Gracefully degrades: returns empty list on any failure.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self._session: Optional[httpx.AsyncClient] = None

    async def _get_session(self) -> httpx.AsyncClient:
        if self._session is None:
            self._session = httpx.AsyncClient(
                timeout=DEFAULT_TIMEOUT_MS / 1000.0,
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._session

    async def close(self):
        if self._session:
            await self._session.aclose()
            self._session = None

    # ── Public API ───────────────────────────────────────────────────────────

    async def search_videos(
        self,
        query: str,
        min_duration: float = 3.0,
        exclude_ids: Optional[List[int]] = None,
        orientation: str = "portrait",
    ) -> List[PexelsVideo]:
        """
        Search Pexels for videos matching the given query.

        Ported from short-video-maker's PexelsAPI.findVideo().

        Args:
            query: Search term.
            min_duration: Minimum video duration in seconds.
            exclude_ids: IDs to exclude (already used).
            orientation: "portrait", "landscape", or "square".

        Returns:
            List of PexelsVideo matching all criteria. Empty list on failure.
        """
        if not self.api_key:
            logger.warning("[PexelsClient] No API key configured")
            return []

        # [FLAG] SHORT_VIDEO_MAKER_PEXELS_ENABLED — skip if disabled
        try:
            from src.config import get_config
            cfg = get_config()
            if not cfg.short_video_maker_pexels_enabled:
                logger.info("[PexelsClient] Disabled by SHORT_VIDEO_MAKER_PEXELS_ENABLED flag, skipping B-roll fetch")
                return []
        except Exception:
            pass

        exclude_ids = exclude_ids or []

        # ── BLOCK FALLBACK PATH C: JOKER_TERMS for insurance/finance content ──
        # When the query contains insurance/finance keywords, skip JOKER_TERMS
        # (nature, globe, space, ocean) because they would inject completely
        # irrelevant generic footage. Only search with the original query.
        # Insurance keywords are defined in INSURANCE_KEYWORD_MAP (shared with
        # broll_service.py and confidence_subtitle_service.py).
        _INSURANCE_KEYWORDS = [
            "seguro", "seguros", "indemnización", "indemnizacion",
            "fallecimiento", "cobertura", "mutua", "ahorro",
            "protección", "proteccion", "accidente", "tranquilidad",
            "contrato", "precio", "prima", "póliza", "poliza",
            "siniestro", "reclamación", "reclamacion", "vida",
            "coche", "hogar", "salud", "vivienda",
        ]
        _query_lower = query.lower()
        _is_insurance = any(kw in _query_lower for kw in _INSURANCE_KEYWORDS)

        if _is_insurance:
            logger.info(
                f"[PexelsClient] ⛔ BLOCKED fallback path C: JOKER_TERMS skipped "
                f"for insurance/finance content (query='{query}'). "
                f"Only searching with the original query to avoid injecting "
                f"generic nature/space footage irrelevant to insurance concepts."
            )
            search_terms = [query]
        else:
            search_terms = [query] + JOKER_TERMS
            random.shuffle(search_terms)

        for term in search_terms:
            try:
                videos = await self._search_term(
                    term=term,
                    min_duration=min_duration,
                    exclude_ids=exclude_ids,
                    orientation=orientation,
                )
                if videos:
                    logger.info(
                        "[PexelsClient] Found %d video(s) for term '%s' (query='%s')",
                        len(videos), term, query,
                    )
                    # [Metrics] broll_pexels_result
                    chosen_id = videos[0].id if hasattr(videos[0], 'id') else str(videos[0])[:20]
                    record_event("broll_pexels_result", payload={
                        "query": query, "term": term, "count": len(videos),
                        "chosen_id": str(chosen_id),
                    })
                    return videos
            except Exception as e:
                logger.debug(
                    "[PexelsClient] Term '%s' failed: %s — trying next", term, e,
                )

        logger.warning("[PexelsClient] No videos found for query='%s'", query)
        return []

    # ── Internal search ──────────────────────────────────────────────────────

    async def _search_term(
        self,
        term: str,
        min_duration: float,
        exclude_ids: List[int],
        orientation: str,
    ) -> List[PexelsVideo]:
        """
        Search a single term with retry logic.

        Ported from short-video-maker's PexelsAPI._findVideo().
        Uses an in-memory cache keyed by (term, page=1) to avoid redundant
        API calls within the same server session.
        """
        # Check in-memory cache before making the HTTP request
        _cache_key = (term, 1)
        cached = _cache_get(_cache_key)
        if cached is not None:
            logger.debug("[PexelsClient] Cache hit for term '%s'", term)
            # Re-apply filtering on cached raw data (exclude_ids may differ)
            return self._filter_videos(
                videos=cached,
                min_duration=min_duration,
                exclude_ids=exclude_ids,
                orientation=orientation,
            )[:3]

        last_error: Optional[Exception] = None

        for attempt in range(RETRY_TIMES):
            try:
                session = await self._get_session()
                params = {
                    "query": term,
                    "per_page": 80,
                    "orientation": orientation,
                    "size": "medium",  # medium = HD quality
                }
                resp = await session.get(
                    PEXELS_API_BASE,
                    headers={"Authorization": self.api_key},
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                videos = data.get("videos", [])

                # Store in cache (raw API response, before filtering)
                _cache_set(_cache_key, videos)


                if not videos:
                    logger.debug("[PexelsClient] No videos for term '%s'", term)
                    return []

                # Filter by quality, dimensions, duration, and exclusion
                candidates = self._filter_videos(
                    videos=videos,
                    min_duration=min_duration,
                    exclude_ids=exclude_ids,
                    orientation=orientation,
                )

                if candidates:
                    # Return a random selection (up to 3) for variety
                    random.shuffle(candidates)
                    return candidates[:3]

                logger.debug(
                    "[PexelsClient] Term '%s': %d raw videos, 0 after filtering",
                    term, len(videos),
                )
                return []

            except httpx.TimeoutException as e:
                last_error = e
                logger.debug(
                    "[PexelsClient] Timeout on term '%s' (attempt %d/%d)",
                    term, attempt + 1, RETRY_TIMES,
                )
                if attempt < RETRY_TIMES - 1:
                    wait = 1.0 * (attempt + 1)
                    await asyncio.sleep(wait)
                continue

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    logger.error("[PexelsClient] Invalid API key (401)")
                    return []  # Don't retry auth errors
                last_error = e
                logger.debug(
                    "[PexelsClient] HTTP %d on term '%s' (attempt %d/%d)",
                    e.response.status_code, term, attempt + 1, RETRY_TIMES,
                )
                if attempt < RETRY_TIMES - 1:
                    await asyncio.sleep(1.0)
                continue

            except Exception as e:
                last_error = e
                logger.debug(
                    "[PexelsClient] Error on term '%s' (attempt %d/%d): %s",
                    term, attempt + 1, RETRY_TIMES, e,
                )
                if attempt < RETRY_TIMES - 1:
                    await asyncio.sleep(1.0)
                continue

        if last_error:
            logger.warning(
                "[PexelsClient] All %d retries exhausted for term '%s': %s",
                RETRY_TIMES, term, last_error,
            )
        return []

    # ── Filtering ────────────────────────────────────────────────────────────

    def _filter_videos(
        self,
        videos: list,
        min_duration: float,
        exclude_ids: List[int],
        orientation: str,
    ) -> List[PexelsVideo]:
        """
        Filter raw Pexels API videos by quality, dimensions, duration, and exclusion.

        Ported from short-video-maker's dimension/duration filtering logic.
        """
        target_w, target_h = ORIENTATION_DIMENSIONS.get(orientation, (576, 1024))
        min_dur = min_duration + DURATION_BUFFER_SECONDS
        candidates: List[PexelsVideo] = []

        for v in videos:
            vid_id = v.get("id")
            if vid_id in exclude_ids:
                continue

            duration = float(v.get("duration", 0))
            if duration < min_dur:
                continue

            video_files = v.get("video_files", [])
            for vf in video_files:
                w = vf.get("width", 0)
                h = vf.get("height", 0)
                file_type = vf.get("file_type", "")
                quality = vf.get("quality", "")

                # HD quality filter: prefer "hd" or "medium" quality
                if quality not in ("hd", "medium", "sd"):
                    continue

                # Must be MP4
                if file_type != "video/mp4":
                    continue

                # Exact dimension matching for orientation
                if w == target_w and h == target_h:
                    candidates.append(PexelsVideo(
                        id=vid_id,
                        url=vf["link"],
                        width=w,
                        height=h,
                        duration=duration,
                    ))
                    break  # One video_file entry per video is enough

        return candidates

    # ── Convenience ──────────────────────────────────────────────────────────

    async def search_videos_batch(
        self,
        queries: List[str],
        min_duration: float = 3.0,
        exclude_ids: Optional[List[int]] = None,
        orientation: str = "portrait",
        max_per_query: int = 2,
    ) -> List[PexelsVideo]:
        """
        Search multiple queries and collect unique results.

        Useful for getting diverse B-roll from multiple keywords.
        """
        exclude_ids = exclude_ids or []
        all_videos: List[PexelsVideo] = []
        seen_ids: set = set(exclude_ids)

        for query in queries:
            results = await self.search_videos(
                query=query,
                min_duration=min_duration,
                exclude_ids=list(seen_ids),
                orientation=orientation,
            )
            added = 0
            for v in results:
                if v.id not in seen_ids and added < max_per_query:
                    all_videos.append(v)
                    seen_ids.add(v.id)
                    added += 1

        return all_videos


# ── Singleton ────────────────────────────────────────────────────────────────

_pexels_client: Optional[PexelsClient] = None


def get_pexels_client(api_key: Optional[str] = None) -> PexelsClient:
    """Return a cached PexelsClient singleton."""
    global _pexels_client
    if _pexels_client is None:
        _pexels_client = PexelsClient(api_key=api_key)
    return _pexels_client
