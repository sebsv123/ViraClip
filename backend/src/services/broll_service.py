"""
BRoll Service - AI-powered B-roll injection for viral video enhancement.

Provider priority (configurable via BROLL_PROVIDER_PRIORITY):
  premium_first (default):
    1. LTXV / ComfyUI local generation  (best quality, zero API cost)
    2. T2V Replicate                    (cloud generative, paid)
    3. Pexels / Pixabay / Coverr stock  (free, lower relevance)
  stock_first:
    1. Pexels / Pixabay / Coverr stock
    2. LTXV / ComfyUI
    3. T2V Replicate

Pipeline:
  1. Keyword extraction   — Groq llama-3.1-8b-instant extracts 2-3 visual search terms
  2. Asset fetch           — ordered by provider priority with quality gating
  3. Silence detection     — librosa finds gaps > 1.5 s in segment audio
  4. FFmpeg overlay        — inserts B-roll with fade-in/out at timestamps
"""
import asyncio
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import httpx

from ..config import Config, get_config
from ..comfyui_bridge import ComfyUIBridge, COMFYUI_ENABLED, LTXV_ENABLED
from .broll_compositor import compose_overlay, probe_duration
from .scene_broll_placer import get_insert_timestamps
from .broll_provider_strategy import (
    BROLL_PROVIDER_PRIORITY,
    BROLL_ENABLE_PREMIUM,
    BROLL_ENABLE_STOCK,
    ProviderType,
    get_provider_order,
    diagnose_providers,
    passes_quality_gate,
)

logger = logging.getLogger(__name__)

# ── B-roll tuning ─────────────────────────────────────────────────────────────
_BROLL_DOWNLOAD_TIMEOUT = int(os.environ.get("BROLL_DOWNLOAD_TIMEOUT", "30"))
_MIN_SILENCE_SEC = float(os.environ.get("BROLL_MIN_SILENCE_SEC", "1.5"))
_BROLL_DURATION = float(os.environ.get("BROLL_DURATION", "2.5"))
_FADE_DURATION = float(os.environ.get("BROLL_FADE_DURATION", "0.6"))
_CACHE_TTL_DAYS = int(os.environ.get("BROLL_CACHE_TTL_DAYS", "7"))
_BROLL_MAX_OVERLAYS = int(os.environ.get("BROLL_MAX_OVERLAYS", "8"))

# ── Semantic keyword classification for generative B-roll ────────────────────
_MOTION_KEYWORDS = {
    "run", "race", "crowd", "explosion", "fast", "chase", "build",
    "construct", "drive", "fly", "jump", "fight", "sport", "traffic",
    "running", "speed", "motion", "action", "dynamic", "movement"
}
_ABSTRACT_KEYWORDS = {
    "money", "fear", "love", "future", "success", "death", "dream",
    "freedom", "power", "danger", "opportunity", "wealth", "family",
    "insurance", "protection", "planning", "financial", "security",
    "hope", "trust", "growth", "innovation", "challenge", "goal"
}

def _select_broll_workflow(keyword: str) -> str:
    """Select appropriate workflow based on keyword semantics."""
    kw_tokens = set(keyword.lower().split())
    if kw_tokens & _MOTION_KEYWORDS:
        return "generate_broll"  # LTXV — better for motion
    elif kw_tokens & _ABSTRACT_KEYWORDS:
        return "generate_broll_flux"  # FLUX — better for abstract/emotional
    else:
        return "generate_broll"  # default LTXV

def _extract_mood(text: str) -> str:
    """Extract emotional mood from transcript context."""
    text_lower = text.lower()
    if any(w in text_lower for w in ["miedo", "fear", "peligro", "riesgo", "danger", "scary"]):
        return "tense dramatic dark shadows"
    elif any(w in text_lower for w in ["éxito", "success", "logro", "victoria", "win", "achieve"]):
        return "uplifting bright energetic golden"
    elif any(w in text_lower for w in ["familia", "family", "amor", "love", "care", "together"]):
        return "warm soft intimate cozy"
    elif any(w in text_lower for w in ["money", "wealth", "financial", "rich", "profit"]):
        return "luxurious sleek modern professional"
    else:
        return "neutral professional cinematic"

def build_broll_prompt(keyword: str, transcript_context: str = "") -> str:
    """
    Build cinematic prompt for ComfyUI from keyword and transcript context.
    Creates rich, non-literal descriptions that evoke the concept.
    """
    base = (
        f"cinematic vertical video 9:16, {keyword}, "
        "professional camera movement, shallow depth of field, "
        "golden hour lighting, high contrast, film grain, "
        "dynamic composition, no text, no watermark, "
        "broadcast quality, 4K, masterpiece"
    )
    if transcript_context:
        mood = _extract_mood(transcript_context)
        base += f", {mood} atmosphere"
    return base


