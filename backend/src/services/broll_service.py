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
from .editorial_broll_planner import BrollCueDecision, EditorialBrollPlanner
from .broll_provider_strategy import (
    BROLL_PROVIDER_PRIORITY,
    BROLL_ENABLE_STOCK,
    BROLL_MIN_CLIP_DURATION_SEC,
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
_BETA_CLEAN_BROLL_MIN_VISIBLE_S = 2.5
_BETA_CLEAN_BROLL_TARGET_S = 2.8
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".avif"}

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
        self.last_editorial_broll: List[Dict[str, Any]] = []

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
        """Return insurance/finance-first Spanish stock-video keywords as fallback."""
        # Beta: insurance/finance domain in Spanish — always return domain-relevant terms
        # that work well with Pexels/Coverr stock libraries
        text_lower = text.lower()
        # Detect insurance/finance context
        if any(w in text_lower for w in ["seguro", "seguros", "póliza", "cobertura", "prima",
                                          "indemnización", "siniestro", "reclamo", "aseguradora",
                                          "financial", "financiero", "inversión", "ahorro",
                                          "banco", "bank", "cuenta", "crédito", "hipoteca"]):
            return ["oficina ejecutivos reunión", "familia protección hogar",
                    "dinero calculadora ahorro", "documentos firma contrato",
                    "edificio corporativo moderno"]
        # Detect health/medical context
        if any(w in text_lower for w in ["salud", "hospital", "médico", "doctor", "clínica",
                                          "paciente", "enfermedad", "seguro salud"]):
            return ["hospital pasillo doctor", "manos doctor paciente",
                    "familia salud bienestar", "medicina laboratorio análisis"]
        # Generic Spanish fallback
        return ["oficina moderna profesional", "personas caminando ciudad",
                "tecnología computadora oficina", "naturaleza paisaje tranquilo"]

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

    async def fetch_editorial_broll_asset(self, keyword: str) -> Optional[Path]:
        """Fetch B-roll for editorial v1 without premium/generative providers."""
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        for provider_type in (
            ProviderType.LOCAL,
            ProviderType.STOCK_VIDEO,
            ProviderType.STOCK_IMAGE,
            ProviderType.CACHE,
        ):
            result = await self._try_provider(provider_type, keyword, safe)
            if result:
                return result
        logger.info("[editorial-broll] no stock/local asset for query=%s", keyword)
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
        task_id: Optional[str] = None,
        suggested_broll_cue_type: Optional[str] = None,
    ) -> str:
        """
        Full B-roll pipeline for a single clip.

        1. Plan editorial cues locally from the Spanish transcript
        2. Fetch stock/local assets for approved cue visual queries
        3. Insert B-roll overlays at the planner's approved timestamps

        Returns *output_path* on success, *video_path* (original) on failure.
        """
        try:
            self.last_editorial_broll = []
            # ── Duration guard: skip B-roll for very short clips ──────────────
            if clip_duration > 0 and clip_duration < BROLL_MIN_CLIP_DURATION_SEC:
                logger.info("[BRoll] SKIP — clip duration %.1fs < BROLL_MIN_CLIP_DURATION_SEC=%.1fs",
                            clip_duration, BROLL_MIN_CLIP_DURATION_SEC)
                return video_path

            planner = EditorialBrollPlanner()
            cue_decisions = planner.plan(
                transcript_segments=segment_text,
                clip_duration=clip_duration or probe_duration(video_path),
                word_timestamps=words_with_timestamps,
                max_cues=max_overlays,
                suggested_broll_cue_type=suggested_broll_cue_type,
            )
            approved_cues: List[BrollCueDecision] = [
                cue for cue in cue_decisions
                if cue.decision == "approve" and cue.visual_query and cue.start_s is not None
            ]
            rejected_cues = [cue for cue in cue_decisions if cue.decision == "reject"]
            logger.info(
                "[editorial-broll] planned cues approved=%d rejected=%d",
                len(approved_cues),
                len(rejected_cues),
            )
            for cue in approved_cues:
                logger.info(
                    "[editorial-broll] approve type=%s start=%.2f dur=%.2f query=%s reason=%s",
                    cue.cue_type,
                    cue.start_s or 0.0,
                    cue.duration_s,
                    cue.visual_query,
                    cue.reason,
                )
            for cue in rejected_cues:
                logger.info(
                    "[editorial-broll] reject type=%s reason=%s",
                    cue.cue_type,
                    cue.reason,
                )

            if not approved_cues:
                logger.info("[editorial-broll] no approved cues; skipping b-roll")
                return video_path

            # Step 2 — try LocalBrollAssetBank first, then stock fetch.
            from ..config import get_config as _get_cfg_asset
            _cfg_asset = _get_cfg_asset()
            _local_bank_enabled = (
                _cfg_asset.enable_local_broll_bank
                if hasattr(_cfg_asset, "enable_local_broll_bank")
                else True
            )

            broll_assets: List[Path] = []
            asset_cues: List[BrollCueDecision] = []
            asset_sources: List[str] = []
            for cue in approved_cues:
                if len(broll_assets) >= max_overlays:
                    break

                asset: Optional[Path] = None
                asset_source = "none"

                # Priority 1: LocalBrollAssetBank
                if _local_bank_enabled:
                    try:
                        from .local_broll_asset_bank import find_asset as _find_local_asset
                        from .local_broll_asset_bank import mark_used as _mark_asset_used
                        asset = _find_local_asset(cue.cue_type or "", task_id=task_id)
                        if asset is not None:
                            asset_source = "local"
                            _mark_asset_used(asset, task_id=task_id)
                    except Exception as _local_e:
                        logger.debug("[editorial-broll] local asset bank error: %s", _local_e)

                # Priority 2: stock fetch fallback
                if asset is None:
                    asset = await self.fetch_editorial_broll_asset(cue.visual_query or "")
                    if asset is not None:
                        asset_source = "stock"

                if asset:
                    broll_assets.append(asset)
                    asset_cues.append(cue)
                    asset_sources.append(asset_source)
                    logger.info("[editorial-broll] asset query=%s path=%s", cue.visual_query, asset)

            if not broll_assets:
                logger.info("[editorial-broll] approved cues had no stock/local assets; skipping b-roll")
                return video_path

            insert_timestamps: List[float] = [float(cue.start_s or 0.0) for cue in asset_cues]

            # Step 4 — build (timestamp, asset, duration) pairs and apply in one pass
            broll_pairs: List[Tuple[float, str, float]] = []
            broll_metadata: List[Dict[str, Any]] = []
            for ts, asset, cue, asset_source in zip(insert_timestamps, broll_assets, asset_cues, asset_sources):
                remaining = max(0.0, (clip_duration or cue.duration_s + ts + 1.0) - ts - 0.5)
                requested = max(float(cue.duration_s or 0.0), _BETA_CLEAN_BROLL_TARGET_S)
                effective = min(requested, remaining) if remaining > 0 else requested
                is_image = asset.suffix.lower() in _IMAGE_EXTS
                asset_duration = _BETA_CLEAN_BROLL_TARGET_S if is_image else probe_duration(asset)
                logger.info(
                    "[broll-duration] requested=%.2f asset_duration=%.2f effective=%.2f",
                    requested,
                    asset_duration,
                    effective,
                )
                if effective < _BETA_CLEAN_BROLL_MIN_VISIBLE_S:
                    logger.info("[broll-duration] skipped too short after clamp")
                    continue
                if not is_image and asset_duration < effective:
                    logger.info("[broll-duration] extended/looped to effective=%.2f", effective)
                broll_pairs.append((ts, str(asset), effective))
                broll_metadata.append({
                    "cue_type": cue.cue_type,
                    "trigger_text": cue.trigger_text,
                    "visual_query": cue.visual_query,
                    "asset_path": str(asset),
                    "asset_source": asset_source,
                    "start_s": ts,
                    "requested_duration": requested,
                    "asset_duration": asset_duration,
                    "effective_duration": effective,
                    "transition": cue.transition,
                    "reason": cue.reason,
                })

            if not broll_pairs:
                logger.info("[editorial-broll] approved cues but no suitable asset found")
                return video_path

            editorial_fade_s = 0.0 if all(cue.transition == "clean_cut" for cue in asset_cues) else broll_fade_s
            if len(broll_pairs) == 1:
                ts, asset_path, dur = broll_pairs[0]
                ok = await self.insert_broll(
                    video_path=video_path,
                    fade=editorial_fade_s,
                    output_path=output_path,
                    broll_path=asset_path,
                    timestamp=ts,
                    overlay_duration=dur,
                )
            else:
                from .broll_compositor import compose_overlay_multi
                ok = await compose_overlay_multi(
                    fade=editorial_fade_s,
                    main_path=video_path,
                    broll_pairs=broll_pairs,
                    output_path=output_path,
                )

            if ok:
                self.last_editorial_broll = broll_metadata
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
