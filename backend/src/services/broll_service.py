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
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import httpx

from ..config import Config, get_config
from ..comfyui_bridge import ComfyUIBridge, COMFYUI_ENABLED

logger = logging.getLogger(__name__)

_BROLL_DOWNLOAD_TIMEOUT = 30   # seconds per file
_MIN_SILENCE_SEC = 1.5         # minimum silence gap to qualify for B-roll insert
_BROLL_DURATION = 3.0          # seconds of B-roll to overlay
_FADE_DURATION = 0.3           # fade-in / fade-out length


class BrollService:
    """AI-powered B-roll injection service."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.broll_dir = Path(self.config.temp_dir) / "uploads/broll"
        self.broll_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. KEYWORD EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────

    async def extract_keywords(self, text: str) -> List[str]:
        """Use Groq llama-3.1-8b-instant to pull 2-3 visual search keywords."""
        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            logger.warning("[BRoll] GROQ_API_KEY not set — falling back to first 3 nouns")
            return self._simple_keyword_fallback(text)

        prompt = (
            "Extract 2-3 short, highly visual search keywords from the following transcript "
            "that would make great stock video b-roll. Reply with ONLY a JSON array of strings, "
            "e.g. [\"mountain\", \"snow\", \"landscape\"]. No explanation.\n\n"
            f"Transcript: {text[:400]}"
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
                    return result
        except Exception as e:
            logger.warning(f"[BRoll] Keyword extraction failed: {e}")
        return self._simple_keyword_fallback(text)

    @staticmethod
    def _simple_keyword_fallback(text: str) -> List[str]:
        """Return first 3 non-stopword words as a basic fallback."""
        stopwords = {"the", "a", "an", "is", "are", "was", "were", "i", "you",
                     "he", "she", "it", "we", "they", "and", "or", "but", "in",
                     "on", "at", "to", "of", "for", "with", "this", "that"}
        words = [w.strip(".,!?\"'") for w in text.split() if w.isalpha()]
        result = [w.lower() for w in words if w.lower() not in stopwords][:3]
        return result or ["nature", "landscape"]

    # ──────────────────────────────────────────────────────────────────────────
    # 2. ASSET FETCH (Pexels → Pixabay fallback)
    # ──────────────────────────────────────────────────────────────────────────

    async def fetch_broll_asset(self, keyword: str) -> Optional[Path]:
        """Fetch and cache a portrait video/photo for *keyword*. Returns local Path or None."""
        safe = "".join(c if c.isalnum() else "_" for c in keyword).lower()
        cached_video = self.broll_dir / f"{safe}.mp4"
        if cached_video.exists() and cached_video.stat().st_size > 10_000:
            logger.info(f"[BRoll] Cache hit (video): {cached_video}")
            return cached_video
        cached_photo = self.broll_dir / f"{safe}.jpg"
        if cached_photo.exists() and cached_photo.stat().st_size > 5_000:
            logger.info(f"[BRoll] Cache hit (photo): {cached_photo}")
            return cached_photo

        # Try Pexels video first
        video_url = await self._search_pexels(keyword)
        if not video_url:
            video_url = await self._search_pixabay(keyword)
        if video_url:
            result = await self._download(video_url, cached_video)
            if result:
                return result

        # Fallback: Pexels Photos API (still image)
        photo = await self._search_pexels_photos_and_download(keyword, safe)
        if photo:
            return photo

        logger.warning(f"[BRoll] No asset found for keyword '{keyword}'")
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
        Uses ffmpeg overlay filter with fade-in/out of *fade* seconds.
        Returns True on success.
        """
        end_ts = timestamp + overlay_duration
        fade_out_start = overlay_duration - fade

        filter_complex = (
            f"[1:v]"
            f"scale=iw:ih,"
            f"fade=t=in:st=0:d={fade}:alpha=1,"
            f"fade=t=out:st={fade_out_start}:d={fade}:alpha=1"
            f"[bv];"
            f"[0:v][bv]overlay=x=0:y=0:"
            f"enable='between(t,{timestamp},{end_ts})'[vout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", "0", "-t", str(overlay_duration + 1), "-i", broll_path,
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "0:a",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _out, _err = await proc.communicate()
            if proc.returncode == 0:
                logger.info(f"[BRoll] ✓ Overlay inserted at t={timestamp:.1f}s → {output_path}")
                return True
            else:
                logger.error(f"[BRoll] FFmpeg overlay failed (rc={proc.returncode}): {_err.decode()[:400]}")
                return False
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
    ) -> str:
        """
        Full B-roll pipeline for a single clip.

        1. Extract keywords from *segment_text*
        2. Fetch the best matching stock video
        3. Detect silences (if *audio_path* provided)
        4. Insert B-roll overlay

        Returns *output_path* on success, *video_path* (original) on failure.
        """
        try:
            # Step 1 — keywords (LLM extraction + optional YOLO visual augmentation)
            keywords = await self.extract_keywords(segment_text)

            # YOLO augmentation: detect objects actually visible in the clip
            try:
                from ..video_processing.object_detection import detect_objects_in_video
                yolo_kws = await detect_objects_in_video(video_path, max_frames=4)
                if yolo_kws:
                    # Prepend YOLO keywords so visually grounded terms are tried first
                    for kw in reversed(yolo_kws[:2]):
                        if kw not in keywords:
                            keywords.insert(0, kw)
                    logger.info(f"[BRoll] YOLO augmented keywords: {keywords}")
            except Exception as _yolo_e:
                logger.debug(f"[BRoll] YOLO augmentation skipped: {_yolo_e}")

            if not keywords:
                return video_path

            # Step 2 — fetch asset (try keywords in order until one succeeds)
            broll_asset: Optional[Path] = None
            for kw in keywords:
                broll_asset = await self.fetch_broll_asset(kw)
                if broll_asset:
                    break

            if not broll_asset:
                # Primary GPU path: LTX-Video / AnimateLCM T2V (Phase 3.1)
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
                            broll_asset = _t2v_out
                            logger.info(
                                f"[BRoll] ✓ T2V ({_t2v_res.get('model', 'ltx')}) generated "
                                f"B-Roll for: {_t2v_prompt[:40]}"
                            )
                except Exception as _t2v_e:
                    logger.debug(f"[BRoll] T2V generation skipped: {_t2v_e}")

            if not broll_asset and COMFYUI_ENABLED:
                # Secondary GPU path: ComfyUI AnimateDiff fallback
                try:
                    _cfy = ComfyUIBridge()
                    _gen_prompt = ", ".join(keywords[:2]) if keywords else segment_text[:50]
                    _gen_out = self.broll_dir / f"gen_{'_'.join(keywords[:1])}.mp4"
                    _gen_result = await _cfy.generate_broll(
                        prompt=_gen_prompt,
                        output_path=_gen_out,
                        duration=_BROLL_DURATION,
                    )
                    await _cfy.close()
                    if _gen_result and _gen_out.exists():
                        broll_asset = _gen_out
                        logger.info(f"[BRoll] ✓ AnimateDiff generated B-Roll for: {_gen_prompt[:40]}")
                except Exception as _gen_e:
                    logger.debug(f"[BRoll] AnimateDiff fallback skipped: {_gen_e}")

            if not broll_asset:
                logger.info(f"[BRoll] No asset fetched for keywords {keywords} — skipping")
                return video_path

            # Step 3 — silence detection
            insert_ts = 5.0  # default: insert at 5 s
            if audio_path and Path(audio_path).exists():
                silences = self.detect_silences(audio_path)
                if silences:
                    # Pick the first silence that starts after 2 s (avoid immediate intro)
                    for s_start, s_end in silences:
                        if s_start >= 2.0:
                            insert_ts = s_start + 0.1
                            break

            # Step 4 — overlay
            overlay_dur = min(_BROLL_DURATION, max(1.0, clip_duration - insert_ts - 0.5))
            ok = await self.insert_broll(
                video_path=video_path,
                output_path=output_path,
                broll_path=str(broll_asset),
                timestamp=insert_ts,
                overlay_duration=overlay_dur,
            )
            return output_path if ok else video_path

        except Exception as e:
            logger.error(f"[BRoll] process_clip failed: {e}", exc_info=True)
            return video_path
