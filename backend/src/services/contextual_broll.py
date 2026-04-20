"""
Contextual B-Roll — Phase 9 Creative Engine

Unified B-roll lookup: local asset bank → multi-source (Pexels + Pixabay + Coverr) → T2V (Replicate).
Triggered by keyword events from the multimodal timeline.
"""

import asyncio
import logging
import os
import subprocess
import json
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# LTXV threshold - lower = more aggressive LTXV usage
LTXV_BROLL_PRIORITY_THRESHOLD = float(os.environ.get("LTXV_BROLL_PRIORITY_THRESHOLD", "0.4"))

_ASSET_EXTS = (".mp4", ".mov", ".webm", ".jpg", ".jpeg", ".png", ".webp")
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Maps keyword fragments to seed-bank category subdirectory names.
# Longest-match wins — checked in insertion order (most-specific first).
_CATEGORY_MAP: "list[tuple[str, str]]" = [
    # tech / business
    ("phone",       "tech"),       ("laptop",    "tech"),
    ("computer",    "tech"),       ("code",      "tech"),
    ("software",    "tech"),       ("data",      "tech"),
    ("crypto",      "finance"),    ("bitcoin",   "finance"),
    ("money",       "finance"),    ("stock",     "finance"),
    ("invest",      "finance"),    ("bank",      "finance"),
    ("office",      "business"),   ("meeting",   "business"),
    ("startup",     "business"),   ("entrepreneur", "business"),
    # people / lifestyle
    ("person",      "people"),     ("people",    "people"),
    ("woman",       "people"),     ("man",       "people"),
    ("crowd",       "people"),     ("audience",  "people"),
    ("health",      "health"),     ("fitness",   "health"),
    ("workout",     "sport"),      ("gym",       "sport"),
    ("sport",       "sport"),      ("athlete",   "sport"),
    # nature / travel
    ("nature",      "nature"),     ("forest",    "nature"),
    ("ocean",       "nature"),     ("mountain",  "nature"),
    ("sky",         "nature"),     ("sunset",    "nature"),
    ("city",        "city"),       ("urban",     "city"),
    ("street",      "city"),       ("building",  "city"),
    ("travel",      "travel"),     ("flight",    "travel"),
    ("airport",     "travel"),     ("hotel",     "travel"),
    # food / abstract
    ("food",        "food"),       ("cook",      "food"),
    ("restaurant",  "food"),       ("coffee",    "food"),
    ("abstract",    "abstract"),   ("motivat",   "motivation"),
    ("success",     "motivation"), ("inspire",   "motivation"),
]


def _keyword_to_category(keyword: str) -> "str | None":
    """Map a keyword to the closest seed-bank category, or None."""
    kw = keyword.lower()
    for fragment, category in _CATEGORY_MAP:
        if fragment in kw:
            return category
    return None


@dataclass
class BrollAsset:
    path: str
    source: str    # "local" | "multi" | "image" | "ltxv" | "t2v"
    keyword: str
    duration: float


