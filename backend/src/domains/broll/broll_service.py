"""
BRoll Service - AI-powered B-roll injection for viral video enhancement.

Pipeline:
  1. Keyword extraction   — Groq llama-3.1-8b-instant extracts 2-3 visual search terms
  2. Asset fetch          — Pexels API (portrait video); Pixabay API as fallback
  3. Silence detection    — librosa finds gaps > 1.5 s in segment audio
  4. FFmpeg overlay       — inserts B-roll with 0.3 s fade-in/out at silence timestamps
                           (or at t=5 s if no silences found)
"""
import asyncio
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import httpx

from ...config import Config, get_config
from ...comfyui_bridge import COMFYUI_ENABLED, ComfyUIBridge  # ComfyUIBridge reservado para LTXV intro
from .comfyui_integration import comfyui_integration
from .broll_compositor import compose_overlay, probe_duration
from .scene_broll_placer import get_insert_timestamps

logger = logging.getLogger(__name__)

# Configuraciones B-roll via environment variables para fácil tuning
_BROLL_DOWNLOAD_TIMEOUT = int(os.environ.get("BROLL_DOWNLOAD_TIMEOUT", "30"))   # seconds per file
_MIN_SILENCE_SEC = float(os.environ.get("BROLL_MIN_SILENCE_SEC", "1.5"))       # minimum silence gap
_BROLL_DURATION = float(os.environ.get("BROLL_DURATION", "4.5"))               # seconds of B-roll - más largo para presencia
_FADE_DURATION = float(os.environ.get("BROLL_FADE_DURATION", "0.6"))             # fade-in / fade-out length - suave
_CACHE_TTL_DAYS = int(os.environ.get("BROLL_CACHE_TTL_DAYS", "7"))               # cache stale days
_BROLL_MAX_OVERLAYS = int(os.environ.get("BROLL_MAX_OVERLAYS", "3"))             # max overlays per clip


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
            "You are a video editor choosing B-roll footage. "
            "Read this transcript and extract 2-3 SPECIFIC English search terms for stock video footage. "
            "Rules:\n"
            "- Keywords MUST directly match a noun/action/place MENTIONED in the transcript\n"
            "- NO generic motivational words (success, winner, achievement, determination)\n"
            "- Choose the most VISUAL and CONCRETE thing the speaker is talking about\n"
            "- Must be searchable on a stock video site (e.g. Pexels, Pixabay)\n"
            "- Reply with ONLY a JSON array, e.g. [\"stock market chart\", \"office meeting\", \"coffee cup\"]\n\n"
            f"Transcript: {text[:500]}"
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
            from ...domains.detection.yolo_detector import get_visual_context, filter_keywords_with_yolo
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
    # 2. ASSET FETCH (Pexels → Pixabay fallback)
    # ──────────────────────────────────────────────────────────────────────────

    def _is_cache_fresh(self, path: Path) -> bool:
        """Return True if *path* exists and was modified within _CACHE_TTL_DAYS."""
        import time as _time
        if not path.exists() or path.stat().st_size < 1_000:
            return False
        age_days = (_time.time() - path.stat().st_mtime) / 86400
        return age_days <= _CACHE_TTL_DAYS

    async def fetch_broll_asset(self, keyword: str, video_path: Optional[str] = None, task_id: Optional[str] = None) -> Optional[Path]:
        """Fetch the most relevant B-roll asset for *keyword*.

        Strategy: API-first for maximum relevance (unless BROLL_USE_LTX is enabled).
        0. If BROLL_USE_LTX="true", try LTX-Video generation first
        1. Query Pexels + Pixabay + Coverr in parallel (best result for this keyword)
        2. If all APIs fail → fall back to Pexels Photos (static image via API)
        3. If all APIs are unavailable (no keys / network error) → use local cache
        Cache is a safety net, not the primary source.
        """
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        cached_video = self.broll_dir / f"{safe}.mp4"
        cached_photo = self.broll_dir / f"{safe}.jpg"

        # ── 0. LTX-Video generation (if enabled) ─────────────────────────────
        # IMPORTANTE: aquí queremos un CLIP DE BROLL puro generado por LTX a
        # partir del keyword, no una concatenación con el video original.
        # Antes se pedía "broll_transition" que devolvía main+xfade+broll;
        # ahora se pide "broll_generate" (orchestrator.generate_broll_with_ltx)
        # y guardamos el resultado en el cache local por keyword.
        if os.getenv("BROLL_USE_LTX", "true").lower() == "true" and task_id:
            try:
                prompt = f"cinematic B-roll footage of {keyword}, professional quality, smooth motion, 9:16 vertical"
                logger.info(f"🎬 Generating B-roll with LTX-Video: '{keyword}'")
                _ltx_result = await comfyui_integration.process_with_comfyui(
                    task_id=f"{task_id}_broll_{safe}",
                    video_path=None,  # not used for pure generation
                    operation="broll_generate",
                    prompt=prompt,
                    duration=3.0,
                    width=608,   # 9:16-ish at LTX step=32 (608x1088)
                    height=1088,
                )
                if _ltx_result and Path(_ltx_result).exists():
                    # Promote into keyword-cache for future reuse
                    try:
                        shutil.copy2(_ltx_result, cached_video)
                    except Exception as _copy_e:
                        logger.debug(f"[BRoll] No pude cachear LTX en {cached_video}: {_copy_e}")
                    logger.info(f"[BRoll] ✓ LTX B-roll generated for '{keyword}': {_ltx_result}")
                    return Path(_ltx_result)
            except Exception as _ltx_e:
                logger.warning(f"⚠️ LTX B-roll failed, falling back to stock footage: {_ltx_e}")

        # ── 1. API-first: query all video sources in parallel ─────────────────
        pexels_task  = asyncio.create_task(self._search_pexels(keyword))
        pixabay_task = asyncio.create_task(self._search_pixabay(keyword))
        coverr_task  = asyncio.create_task(self._search_coverr(keyword))

        results = await asyncio.gather(pexels_task, pixabay_task, coverr_task,
                                       return_exceptions=True)
        video_urls = [r for r in results if isinstance(r, str) and r]

        for url in video_urls:
            result = await self._download(url, cached_video)
            if result:
                logger.info(f"[BRoll] API → downloaded video for '{keyword}': {result.name}")
                return result

        # ── 2. Fallback: Pexels Photos API (static image) ─────────────────────
        photo = await self._search_pexels_photos_and_download(keyword, safe)
        if photo:
            logger.info(f"[BRoll] API → downloaded photo for '{keyword}': {photo.name}")
            return photo

        # ── 3. Last resort: local cache (APIs down / no keys) ─────────────────
        if self._is_cache_fresh(cached_video):
            logger.info(f"[BRoll] Cache fallback (video): {cached_video}")
            return cached_video
        if self._is_cache_fresh(cached_photo):
            logger.info(f"[BRoll] Cache fallback (photo): {cached_photo}")
            return cached_photo

        logger.warning(f"[BRoll] No asset found for keyword '{keyword}' (APIs + cache exhausted)")
        return None

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
        # Check config first (allows session-level disable), then env
        key = self.config.coverr_api_key or os.getenv("COVERR_API_KEY", "")
        if not key:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://api.coverr.co/videos",
                    params={"keywords": query, "token": key, "per_page": 5},
                )
                if resp.status_code == 401:
                    logger.warning("[BRoll] Coverr API key invalid (401) — disabling Coverr for this session")
                    # Disable Coverr by clearing the key in this config instance
                    self.config.coverr_api_key = ""
                    return None
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
        2. Fetch the best matching stock video per keyword
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
                    from ...video_processing.object_detection import detect_objects_in_video
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

            # Step 2 — fetch one asset per keyword (up to max_overlays distinct clips)
            broll_assets: List[Path] = []
            _task_id = Path(video_path).stem if video_path else f"broll_{int(asyncio.get_event_loop().time())}"
            for kw in keywords[:max(3, max_overlays)]:
                asset = await self.fetch_broll_asset(kw, video_path=video_path, task_id=_task_id)
                if asset and asset not in broll_assets:
                    broll_assets.append(asset)

            # GPU T2V fallback if no stock assets found
            if not broll_assets:
                try:
                    from .t2v_broll_service import T2VBrollService
                    if T2VBrollService.is_available():
                        _t2v = T2VBrollService()
                        _t2v_prompt = ", ".join(keywords[:2]) if keywords else segment_text[:50]
                        _t2v_out = self.broll_dir / f"t2v_{'_'.join(keywords[:1])}.mp4"
                        _t2v_res = await _t2v.generate(
                            prompt=_t2v_prompt,
                            duration=_BROLL_DURATION,
                            output_path=str(_t2v_out),
                        )
                        if _t2v_res and _t2v_out.exists():
                            broll_assets.append(_t2v_out)
                            logger.info(
                                f"[BRoll] ✓ T2V ({_t2v_res.get('model', 'ltx')}) generated "
                                f"B-Roll for: {_t2v_prompt[:40]}"
                            )
                except Exception as _t2v_e:
                    logger.debug(f"[BRoll] T2V generation skipped: {_t2v_e}")

            # Último recurso: LTX-Video directo vía ComfyUIOrchestrator.
            # (ComfyUIBridge.generate_broll era un placeholder que retornaba
            # None; migrado a la operation "broll_generate" que sí invoca el
            # workflow LTX real.)
            if not broll_assets and COMFYUI_ENABLED:
                try:
                    _gen_prompt = ", ".join(keywords[:2]) if keywords else segment_text[:50]
                    _task_ns = f"brollgen_{'_'.join(keywords[:1]) or 'fallback'}"
                    _gen_result = await comfyui_integration.process_with_comfyui(
                        task_id=_task_ns,
                        video_path=None,
                        operation="broll_generate",
                        prompt=f"cinematic B-roll footage of {_gen_prompt}, smooth motion, 9:16 vertical",
                        duration=_BROLL_DURATION,
                        width=608,
                        height=1088,
                    )
                    if _gen_result and Path(_gen_result).exists():
                        _gen_out = self.broll_dir / f"gen_{'_'.join(keywords[:1]) or 'fallback'}.mp4"
                        try:
                            shutil.copy2(_gen_result, _gen_out)
                        except Exception:
                            _gen_out = Path(_gen_result)
                        broll_assets.append(_gen_out)
                        logger.info(f"[BRoll] ✓ LTX-Video fallback generated B-Roll for: {_gen_prompt[:40]}")
                except Exception as _gen_e:
                    logger.debug(f"[BRoll] LTX fallback skipped: {_gen_e}")

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