class BrollService:
    """AI-powered B-roll injection service."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.broll_dir = Path(self.config.temp_dir) / "uploads/broll"
        self.broll_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. KEYWORD EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────

    async def extract_keywords(
        self,
        text: str,
        video_path: Optional[Path] = None,
        clip_duration: float = 0.0,
    ) -> List[str]:
        """
        Extract 2-3 visual B-roll keywords from *text*.

        If *video_path* is provided, YOLOv10 visual grounding filters out
        keywords whose subject is already visible in the clip — no B-roll
        needed for what the viewer can already see.
        """
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            logger.warning("[BRoll] GROQ_API_KEY not set — falling back to first 3 nouns")
            keywords = self._simple_keyword_fallback(text)
            return await self._apply_yolo_filter(keywords, video_path, clip_duration)

        prompt = (
            "You are a cinematic B-roll director for a viral video. "
            "Analyze this transcript and extract 2-3 VISUAL CONCEPTS that would make the video WOW.\n\n"
            "CONTEXT RULES:\n"
            "1. Keywords must EXACTLY match what the speaker is saying IN THIS MOMENT\n"
            "2. Choose CINEMATIC, MOVIE-QUALITY visuals (not generic stock footage)\n"
            "3. Prefer: dynamic motion, dramatic lighting, professional cinematography\n"
            "4. AVOID: generic motivational concepts, abstract ideas, obvious stock tropes\n"
            "5. FOCUS ON: specific actions, detailed environments, emotional moments\n\n"
            "QUALITY CHECK:\n"
            "- Would this look like a Netflix documentary? → YES = good keyword\n"
            "- Could this be a movie scene? → YES = good keyword\n"
            "- Does it have motion and depth? → YES = good keyword\n\n"
            "EXAMPLES:\n"
            '- Talking about hard work → ["sweat droplets on forehead close-up", "hands typing furiously on keyboard", "clock hands moving rapidly"]\n'
            '- Talking about money → ["gold coins falling in slow motion", "luxury car headlights at night", "stack of cash being counted"]\n'
            '- Talking about nature → ["drone shot of forest canopy", "waves crashing dramatic rocks", "time-lapse blooming flower"]\n\n'
            "Reply with ONLY a JSON array of cinematic search terms.\n\n"
            f"TRANSCRIPT: {text[:600]}"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    json={
                        "model": "llama-3.1-8b-instant",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 60,
                        "temperature": 0.2,
                    },
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Parse the JSON array
                keywords = json.loads(content)
                if isinstance(keywords, list):
                    result = [str(k).strip() for k in keywords[:3] if k]
                    logger.info(f"[BRoll] Keywords extracted: {result}")
                    return await self._apply_yolo_filter(result, video_path, clip_duration)
        except Exception as e:
            logger.warning(f"[BRoll] Keyword extraction failed: {e}")
        fallback = self._simple_keyword_fallback(text)
        return await self._apply_yolo_filter(fallback, video_path, clip_duration)

    async def _apply_yolo_filter(
        self,
        keywords: List[str],
        video_path: Optional[Path],
        clip_duration: float,
    ) -> List[str]:
        """Filter *keywords* using YOLOv10 visual grounding on *video_path*."""
        if not video_path or clip_duration <= 0:
            return keywords
        try:
            from .yolo_detector import get_visual_context, filter_keywords_with_yolo
            ctx = await get_visual_context(video_path, clip_duration)
            filtered = filter_keywords_with_yolo(keywords, ctx["detected_labels"])
            if filtered != keywords:
                logger.info(
                    "[BRoll] YOLO filtered %d → %d keywords: %s → %s",
                    len(keywords), len(filtered), keywords, filtered,
                )
            return filtered
        except Exception as exc:
            logger.debug("[BRoll] YOLO filter skipped: %s", exc)
            return keywords

    @staticmethod
    def _simple_keyword_fallback(text: str) -> List[str]:
        """Return safe English stock-video keywords as a basic fallback."""
        # Always return generic English terms — never pass raw transcript words
        # (which may be in another language and return irrelevant stock footage)
        return ["nature", "landscape", "people"]

    # ──────────────────────────────────────────────────────────────────────────
    # 2. PROVIDER DIAGNOSTICS
    # ──────────────────────────────────────────────────────────────────────────

    def log_provider_status(self) -> dict:
        """Log and return availability of all B-roll providers.

        Delegates to the centralised broll_provider_strategy module.
        """
        status = diagnose_providers()
        return status.as_dict()

    # ──────────────────────────────────────────────────────────────────────────
    # 3. QUALITY GATING
    # ──────────────────────────────────────────────────────────────────────────

    def _is_cache_fresh(self, path: Path) -> bool:
        """Return True if *path* exists and was modified within _CACHE_TTL_DAYS."""
        import time as _time
        if not path.exists() or path.stat().st_size < 1_000:
            return False
        age_days = (_time.time() - path.stat().st_mtime) / 86400
        return age_days <= _CACHE_TTL_DAYS

    @staticmethod
    def _passes_quality_gate(path: Path, provider: str) -> bool:
        """Unified quality gate — delegates to broll_provider_strategy."""
        return passes_quality_gate(path, provider)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. ASSET FETCH — strategy-driven dispatch (single source of truth)
    # ──────────────────────────────────────────────────────────────────────────

    async def fetch_broll_asset(self, keyword: str) -> Optional[Path]:
        """Fetch the best B-roll asset for *keyword* using provider order
        from broll_provider_strategy.get_provider_order().

        This is the ONLY method that routes to individual providers.
        No other file should duplicate this routing logic.
        """
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        provider_order = get_provider_order()  # single source of truth

        for provider_type in provider_order:
            result = await self._try_provider(provider_type, keyword, safe)
            if result:
                return result

        logger.warning("[BRoll] ALL PROVIDERS EXHAUSTED for keyword='%s' "
                       "(priority=%s, order=%s)",
                       keyword, BROLL_PROVIDER_PRIORITY,
                       [p.value for p in provider_order])
        return None

    async def _try_provider(
        self, provider_type: ProviderType, keyword: str, safe: str
    ) -> Optional[Path]:
        """Dispatch to a single provider. Returns Path on success, None on failure."""
        if provider_type == ProviderType.LOCAL:
            return self._try_local_cache(keyword, safe)
        if provider_type == ProviderType.LTXV:
            return await self._try_ltxv(keyword, safe)
        if provider_type == ProviderType.ANIMATEDIFF:
            return await self._try_animatediff(keyword, safe)
        if provider_type == ProviderType.T2V_REPLICATE:
            return await self._try_t2v(keyword, safe)
        if provider_type == ProviderType.STOCK_VIDEO:
            return await self._try_stock_video(keyword, safe)
        if provider_type == ProviderType.STOCK_IMAGE:
            return await self._try_stock_image(keyword, safe)
        if provider_type == ProviderType.CACHE:
            return self._try_disk_cache(keyword, safe)
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # 5. INDIVIDUAL PROVIDER METHODS
    # ──────────────────────────────────────────────────────────────────────────

    def _try_local_cache(self, keyword: str, safe: str) -> Optional[Path]:
        """Check local disk cache for a fresh asset."""
        cached_video = self.broll_dir / f"{safe}.mp4"
        cached_photo = self.broll_dir / f"{safe}.jpg"
        if self._is_cache_fresh(cached_video):
            logger.info("[BRoll] ✓ PROVIDER=local keyword='%s' → %s", keyword, cached_video.name)
            return cached_video
        if self._is_cache_fresh(cached_photo):
            logger.info("[BRoll] ✓ PROVIDER=local keyword='%s' → %s", keyword, cached_photo.name)
            return cached_photo
        return None

    async def _try_ltxv(
        self, keyword: str, safe: str, transcript_context: str = ""
    ) -> Optional[Path]:
        """Try LTXV/FLUX generative B-roll based on keyword semantics."""
        if not LTXV_ENABLED:
            logger.debug("[BRoll] LTXV disabled (LTXV_ENABLED=false)")
            return None

        out_path = self.broll_dir / f"gen_{safe}.mp4"

        try:
            bridge = ComfyUIBridge()
            available = await bridge.is_available()
            if not available:
                logger.info("[BRoll] ✗ PROVIDER=ltxv SKIP — ComfyUI not reachable")
                return None

            # Select workflow based on keyword semantics
            workflow = _select_broll_workflow(keyword)
            prompt = build_broll_prompt(keyword, transcript_context)

            logger.info(f"[BRoll] Using workflow={workflow} for keyword='{keyword}'")

            if workflow == "generate_broll_flux":
                result = await bridge.generate_flux_broll(prompt, out_path)
            else:
                result = await bridge.generate_ltxv_broll(prompt, out_path, duration=_BROLL_DURATION)

            await bridge.close()

            if result and self._passes_quality_gate(out_path, workflow):
                logger.info("[BRoll] ✓ PROVIDER=%s keyword='%s' → %s", workflow, keyword, out_path.name)
                return out_path
            logger.info("[BRoll] ✗ PROVIDER=%s keyword='%s' → failed or quality reject", workflow, keyword)
        except Exception as exc:
            logger.warning("[BRoll] ✗ PROVIDER=ltxv keyword='%s' error: %s", keyword, exc)

        return None

    async def _try_animatediff(self, keyword: str, safe: str) -> Optional[Path]:
        """Try ComfyUI AnimateDiff. Returns Path or None."""
        if not COMFYUI_ENABLED:
            logger.debug("[BRoll] ComfyUI AnimateDiff disabled (COMFYUI_ENABLED=false)")
            return None

        out_path = self.broll_dir / f"gen_{safe}.mp4"

        try:
            bridge = ComfyUIBridge()
            available = await bridge.is_available()
            if available:
                prompt = f"Cinematic vertical footage of {keyword}, smooth, professional"
                result = await bridge.generate_broll(prompt, out_path, duration=_BROLL_DURATION)
                await bridge.close()
                if result and self._passes_quality_gate(out_path, "animatediff"):
                    logger.info("[BRoll] ✓ PROVIDER=animatediff keyword='%s' → %s", keyword, out_path.name)
                    return out_path
                logger.info("[BRoll] ✗ PROVIDER=animatediff keyword='%s' → failed", keyword)
            else:
                logger.info("[BRoll] ✗ PROVIDER=animatediff SKIP — ComfyUI not reachable")
        except Exception as exc:
            logger.warning("[BRoll] ✗ PROVIDER=animatediff keyword='%s' error: %s", keyword, exc)

        return None

    async def _try_t2v(self, keyword: str, safe: str) -> Optional[Path]:
        """Try T2V Replicate. Returns Path or None."""
        try:
            from .t2v_broll_service import T2VBrollService
            if T2VBrollService.is_available():
                t2v = T2VBrollService()
                t2v_prompt = f"Cinematic 4K vertical footage of {keyword}, smooth camera, no text"
                t2v_out = self.broll_dir / f"t2v_{safe}.mp4"
                res = await t2v.generate(prompt=t2v_prompt, duration=_BROLL_DURATION, output_path=str(t2v_out))
                if res and t2v_out.exists() and self._passes_quality_gate(t2v_out, "t2v_replicate"):
                    logger.info("[BRoll] ✓ PROVIDER=t2v_replicate keyword='%s' → %s", keyword, t2v_out.name)
                    return t2v_out
                logger.info("[BRoll] ✗ PROVIDER=t2v_replicate keyword='%s' → failed", keyword)
        except Exception as exc:
            logger.debug("[BRoll] ✗ PROVIDER=t2v_replicate keyword='%s' error: %s", keyword, exc)

        return None

    async def _try_stock_video(self, keyword: str, safe: str) -> Optional[Path]:
        """Try Pexels → Pixabay → Coverr. Returns Path or None."""
        if not BROLL_ENABLE_STOCK:
            logger.debug("[BRoll] Stock providers disabled (BROLL_ENABLE_STOCK=false)")
            return None

        cached_video = self.broll_dir / f"{safe}.mp4"

        # ── Parallel stock video search ───────────────────────────────────────
        pexels_task  = asyncio.create_task(self._search_pexels(keyword))
        pixabay_task = asyncio.create_task(self._search_pixabay(keyword))
        coverr_task  = asyncio.create_task(self._search_coverr(keyword))

        results = await asyncio.gather(pexels_task, pixabay_task, coverr_task,
                                       return_exceptions=True)
        providers = ["pexels_video", "pixabay_video", "coverr_video"]
        video_urls = [(r, p) for r, p in zip(results, providers) if isinstance(r, str) and r]

        for url, provider in video_urls:
            result = await self._download(url, cached_video)
            if result and self._passes_quality_gate(cached_video, provider):
                logger.info("[BRoll] ✓ PROVIDER=%s keyword='%s' → %s", provider, keyword, result.name)
                return result
            elif result:
                logger.info("[BRoll] ✗ PROVIDER=%s keyword='%s' → quality reject", provider, keyword)

        return None

    async def _try_stock_image(self, keyword: str, safe: str) -> Optional[Path]:
        """Try Pexels Photos. Returns Path or None."""
        if not BROLL_ENABLE_STOCK:
            logger.debug("[BRoll] Stock providers disabled (BROLL_ENABLE_STOCK=false)")
            return None

        cached_photo = self.broll_dir / f"{safe}.jpg"

        photo = await self._search_pexels_photos_and_download(keyword, safe)
        if photo and self._passes_quality_gate(photo, "pexels_photo"):
            logger.info("[BRoll] ✓ PROVIDER=pexels_photo keyword='%s' → %s", keyword, photo.name)
            return photo

        return None

    def _try_disk_cache(self, keyword: str, safe: str) -> Optional[Path]:
        """Alias for _try_local_cache (disk cache = local cache)."""
        return self._try_local_cache(keyword, safe)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. API SEARCH HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _search_pexels_photos_and_download(self, keyword: str, safe_name: str) -> Optional[Path]:
        """Search Pexels Photos API and download a portrait image for *keyword*."""
        key = self.config.pexels_api_key or os.getenv("PEXELS_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.pexels.com/v1/search",
                    headers={"Authorization": key},
                    params={"query": keyword, "per_page": 3, "orientation": "portrait"},
                )
                resp.raise_for_status()
                photos = resp.json().get("photos", [])
                if not photos:
                    return None
                src = photos[0].get("src", {})
                photo_url = src.get("portrait") or src.get("large2x") or src.get("large")
                if not photo_url:
                    return None
                dest = self.broll_dir / f"{safe_name}.jpg"
                img_resp = await client.get(photo_url, follow_redirects=True, timeout=_BROLL_DOWNLOAD_TIMEOUT)
                img_resp.raise_for_status()
                dest.write_bytes(img_resp.content)
                logger.info(f"[BRoll] Pexels photo: '{keyword}' → {dest} ({dest.stat().st_size // 1024} KB)")
                return dest
        except Exception as e:
            logger.warning(f"[BRoll] Pexels Photos search error for '{keyword}': {e}")
            return None

    async def _search_pexels(self, query: str) -> Optional[str]:
        key = self.config.pexels_api_key or os.getenv("PEXELS_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.pexels.com/videos/search",
                    headers={"Authorization": key},
                    params={"query": query, "per_page": 5, "orientation": "portrait"},
                )
                resp.raise_for_status()
                videos = resp.json().get("videos", [])
                if not videos:
                    return None
                for vf in videos[0].get("video_files", []):
                    w, h = vf.get("width", 0), vf.get("height", 0)
                    if h > w and vf.get("file_type") == "video/mp4":
                        logger.info(f"[BRoll] Pexels hit for '{query}': {vf['link'][:60]}...")
                        return vf["link"]
                # fallback: first file regardless of orientation
                files = videos[0].get("video_files", [])
                return files[0]["link"] if files else None
        except Exception as e:
            logger.warning(f"[BRoll] Pexels search error: {e}")
            return None

    async def _search_coverr(self, query: str) -> Optional[str]:
        """Search Coverr CC0 video library."""
        if not self.config.coverr_enabled:
            logger.debug("[BRoll] Coverr disabled (no API key)")
            return None
        key = self.config.coverr_api_key
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.coverr.co/videos",
                    params={"keywords": query, "token": key, "per_page": 5},
                )
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("hits", []):
                    # Prefer clips with portrait dimensions and duration 3-10s
                    dur = item.get("duration", 0)
                    w   = item.get("width", 0)
                    h   = item.get("height", 0)
                    url = item.get("urls", {}).get("mp4_download") or item.get("url")
                    if url and 3 <= dur <= 12 and h >= 720:
                        logger.info(f"[BRoll] Coverr hit for '{query}': {url[:60]}...")
                        return url
                # Any clip if none match portrait preference
                for item in data.get("hits", []):
                    url = item.get("urls", {}).get("mp4_download") or item.get("url")
                    if url:
                        return url
        except Exception as e:
            logger.debug(f"[BRoll] Coverr search error: {e}")
        return None

    async def _search_pixabay(self, query: str) -> Optional[str]:
        key = self.config.pixabay_api_key or os.getenv("PIXABAY_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://pixabay.com/api/videos/",
                    params={
                        "key": key,
                        "q": query,
                        "video_type": "film",
                        "orientation": "vertical",
                        "per_page": 3,
                    },
                )
                resp.raise_for_status()
                hits = resp.json().get("hits", [])
                if not hits:
                    return None
                videos = hits[0].get("videos", {})
                for size in ("medium", "small", "large"):
                    url = videos.get(size, {}).get("url")
                    if url:
                        logger.info(f"[BRoll] Pixabay hit for '{query}': {url[:60]}...")
                        return url
        except Exception as e:
            logger.warning(f"[BRoll] Pixabay search error: {e}")
        return None

    async def _download(self, url: str, dest: Path) -> Optional[Path]:
        try:
            async with httpx.AsyncClient(timeout=_BROLL_DOWNLOAD_TIMEOUT, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        async for chunk in resp.aiter_bytes(8192):
                            f.write(chunk)
            logger.info(f"[BRoll] Downloaded: {dest} ({dest.stat().st_size // 1024} KB)")
            return dest
        except Exception as e:
            logger.error(f"[BRoll] Download failed {url[:60]}: {e}")
            dest.unlink(missing_ok=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # 3. SILENCE DETECTION
    # ──────────────────────────────────────────────────────────────────────────

    def detect_silences(
        self,
        audio_path: str,
        min_duration: float = _MIN_SILENCE_SEC,
    ) -> List[Tuple[float, float]]:
        """Return list of (start, end) silence gaps >= *min_duration* seconds."""
        try:
            import librosa
            import numpy as np

            y, sr = librosa.load(audio_path, sr=16000, mono=True)
            rms = librosa.feature.rms(y=y, frame_length=512, hop_length=256)[0]
            times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=256)

            threshold = float(np.percentile(rms, 15))  # bottom 15% = silence
            silences: List[Tuple[float, float]] = []
            in_silence = False
            silence_start = 0.0

            for i, (t, energy) in enumerate(zip(times, rms)):
                if energy < threshold and not in_silence:
                    in_silence = True
                    silence_start = float(t)
                elif energy >= threshold and in_silence:
                    in_silence = False
                    duration = float(t) - silence_start
                    if duration >= min_duration:
                        silences.append((silence_start, float(t)))

            logger.info(f"[BRoll] Detected {len(silences)} silence gaps >= {min_duration}s")
            return silences
        except Exception as e:
            logger.warning(f"[BRoll] Silence detection failed: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # 4. FFMPEG OVERLAY INSERTION
    # ──────────────────────────────────────────────────────────────────────────

    async def insert_broll(
        self,
        video_path: str,
        output_path: str,
        broll_path: str,
        timestamp: float,
        overlay_duration: float = _BROLL_DURATION,
        fade: float = _FADE_DURATION,
    ) -> bool:
        """
        Overlay *broll_path* on *video_path* at *timestamp* for *overlay_duration* seconds.
        Delegates to broll_compositor.compose_overlay for format-adaptive scaling.
        Returns True on success.
        """
        try:
            ok = compose_overlay(
                main_path=video_path,
                broll_path=broll_path,
                output_path=output_path,
                timestamp=timestamp,
                duration=overlay_duration,
                fade=fade,
            )
            if ok:
                logger.info(f"[BRoll] ✓ Overlay inserted at t={timestamp:.1f}s → {output_path}")
            else:
                logger.error(f"[BRoll] compose_overlay returned False for {video_path}")
            return ok
        except Exception as e:
            logger.error(f"[BRoll] insert_broll exception: {e}")
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ──────────────────────────────────────────────────────────────────────────

    async def process_clip(
        self,
        video_path: str,
        output_path: str,
        segment_text: str,
        audio_path: Optional[str] = None,
        clip_duration: float = 0.0,
        max_overlays: int = 3,
        overlay_duration_s: float = _BROLL_DURATION,
        words_with_timestamps: Optional[List[Dict]] = None,
        precomputed_keywords: Optional[List[str]] = None,
        broll_fade_s: float = 0.25,
    ) -> str:
        """
        Full B-roll pipeline for a single clip.

        1. Extract keywords (or use precomputed_keywords from AI brain)
        2. Fetch best asset per keyword via provider-priority cascade
           (premium_first: LTXV → T2V → Stock | stock_first: Stock → LTXV → T2V)
        3. Insert B-roll overlays at spoken-word timestamps or scene boundaries

        Returns *output_path* on success, *video_path* (original) on failure.
        """
        try:
            # Step 1 — keywords: use AI brain's choices if available, else NLP extraction
            if precomputed_keywords:
                keywords = list(precomputed_keywords)
                logger.info(f"[BRoll] Using AI keywords: {keywords}")
            else:
                keywords = await self.extract_keywords(segment_text)

                # Enhanced B-roll: análisis de contexto visual para keywords más precisos
                try:
                    from .enhanced_broll_service import EnhancedBrollService
                    _ebs = EnhancedBrollService()
                    _opportunities = await _ebs.analyze_broll_opportunities(
                        transcript=segment_text,
                        video_path=Path(video_path),
                        clip_duration=clip_duration,
                    )
                    if _opportunities:
                        _enhanced_kws = [
                            kw for opp in _opportunities[:2]
                            for kw in opp.suggested_keywords[:2]
                            if kw not in keywords
                        ]
                        keywords = _enhanced_kws + keywords
                        logger.info(f"[BRoll] Enhanced context keywords: {_enhanced_kws}")
                except Exception as _ebs_e:
                    logger.debug(f"[BRoll] Enhanced B-roll analysis skipped: {_ebs_e}")

                # YOLO augmentation: detect objects actually visible in the clip
                try:
                    from ..video_processing.object_detection import detect_objects_in_video
                    yolo_kws = await detect_objects_in_video(video_path, max_frames=4)
                    if yolo_kws:
                        for kw in reversed(yolo_kws[:2]):
                            if kw not in keywords:
                                keywords.insert(0, kw)
                        logger.info(f"[BRoll] YOLO augmented keywords: {keywords}")
                except Exception as _yolo_e:
                    logger.debug(f"[BRoll] YOLO augmentation skipped: {_yolo_e}")

            # Semantic B-roll: Pexels + sentence-transformers para un asset semántico extra
            try:
                from .semantic_broll_service import create_semantic_broll_service
                _sbs = create_semantic_broll_service()
                _sem_result = await _sbs.find_broll_for_segment(
                    transcript_segment=segment_text,
                    segment_duration=clip_duration or 4.5,
                )
                if _sem_result and _sem_result.get("keywords"):
                    _sem_kws = [k for k in _sem_result["keywords"] if k not in keywords]
                    if _sem_kws:
                        keywords = _sem_kws[:2] + keywords
                        logger.info(f"[BRoll] Semantic keywords added: {_sem_kws[:2]}")
            except Exception as _sbs_e:
                logger.debug(f"[BRoll] Semantic B-roll skipped: {_sbs_e}")

            if not keywords:
                return video_path

            # Step 2 — PREMIUM GENERATION FIRST (explicit calls before cascade)
            # Try LTXV/ComfyUI/T2V explicitly before falling back to stock APIs
            broll_assets: List[Path] = []
            premium_attempts = 0
            premium_success = 0
            
            # >>> EXPLICIT PREMIUM ATTEMPTS (before stock fallback) <<<
            for kw in keywords[:max(3, max_overlays)]:
                if len(broll_assets) >= max_overlays:
                    break
                
                asset = None
                
                # 1. Try LTXV first (best quality, local)
                # Note: _try_ltxv already includes quality gate internally
                if LTXV_ENABLED:
                    premium_attempts += 1
                    try:
                        asset = await self._try_ltxv(kw, kw.replace(' ', '_')[:30])
                        if asset:  # Quality gate already applied in _try_ltxv
                            broll_assets.append(asset)
                            premium_success += 1
                            logger.info("[BRoll] ✓ LTXV success for '%s': %s", kw, asset)
                            continue
                    except Exception as e:
                        logger.warning("[BRoll] LTXV failed for '%s': %s", kw, e)
                
                # 2. Try AnimateDiff (ComfyUI local)
                # Note: _try_animatediff already includes quality gate internally
                if COMFYUI_ENABLED and len(broll_assets) < max_overlays:
                    premium_attempts += 1
                    try:
                        asset = await self._try_animatediff(kw, kw.replace(' ', '_')[:30])
                        if asset:  # Quality gate already applied in _try_animatediff
                            broll_assets.append(asset)
                            premium_success += 1
                            logger.info("[BRoll] ✓ AnimateDiff success for '%s': %s", kw, asset)
                            continue
                    except Exception as e:
                        logger.warning("[BRoll] AnimateDiff failed for '%s': %s", kw, e)
                
                # 3. Try T2V Replicate (cloud)
                # Note: _try_t2v already includes quality gate internally
                if len(broll_assets) < max_overlays:
                    try:
                        from .t2v_broll_service import T2VBrollService
                        if T2VBrollService.is_available():
                            premium_attempts += 1
                            asset = await self._try_t2v(kw, kw.replace(' ', '_')[:30])
                            if asset:  # Quality gate already applied in _try_t2v
                                broll_assets.append(asset)
                                premium_success += 1
                                logger.info("[BRoll] ✓ T2V success for '%s': %s", kw, asset)
                                continue
                    except Exception as e:
                        logger.warning("[BRoll] T2V failed for '%s': %s", kw, e)
                
                # 4. Stock fallback (only if premium failed)
                if len(broll_assets) < max_overlays:
                    logger.info("[BRoll] Premium failed for '%s', falling back to stock", kw)
                    asset = await self.fetch_broll_asset(kw)
                    if asset:
                        broll_assets.append(asset)
                        logger.info("[BRoll] ✓ Stock fallback for '%s': %s", kw, asset)
            
            logger.info("[BRoll] Premium stats: %d/%d successful (%d%%)", 
                       premium_success, premium_attempts, 
                       (premium_success/max(premium_attempts,1)*100))

            if not broll_assets:
                logger.info(f"[BRoll] No assets fetched for keywords {keywords} — skipping")
                return video_path

            # Step 3 — find timestamps: prefer exact spoken moment for each keyword
            n_wanted = min(len(broll_assets), max_overlays)
            insert_timestamps: List[float] = []

            if words_with_timestamps:
                # Map keyword → timestamp where it is spoken in the clip
                for kw in keywords[:n_wanted]:
                    kw_lower = kw.lower().strip()
                    for w in words_with_timestamps:
                        w_text = (w.get("word") or w.get("text") or "").lower().strip(".,!?-'\"")
                        if kw_lower == w_text or kw_lower in w_text or w_text in kw_lower:
                            ts = float(w.get("start", 0))
                            # Don't place B-roll in the first 0.8s (protect hook)
                            if ts >= 0.8 and all(abs(ts - t) > 2.5 for t in insert_timestamps):
                                insert_timestamps.append(ts)
                            break
                logger.info("[BRoll] Keyword→spoken timestamps: %s",
                            [f"{t:.1f}s" for t in insert_timestamps])

            # Fill remaining slots with scene-detected timestamps
            if len(insert_timestamps) < n_wanted:
                scene_ts = get_insert_timestamps(
                    video_path=video_path,
                    max_n=n_wanted - len(insert_timestamps),
                    clip_duration=clip_duration or None,
                )
                for ts in scene_ts:
                    if all(abs(ts - t) > 2.5 for t in insert_timestamps):
                        insert_timestamps.append(ts)

            insert_timestamps.sort()

            # Protect hook (0–2s) and CTA (last 2s): never overlay B-roll there.
            _hook_guard = 2.0
            _cta_guard  = max(0.0, (clip_duration or 0) - 2.0)
            if _cta_guard > _hook_guard:
                insert_timestamps = [
                    t for t in insert_timestamps
                    if _hook_guard <= t <= _cta_guard
                ]
            if not insert_timestamps and broll_assets:
                # Fallback: midpoint is always safe
                _mid = (clip_duration or 10.0) / 2.0
                insert_timestamps = [_mid]

            # Step 3.5 — BrollEffectsEngine: apply cinematic effect (ken burns / pan) per asset
            _enhanced_assets: List[Path] = []
            try:
                from .broll_effects_engine import get_smart_broll_effect, build_broll_effect_filter
                import subprocess as _sp
                for _ba in broll_assets:
                    try:
                        _effect = get_smart_broll_effect(
                            is_image=_ba.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"),
                        )
                        _efx_filter = build_broll_effect_filter(
                            effect_type=_effect,
                            width=1080, height=1920,
                            duration=overlay_duration_s,
                        )
                        _efx_out = _ba.with_name(f"efx_{_ba.name}")
                        _efx_cmd = [
                            "ffmpeg", "-y", "-i", str(_ba),
                            "-vf", _efx_filter,
                            "-t", str(overlay_duration_s),
                            "-c:v", "libx264", "-preset", "ultrafast", "-an",
                            str(_efx_out),
                        ]
                        _efx_res = _sp.run(_efx_cmd, capture_output=True, timeout=30)
                        if _efx_res.returncode == 0 and _efx_out.exists():
                            _enhanced_assets.append(_efx_out)
                            logger.info(f"[BRoll] ✓ Effect {_effect.value} applied to {_ba.name}")
                        else:
                            _enhanced_assets.append(_ba)
                    except Exception:
                        _enhanced_assets.append(_ba)
                broll_assets = _enhanced_assets
            except Exception as _bee_e:
                logger.debug(f"[BRoll] Effects engine skipped: {_bee_e}")

            # Step 3.6 — Apply entry/exit transitions to each enhanced asset
            _transitioned_assets: List[Path] = []
            for _ba in broll_assets:
                try:
                    _trans_out = _ba.with_name(f"trans_{_ba.name}")
                    _trans_result = apply_broll_transitions(
                        broll_path=str(_ba),
                        output_path=str(_trans_out),
                        duration=overlay_duration_s,
                        transition_duration=0.25
                    )
                    if _trans_result and Path(_trans_result).exists():
                        _transitioned_assets.append(Path(_trans_result))
                        logger.info(f"[BRoll] ✓ Transitions applied to {_ba.name}")
                    else:
                        _transitioned_assets.append(_ba)
                except Exception as _te:
                    logger.debug(f"[BRoll] Transition skipped for {_ba.name}: {_te}")
                    _transitioned_assets.append(_ba)
            broll_assets = _transitioned_assets

            # Step 4 — build (timestamp, asset, duration) pairs and apply in one pass
            broll_pairs: List[Tuple[float, str, float]] = []
            for ts, asset in zip(insert_timestamps, broll_assets):
                dur = min(overlay_duration_s, max(1.5, (clip_duration or overlay_duration_s + ts + 1) - ts - 0.5))
                broll_pairs.append((ts, str(asset), dur))

            if len(broll_pairs) == 1:
                ts, asset_path, dur = broll_pairs[0]
                ok = await self.insert_broll(
                    video_path=video_path,
                    fade=broll_fade_s,
                    output_path=output_path,
                    broll_path=asset_path,
                    timestamp=ts,
                    overlay_duration=dur,
                )
            else:
                from .broll_compositor import compose_overlay_multi
                ok = await compose_overlay_multi(
                    fade=broll_fade_s,
                    main_path=video_path,
                    broll_pairs=broll_pairs,
                    output_path=output_path,
                )

            if ok:
                logger.info(f"[BRoll] ✓ {len(broll_pairs)} overlays applied: {[f't={t:.1f}s' for t,_,_ in broll_pairs]}")
            return output_path if ok else video_path

        except Exception as e:
            logger.error(f"[BRoll] process_clip failed: {e}", exc_info=True)
            return video_path


# ──────────────────────────────────────────────────────────────────────────────
# B-ROLL TRANSITIONS — Entry and exit effects for cinematic feel
# ──────────────────────────────────────────────────────────────────────────────

def apply_broll_transitions(
    broll_path: str,
    output_path: str,
    duration: float,
    transition_duration: float = 0.25
) -> Optional[str]:
    """
    Apply zoom-punch entry and fade-out exit to B-roll clip.
    Entry: smooth zoom from 1.0 to 1.08 in first transition_duration seconds
    Exit: fade-out with slight motion blur in last transition_duration seconds
    """
    try:
        fade_out_start = max(0, duration - transition_duration)
        total_frames = int(duration * 30)
        zoom_frames = int(transition_duration * 30)

        # Build filter_complex with scale/crop, zoom-in entry and fade-out exit
        filter_complex = (
            f"[0:v]"
            f"scale=576:1024:force_original_aspect_ratio=increase,"
            f"crop=576:1024,"
            f"fade=t=in:st=0:d={transition_duration}:alpha=1,"
            f"zoompan=z='if(lte(in,{zoom_frames}),1.0+0.08*in/{zoom_frames},1.08)':"
            f"d={total_frames}:s=576x1024:fps=30,"
            f"fade=t=out:st={fade_out_start}:d={transition_duration}"
            f"[vout];"
            f"[0:a]"
            f"afade=t=in:st=0:d={transition_duration},"
            f"afade=t=out:st={fade_out_start}:d={transition_duration}"
            f"[aout]"
        )

        cmd = [
            "ffmpeg", "-y", "-i", broll_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "h264_nvenc", "-rc", "constqp", "-qp", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            # Fallback to software encoding if NVENC fails
            logger.warning("[BRoll] NVENC failed, retrying with libx264")
            cmd[cmd.index("h264_nvenc")] = "libx264"
            cmd[cmd.index("-rc")] = "-crf"
            cmd[cmd.index("-qp")] = "18"
            cmd.insert(cmd.index("-crf") + 2, "-preset")
            cmd.insert(cmd.index("-preset") + 1, "fast")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0 and Path(output_path).exists():
            logger.info(f"[BRoll] ✓ Transitions applied: {Path(output_path).name}")
            return output_path
        else:
            logger.warning(f"[BRoll] Transition filter failed: {result.stderr[:200]}")
            return None
    except Exception as e:
        logger.warning(f"[BRoll] apply_broll_transitions error: {e}")
        return None