class ContextualBroll:
    """
    Finds or generates a B-roll clip for a given keyword.

    Lookup order (each step only runs if the previous fails):
      1. Local asset bank directory (instant, offline, category-aware)
      2. Multi-source: Pexels + Pixabay + Coverr in parallel
      3. Replicate T2V          (requires T2V_ENABLED=true + REPLICATE_API_TOKEN)
    """

    def __init__(self) -> None:
        self._bank = Path(os.environ.get("BROLL_ASSET_BANK", "/app/assets/broll"))
        self._pexels_key = os.environ.get("PEXELS_API_KEY", "")
        self._pixabay_key = os.environ.get("PIXABAY_API_KEY", "")
        self._coverr_key = os.environ.get("COVERR_API_KEY", "")
        self._t2v_enabled = os.environ.get("T2V_ENABLED", "false").lower() == "true"
        self._replicate_token = os.environ.get("REPLICATE_API_TOKEN", "")
        self._ltxv_enabled = os.environ.get("LTXV_ENABLED", "false").lower() == "true"

    # ── Public API ────────────────────────────────────────────────────────────

    async def get_for_keyword(
        self,
        keyword: str,
        duration: float = 3.0,
        mood: str = "",
        priority: str = "NORMAL",  # NORMAL, HIGH
    ) -> "BrollAsset | None":
        """Return a B-roll asset for keyword, or None if nothing found.

        Lookup order (cascade with 30s total timeout):
          1. Local asset bank (instant, offline, category-aware)
          2. Multi-source video: Pexels + Pixabay + Coverr in parallel (with quality filter)
          3. Pexels/Unsplash IMAGE → Ken Burns animation (FFmpeg, cheap)
          4. LTXV local (HIGH priority skips directly here after failed multi-source)
          5. Replicate T2V (fallback)
        
        For HIGH priority: Try LTXV directly if multi-source fails quality check.
        """
        _timeout = float(os.environ.get("BROLL_SLOT_TIMEOUT_SEC", "30"))
        _prio = priority.upper()  # normalize: "high"→"HIGH", "med"→"MED", "low"→"LOW"
        try:
            # ── HIGH priority: local → multi (quality) → LTXV direct ────────
            if _prio == "HIGH" and self._ltxv_enabled:
                local = self._find_local(keyword)
                if local:
                    logger.info("[BRoll] HIGH slot '%s' → local", keyword)
                    return BrollAsset(str(local), "local", keyword, duration)

                if self._pexels_key or self._pixabay_key or self._coverr_key:
                    path = await self._fetch_multi_source(keyword, duration)
                    if path:
                        logger.info("[BRoll] HIGH slot '%s' → multi (quality passed)", keyword)
                        return BrollAsset(path, "multi", keyword, duration)

                # Direct LTXV — bypass image fallback for HIGH
                path = await self._generate_ltxv_broll(keyword, duration, mood)
                if path:
                    logger.info("[BRoll] HIGH slot '%s' → ltxv", keyword)
                    return BrollAsset(path, "ltxv", keyword, duration)

                if self._t2v_enabled and self._replicate_token:
                    path = await self._generate_t2v(keyword, duration, mood)
                    if path:
                        return BrollAsset(path, "t2v", keyword, duration)
                return None

            # ── MED priority: local → multi + enhance → image fallback ──────
            if _prio == "MED":
                local = self._find_local(keyword)
                if local:
                    logger.info("[BRoll] MED slot '%s' → local", keyword)
                    return BrollAsset(str(local), "local", keyword, duration)

                if self._pexels_key or self._pixabay_key or self._coverr_key:
                    path = await self._fetch_multi_source(keyword, duration)
                    if path:
                        # Try to enhance via RealESRGAN (non-blocking fallback)
                        enhanced = await self._enhance_multi_source(path)
                        source = "multi_enhanced" if enhanced else "multi"
                        final = enhanced or path
                        logger.info("[BRoll] MED slot '%s' → %s", keyword, source)
                        return BrollAsset(final, source, keyword, duration)

                if self._pexels_key:
                    img_path = await self._fetch_pexels_image(keyword)
                    if img_path:
                        logger.info("[BRoll] MED slot '%s' → image (kenburns)", keyword)
                        return BrollAsset(img_path, "image", keyword, duration)

                # MED fallback to LTXV if enabled (conceptual/mood keywords benefit most)
                if self._ltxv_enabled:
                    path = await self._generate_ltxv_broll(keyword, duration, mood)
                    if path:
                        logger.info("[BRoll] MED slot '%s' → ltxv", keyword)
                        return BrollAsset(path, "ltxv", keyword, duration)
                return None

            # ── LOW / NORMAL: full cascade (no enhance overhead) ─────────────
            return await asyncio.wait_for(
                self._cascade_lookup(keyword, duration, mood),
                timeout=_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("B-roll lookup timed out (%.0fs) for '%s'", _timeout, keyword)
            return None

    async def _cascade_lookup(
        self, keyword: str, duration: float, mood: str
    ) -> "BrollAsset | None":
        """Internal cascade — called inside the per-slot timeout."""
        # 1. Local asset bank
        local = self._find_local(keyword)
        if local:
            return BrollAsset(str(local), "local", keyword, duration)

        # 2. Multi-source video (Pexels + Pixabay + Coverr) with quality filter
        if self._pexels_key or self._pixabay_key or self._coverr_key:
            path = await self._fetch_multi_source(keyword, duration)
            if path:
                return BrollAsset(path, "multi", keyword, duration)

        # 3. Image fallback → Ken Burns (Pexels image search, very cheap)
        if self._pexels_key:
            img_path = await self._fetch_pexels_image(keyword)
            if img_path:
                return BrollAsset(img_path, "image", keyword, duration)

        # 4. LTXV local generation (faster than Replicate, no API cost)
        if self._ltxv_enabled:
            path = await self._generate_ltxv_broll(keyword, duration, mood)
            if path:
                return BrollAsset(path, "ltxv", keyword, duration)

        # 5. T2V Replicate (expensive, last resort)
        if self._t2v_enabled and self._replicate_token:
            path = await self._generate_t2v(keyword, duration, mood=mood)
            if path:
                return BrollAsset(path, "t2v", keyword, duration)

        return None

    async def get_for_timeline(
        self,
        timeline_events: list,
        max_assets: int = 3,
    ) -> "list[tuple]":
        """
        Fetch B-roll for up to max_assets hook/impact keyword events.

        Returns [(event, BrollAsset), ...] for events where an asset was found.
        """
        # Include hook, impact, energy keywords AND silence gaps ≥2s for B-roll
        candidates = [
            e for e in timeline_events
            if (e.type == "keyword"
                and e.payload.get("category") in ("hook", "impact", "energy", "broll_llm"))
            or (e.type == "silence" and e.duration >= 2.0)
        ][:max_assets]

        results = await asyncio.gather(
            *[self.get_for_keyword(
                e.payload.get("word", ""),
                duration=e.duration + 1.0,
                mood=e.payload.get("mood", ""),
              )
              for e in candidates],
            return_exceptions=True,
        )

        return [
            (ev, res)
            for ev, res in zip(candidates, results)
            if isinstance(res, BrollAsset)
        ]

    # ── Lookup strategies ─────────────────────────────────────────────────────

    def _find_local(self, keyword: str) -> "Path | None":
        """Search asset bank by keyword. Category-mapped lookup first, then filename glob."""
        if not self._bank.exists():
            return None
        kw = keyword.lower()

        # 1. Category-based lookup: map keyword → category subdir
        category = _keyword_to_category(kw)
        if category:
            cat_dir = self._bank / category
            if cat_dir.is_dir():
                for ext in _ASSET_EXTS:
                    candidates = list(cat_dir.glob(f"*{ext}"))
                    if candidates:
                        import random
                        return random.choice(candidates)

        # 2. Exact keyword subdir match
        for subdir in (self._bank / kw, self._bank / kw[:4]):
            if subdir.is_dir():
                for ext in _ASSET_EXTS:
                    candidates = list(subdir.glob(f"*{ext}"))
                    if candidates:
                        return candidates[0]

        # 3. Filename contains keyword (flat bank or uncategorized)
        for ext in _ASSET_EXTS:
            for p in self._bank.rglob(f"*{kw}*{ext}"):
                if p.is_file():
                    return p

        return None

    @staticmethod
    def _is_image(path: str) -> bool:
        return Path(path).suffix.lower() in _IMAGE_EXTS

    async def _is_quality_broll(self, video_path: Path, slot_mood: str = "") -> bool:
        """Quality filters: motion score, vertical composition, loop detection."""
        try:
            # 1. Motion score (frame diff analysis)
            motion_cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "frame=pkt_pts_time,pkt_size", "-of", "json",
                str(video_path)
            ]
            result = subprocess.run(motion_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                logger.debug("Quality check: ffprobe motion failed for %s", video_path.name)
                return False
            
            frames = json.loads(result.stdout).get("frames", [])
            if len(frames) < 10:
                logger.debug("Quality check: too few frames (%d) in %s", len(frames), video_path.name)
                return False
            
            # Simple motion proxy: size variance between frames
            sizes = [int(f.get("pkt_size", 0)) for f in frames if f.get("pkt_size")]
            if len(sizes) < 10:
                return False
            avg_size = sum(sizes) / len(sizes)
            variance = sum((s - avg_size) ** 2 for s in sizes) / len(sizes)
            motion_score = min(1.0, variance / (avg_size ** 2 + 1)) if avg_size > 0 else 0
            if motion_score < 0.6:
                logger.info("Quality filter: low motion score %.2f for %s", motion_score, video_path.name)
                return False
            
            # 2. Vertical composition check
            probe_cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "json",
                str(video_path)
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5)
            if probe_result.returncode == 0:
                streams = json.loads(probe_result.stdout).get("streams", [])
                if streams:
                    w = streams[0].get("width", 1920)
                    h = streams[0].get("height", 1080)
                    ar = h / w if w > 0 else 1
                    if ar < 0.7:  # Penaliza horizontal (16:9 = 0.56, 9:16 = 1.77)
                        logger.info("Quality filter: horizontal aspect ratio %.2f for %s", ar, video_path.name)
                        return False
            
            # 3. Loop detector (unique frames proxy)
            # Check if middle frames are different from start/end
            if len(frames) >= 20:
                start_size = sum(int(frames[i].get("pkt_size", 0)) for i in range(3)) / 3
                mid_size = sum(int(frames[len(frames)//2 + i].get("pkt_size", 0)) for i in range(3)) / 3
                end_size = sum(int(frames[-3 + i].get("pkt_size", 0)) for i in range(3)) / 3
                
                unique_variance = max(abs(start_size - mid_size), abs(mid_size - end_size), abs(start_size - end_size))
                if unique_variance < 1000:  # Almost identical frame sizes = static/loop
                    logger.info("Quality filter: low unique frame variance %.0f for %s", unique_variance, video_path.name)
                    return False
            
            return True
        except Exception as exc:
            logger.debug("Quality check error for %s: %s", video_path.name, exc)
            return True  # Fallback to accepting if check fails

    async def _fetch_multi_source(self, keyword: str, duration: float) -> "str | None":
        """Delegate to BrollService — queries Pexels + Pixabay + Coverr in parallel."""
        try:
            from .broll_service import BrollService
            result = await BrollService().fetch_broll_asset(keyword)
            if result:
                # Apply quality filter
                if await self._is_quality_broll(Path(str(result))):
                    return str(result)
                else:
                    logger.info("Multi-source result rejected by quality filter for '%s'", keyword)
                    # Don't return - let cascade continue to image or LTXV
                    return None
            return None
        except Exception as exc:
            logger.debug("Multi-source B-roll failed for '%s': %s", keyword, exc)
            return None

    async def _fetch_pexels_image(self, keyword: str) -> "str | None":
        """
        Search Pexels for a portrait IMAGE (not video) and download it.
        The broll_compositor.normalize_broll() will detect the image extension
        and apply Ken Burns animation with silent audio automatically.
        Returns local image path or None.
        """
        if not self._pexels_key:
            return None
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": keyword, "per_page": 5, "orientation": "portrait"},
                    headers={"Authorization": self._pexels_key},
                )
                if resp.status_code != 200:
                    return None
                photos = resp.json().get("photos", [])
                if not photos:
                    return None
                # Pick the first photo, use the "large" size (portrait, ~1280px)
                import random
                photo = random.choice(photos[:3])
                img_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
                if not img_url:
                    return None
                # Download
                img_resp = await client.get(img_url)
                if img_resp.status_code != 200:
                    return None
                ext = ".jpg"
                img_path = self._bank / f"pexels_{keyword[:20].replace(' ', '_')}{ext}"
                img_path.parent.mkdir(parents=True, exist_ok=True)
                img_path.write_bytes(img_resp.content)
                logger.debug("Pexels image downloaded for '%s': %s", keyword, img_path)
                return str(img_path)
        except Exception as exc:
            logger.debug("Pexels image fetch failed for '%s': %s", keyword, exc)
            return None

    async def _enhance_multi_source(self, video_path_str: str) -> "str | None":
        """Run RealESRGAN enhance on a downloaded Pexels video via ComfyUI.
        Returns path to enhanced file on success, None otherwise (caller uses original).
        """
        try:
            from ..comfyui_bridge import ComfyUIBridge
            import tempfile
            bridge = ComfyUIBridge()
            src = Path(video_path_str)
            out = src.with_name(f"enhanced_{src.name}")
            result = await bridge.enhance_pexels(src, out)
            await bridge.close()
            if result and result.exists() and result.stat().st_size > 5_000:
                return str(result)
            return None
        except Exception as exc:
            logger.debug("[BRoll] enhance_pexels fallback: %s", exc)
            return None

    async def _generate_t2v(
        self, keyword: str, duration: float, mood: str = ""
    ) -> "str | None":
        """Delegate to T2V service — Replicate API (CogVideoX / Wan2.1)."""
        try:
            from .t2v_broll_service import T2VBrollService
            mood_tag = f", {mood}" if mood else ", cinematic"
            prompt = (
                f"Cinematic 4K vertical footage of {keyword}, "
                f"smooth camera motion{mood_tag}, no text, no watermark"
            )
            return await T2VBrollService().generate(prompt=prompt, duration=duration)
        except Exception as exc:
            logger.debug("T2V B-roll failed for '%s': %s", keyword, exc)
            return None

    async def _generate_ltxv_broll(
        self, keyword: str, duration: float, mood: str = ""
    ) -> "str | None":
        """Generate B-roll via local LTX-Video (ComfyUI)."""
        if not self._ltxv_enabled:
            return None
        try:
            from ..comfyui_bridge import ComfyUIBridge
            bridge = ComfyUIBridge()
            
            mood_tag = f", {mood}" if mood else ", cinematic"
            prompt = (
                f"Cinematic vertical footage of {keyword}, "
                f"smooth camera motion{mood_tag}, no text, no watermark, "
                f"4K quality, professional lighting"
            )
            
            import tempfile
            output_path = Path(tempfile.mktemp(suffix=".mp4", dir="/app/temp/uploads"))
            
            result = await bridge.generate_ltxv_broll(prompt, output_path, duration=duration)
            await bridge.close()
            
            if result and result.exists() and result.stat().st_size > 5000:
                logger.info("LTXV B-roll generated for '%s': %s", keyword, result.name)
                return str(result)
            return None
        except Exception as exc:
            logger.debug("LTXV B-roll failed for '%s': %s", keyword, exc)
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_contextual_broll: "ContextualBroll | None" = None


def get_contextual_broll() -> ContextualBroll:
    global _contextual_broll
    if _contextual_broll is None:
        _contextual_broll = ContextualBroll()
    return _contextual_broll
