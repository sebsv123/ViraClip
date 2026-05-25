"""
Overlay Content Source — Contextual Overlay System

Multi-source content fetcher for contextual overlays.
Priority order: Local cache → Unsplash → Pexels → Google Imagen 3 → Replicate → Stability → DALL-E → AI generation → Fallback
"""

import asyncio
import hashlib
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# ── Insurance keyword signals ────────────────────────────────────────────────
# Used to detect insurance-domain keywords and enforce tag filtering.
_INSURANCE_KEYWORD_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

_INSURANCE_TAG_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

def _is_insurance_keyword(keyword: str) -> bool:
    """Return True if the keyword contains insurance-domain concepts."""
    kw = keyword.lower()
    return any(sig in kw for sig in _INSURANCE_KEYWORD_SIGNALS)


# ── Insurance keyword signals ────────────────────────────────────────────────
# Used to detect insurance-domain keywords and enforce tag filtering.
_INSURANCE_KEYWORD_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

_INSURANCE_TAG_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

def _is_insurance_keyword(keyword: str) -> bool:
    """Return True if the keyword contains insurance-domain concepts."""
    kw = keyword.lower()
    return any(sig in kw for sig in _INSURANCE_KEYWORD_SIGNALS)


# ── Insurance keyword signals ────────────────────────────────────────────────
# Used to detect insurance-domain keywords and enforce tag filtering.
_INSURANCE_KEYWORD_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

_INSURANCE_TAG_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

def _is_insurance_keyword(keyword: str) -> bool:
    """Return True if the keyword contains insurance-domain concepts."""
    kw = keyword.lower()
    return any(sig in kw for sig in _INSURANCE_KEYWORD_SIGNALS)


# ── Insurance keyword signals ────────────────────────────────────────────────
# Used to detect insurance-domain keywords and enforce tag filtering.
_INSURANCE_KEYWORD_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

_INSURANCE_TAG_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

def _is_insurance_keyword(keyword: str) -> bool:
    """Return True if the keyword contains insurance-domain concepts."""
    kw = keyword.lower()
    return any(sig in kw for sig in _INSURANCE_KEYWORD_SIGNALS)


# ── Insurance keyword signals ────────────────────────────────────────────────
# Used to detect insurance-domain keywords and enforce tag filtering.
_INSURANCE_KEYWORD_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

_INSURANCE_TAG_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

def _is_insurance_keyword(keyword: str) -> bool:
    """Return True if the keyword contains insurance-domain concepts."""
    kw = keyword.lower()
    return any(sig in kw for sig in _INSURANCE_KEYWORD_SIGNALS)


# ── Insurance keyword signals ────────────────────────────────────────────────
# Used to detect insurance-domain keywords and enforce tag filtering.
_INSURANCE_KEYWORD_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

_INSURANCE_TAG_SIGNALS: frozenset = frozenset({
    "insurance", "policy", "claim", "coverage", "premium", "protection",
    "family", "savings", "advisor", "consultation", "document", "signing",
    "contract", "office", "medical", "health", "accident", "agent",
    "broker", "financial", "retirement", "planning",
})

def _is_insurance_keyword(keyword: str) -> bool:
    """Return True if the keyword contains insurance-domain concepts."""
    kw = keyword.lower()
    return any(sig in kw for sig in _INSURANCE_KEYWORD_SIGNALS)



@dataclass
class OverlayAsset:
    """Content asset for overlay rendering."""
    path: str
    source: str  # "local" | "unsplash" | "pexels" | "ai" | "fallback"
    keyword: str
    is_video: bool
    duration: float  # For videos, duration in seconds
    width: int
    height: int


class OverlayContentSource:
    """
    Fetches images/videos for contextual overlays from multiple sources.
    
    Priority:
    1. Local cache (instant, offline)
    2. Unsplash API (free, unlimited, high quality photos)
    3. Pexels API (free, photos + videos)
    4. AI generation (Stable Diffusion via ComfyUI - GPU required)
    5. Fallback (solid color or text overlay)
    """
    
    def __init__(self):
        self.cache_dir = Path(os.environ.get("OVERLAY_CACHE_DIR", "/app/storage/overlay_cache"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # API keys
        self.unsplash_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
        self.pexels_key = os.environ.get("PEXELS_API_KEY", "")
        
        # AI generation
        self.ai_enabled = os.environ.get("AI_OVERLAY_ENABLED", "false").lower() == "true"
        
        # HTTP client
        self.http_client = httpx.AsyncClient(timeout=30.0)
    
    async def get_content(
        self,
        keyword: str,
        category: str = "general",
        prefer_video: bool = False,
        duration: float = 3.0
    ) -> Optional[OverlayAsset]:
        """
        Get overlay content for a keyword.
        
        Multi-provider fallback chain:
        1. Local cache (instant, offline)
        2. Unsplash (free stock photos)
        3. Pexels (free stock photos + videos)
        4. Google Imagen 3 (AI, free 1000/month)
        5. Replicate Flux.1 (AI, $0.003/img)
        6. Stability SDXL (AI, $0.002/img)
        7. DALL-E 3 (AI, $0.04/img)
        8. ComfyUI local (if GPU available)
        9. Fallback gradient
        
        Args:
            keyword: Search keyword
            category: Category hint (nature, money, tech, etc.)
            prefer_video: Prefer video over image if available
            duration: Desired duration for video clips
            
        Returns:
            OverlayAsset or None if nothing found
        """
        # 1. Check local cache
        cached = await self._check_cache(keyword)
        if cached:
            return cached
        
        # 2. Try Unsplash (photos only) — skip for insurance keywords (no tag filtering available)
        if self.unsplash_key and not prefer_video and not _is_insurance_keyword(keyword):
            unsplash_asset = await self._fetch_unsplash(keyword, category)
            if unsplash_asset:
                return unsplash_asset
        
        # 3. Try Pexels (photos + videos)
        if self.pexels_key:
            pexels_asset = await self._fetch_pexels(keyword, category, prefer_video)
            if pexels_asset:
                return pexels_asset
        
        # Only proceed to AI generation for images (not videos)
        if not prefer_video:
            # 4. Try Google Imagen 3 (high priority - uses existing GOOGLE_API_KEY)
            google_asset = await self._generate_google_imagen(keyword, category)
            if google_asset:
                return google_asset
            
            # 5. Try Replicate Flux.1 (high quality, reasonable cost)
            replicate_asset = await self._generate_replicate(keyword, category)
            if replicate_asset:
                return replicate_asset
            
            # 6. Try Stability SDXL (good balance of cost/quality)
            stability_asset = await self._generate_stability(keyword, category)
            if stability_asset:
                return stability_asset
            
            # 7. Try DALL-E 3 (most expensive, highest quality)
            dalle_asset = await self._generate_dalle(keyword, category)
            if dalle_asset:
                return dalle_asset
        
        # 8. Try ComfyUI local AI generation (if enabled and GPU available)
        if self.ai_enabled:
            ai_asset = await self._generate_ai(keyword, category)
            if ai_asset:
                return ai_asset
        
        # 9. Fallback to local placeholder
        return await self._create_fallback(keyword)
    
    async def _check_cache(self, keyword: str) -> Optional[OverlayAsset]:
        """Check if keyword content exists in cache."""
        cache_key = self._cache_key(keyword)
        
        # Check for image
        for ext in [".jpg", ".png", ".webp"]:
            cache_path = self.cache_dir / f"{cache_key}{ext}"
            if cache_path.exists():
                logger.debug(f"Cache HIT for keyword '{keyword}': {cache_path}")
                return OverlayAsset(
                    path=str(cache_path),
                    source="local",
                    keyword=keyword,
                    is_video=False,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        
        # Check for video
        for ext in [".mp4", ".webm"]:
            cache_path = self.cache_dir / f"{cache_key}{ext}"
            if cache_path.exists():
                logger.debug(f"Cache HIT (video) for keyword '{keyword}': {cache_path}")
                return OverlayAsset(
                    path=str(cache_path),
                    source="local",
                    keyword=keyword,
                    is_video=True,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        
        return None
    
    async def _fetch_unsplash(self, keyword: str, category: str) -> Optional[OverlayAsset]:
        """Fetch image from Unsplash API."""
        try:
            url = "https://api.unsplash.com/photos/random"
            params = {
                "query": keyword,
                "orientation": "portrait",  # 9:16 aspect ratio
                "client_id": self.unsplash_key
            }
            
            response = await self.http_client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                image_url = data.get("urls", {}).get("regular")
                
                if image_url:
                    # Download image
                    downloaded = await self._download_file(image_url, keyword, "unsplash")
                    if downloaded:
                        logger.info(f"Unsplash: Downloaded image for '{keyword}'")
                        return downloaded
            else:
                logger.debug(f"Unsplash API error: {response.status_code}")
        
        except Exception as e:
            logger.debug(f"Unsplash fetch failed for '{keyword}': {e}")
        
        return None
    
    async def _fetch_pexels(
        self,
        keyword: str,
        category: str,
        prefer_video: bool = False
    ) -> Optional[OverlayAsset]:
        """Fetch image or video from Pexels API."""
        try:
            # Try video first if preferred
            if prefer_video:
                url = "https://api.pexels.com/videos/search"
                params = {
                    "query": keyword,
                    "orientation": "portrait",
                    "per_page": 1
                }
            else:
                url = "https://api.pexels.com/v1/search"
                params = {
                    "query": keyword,
                    "orientation": "portrait",
                    "per_page": 1
                }
            
            headers = {"Authorization": self.pexels_key}
            response = await self.http_client.get(url, params=params, headers=headers)
            
            if response.status_code == 200:
                data = response.json()
                
                if prefer_video and data.get("videos"):
                    video = data["videos"][0]
                    video_files = video.get("video_files", [])
                    # Get portrait HD version
                    video_url = None
                    for vf in video_files:
                        if vf.get("width", 0) <= 1080 and vf.get("height", 0) >= 1920:
                            video_url = vf.get("link")
                            break
                    
                    if not video_url and video_files:
                        video_url = video_files[0].get("link")
                    
                    if video_url:
                        downloaded = await self._download_file(video_url, keyword, "pexels", is_video=True)
                        if downloaded:
                            logger.info(f"Pexels: Downloaded video for '{keyword}'")
                            return downloaded
                
                elif data.get("photos"):
                    photo = data["photos"][0]
                    image_url = photo.get("src", {}).get("large2x")
                    
                    if image_url:
                        # ── Insurance tag gate ──────────────────────────────────────────
                        # If keyword is insurance-domain, require at least 1 insurance
                        # tag hit in the photo metadata before downloading.
                        if _is_insurance_keyword(keyword):
                            _alt = (photo.get("alt") or "").lower()
                            _photographer = (photo.get("photographer") or "").lower()
                            _tag_hit = any(
                                sig in _alt or sig in _photographer
                                for sig in _INSURANCE_TAG_SIGNALS
                            )
                            if not _tag_hit:
                                logger.warning(
                                    "[OverlaySource] PEXELS INSURANCE REJECT keyword='%s' — "
                                    "insurance keyword but zero insurance tag hits in photo alt='%s'. "
                                    "Rejecting to prevent generic portrait leak.",
                                    keyword, _alt,
                                )
                                return None
                        downloaded = await self._download_file(image_url, keyword, "pexels")
                        if downloaded:
                            logger.info(f"Pexels: Downloaded image for '{keyword}'")
                            return downloaded
            else:
                logger.debug(f"Pexels API error: {response.status_code}")
        
        except Exception as e:
            logger.debug(f"Pexels fetch failed for '{keyword}': {e}")
        
        return None
    
    async def _generate_google_imagen(self, keyword: str, category: str) -> Optional[OverlayAsset]:
        """Generate image using Google Imagen 3."""
        try:
            from .google_imagen_service import get_imagen_service
            
            service = get_imagen_service()
            if not await service.is_available():
                logger.debug("Google Imagen not available")
                return None
            
            # Enhance prompt with context
            prompt = service.create_enhanced_prompt(keyword, context=f"{category} theme")
            
            # Generate image
            image_path = await service.generate_image(prompt, aspect_ratio="9:16")
            
            if image_path and Path(image_path).exists():
                logger.info(f"Google Imagen: Generated image for '{keyword}'")
                return OverlayAsset(
                    path=str(image_path),
                    source="google_imagen",
                    keyword=keyword,
                    is_video=False,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        except Exception as e:
            logger.debug(f"Google Imagen generation failed for '{keyword}': {e}")
        
        return None
    
    async def _generate_replicate(self, keyword: str, category: str) -> Optional[OverlayAsset]:
        """Generate image using Replicate Flux.1."""
        try:
            from .replicate_service import get_replicate_service
            
            service = get_replicate_service()
            if not await service.is_available():
                logger.debug("Replicate not available")
                return None
            
            # Enhance prompt
            prompt = service.create_enhanced_prompt(f"{keyword}, {category} themed")
            
            # Generate image
            image_path = await service.generate_image(prompt, aspect_ratio="9:16")
            
            if image_path and Path(image_path).exists():
                logger.info(f"Replicate: Generated image for '{keyword}'")
                return OverlayAsset(
                    path=str(image_path),
                    source="replicate",
                    keyword=keyword,
                    is_video=False,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        except Exception as e:
            logger.debug(f"Replicate generation failed for '{keyword}': {e}")
        
        return None
    
    async def _generate_stability(self, keyword: str, category: str) -> Optional[OverlayAsset]:
        """Generate image using Stability AI SDXL."""
        try:
            from .stability_service import get_stability_service
            
            service = get_stability_service()
            if not await service.is_available():
                logger.debug("Stability AI not available")
                return None
            
            # Enhance prompt
            prompt = service.create_enhanced_prompt(f"{keyword}, {category}")
            negative_prompt = service.get_default_negative_prompt()
            
            # Generate image
            image_path = await service.generate_image(
                prompt,
                aspect_ratio="9:16",
                negative_prompt=negative_prompt
            )
            
            if image_path and Path(image_path).exists():
                logger.info(f"Stability AI: Generated image for '{keyword}'")
                return OverlayAsset(
                    path=str(image_path),
                    source="stability",
                    keyword=keyword,
                    is_video=False,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        except Exception as e:
            logger.debug(f"Stability AI generation failed for '{keyword}': {e}")
        
        return None
    
    async def _generate_dalle(self, keyword: str, category: str) -> Optional[OverlayAsset]:
        """Generate image using DALL-E 3 (via existing image_gen_service)."""
        try:
            from .image_gen_service import ImageGenService
            
            service = ImageGenService(provider="dalle")
            
            # Create prompt
            prompt = f"Professional photograph of {keyword}, {category} themed, cinematic lighting, 8k"
            
            # Generate image
            image_path = await service.generate_image(prompt, aspect_ratio="9:16")
            
            if image_path and Path(image_path).exists():
                logger.info(f"DALL-E 3: Generated image for '{keyword}'")
                return OverlayAsset(
                    path=str(image_path),
                    source="dalle",
                    keyword=keyword,
                    is_video=False,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        except Exception as e:
            logger.debug(f"DALL-E 3 generation failed for '{keyword}': {e}")
        
        return None
    
    async def _generate_ai(self, keyword: str, category: str) -> Optional[OverlayAsset]:
        """Generate image using AI (Stable Diffusion via ComfyUI)."""
        try:
            # Check if ComfyUI is available
            from .comfyui_bridge import is_available, generate_broll
            
            if not await is_available():
                logger.debug("ComfyUI not available for AI generation")
                return None
            
            # Generate prompt
            prompt = f"high quality photograph of {keyword}, professional, cinematic, 9:16 aspect ratio"
            
            # Generate via ComfyUI
            result = await generate_broll(prompt, duration=3.0)
            
            if result and Path(result).exists():
                logger.info(f"AI: Generated image for '{keyword}'")
                return OverlayAsset(
                    path=result,
                    source="ai",
                    keyword=keyword,
                    is_video=False,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        
        except Exception as e:
            logger.debug(f"AI generation failed for '{keyword}': {e}")
        
        return None
    
    async def _download_file(
        self,
        url: str,
        keyword: str,
        source: str,
        is_video: bool = False
    ) -> Optional[OverlayAsset]:
        """Download file from URL and cache it."""
        try:
            response = await self.http_client.get(url)
            
            if response.status_code == 200:
                # Determine file extension
                ext = ".mp4" if is_video else ".jpg"
                cache_key = self._cache_key(keyword)
                cache_path = self.cache_dir / f"{cache_key}{ext}"
                
                # Save to cache
                cache_path.write_bytes(response.content)
                
                return OverlayAsset(
                    path=str(cache_path),
                    source=source,
                    keyword=keyword,
                    is_video=is_video,
                    duration=3.0,
                    width=1080,
                    height=1920
                )
        
        except Exception as e:
            logger.debug(f"Download failed from {url}: {e}")
        
        return None
    
    async def _create_fallback(self, keyword: str) -> OverlayAsset:
        """Create an enhanced gradient-based fallback overlay with emoji support."""
        fallback_path = self.cache_dir / f"fallback_{self._cache_key(keyword)}.jpg"
        
        if not fallback_path.exists():
            try:
                # Get category-based colors for gradient
                colors = self._get_category_colors(keyword)
                gradient = f"gradients=x=0:y=0:colors={colors['top']}|{colors['bottom']}:size=1080x1920:speed=0"
                
                # Add emoji if available
                emoji = self._get_keyword_emoji(keyword)
                text_display = f"{emoji} {keyword}" if emoji else keyword
                
                # Create gradient with centered text and shadow
                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-f", "lavfi",
                    "-i", gradient,
                    "-vf", f"drawtext=text='{text_display}':fontsize=100:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:shadowcolor=black:shadowx=2:shadowy=2",
                    "-frames:v", "1",
                    "-y",
                    str(fallback_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await proc.wait()
                logger.info(f"Fallback overlay created for '{keyword}' (offline mode)")
            except Exception as e:
                logger.debug(f"Fallback creation failed, using simple color: {e}")
                # Simpler fallback if gradient fails
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg", "-f", "lavfi",
                        "-i", f"color=c=0x1a1a2e:s=1080x1920:d=1",
                        "-vf", f"drawtext=text='{keyword}':fontsize=80:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
                        "-frames:v", "1",
                        "-y",
                        str(fallback_path),
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL
                    )
                    await proc.wait()
                except:
                    # Last resort: create minimal file
                    fallback_path.touch()
        
        return OverlayAsset(
            path=str(fallback_path),
            source="fallback",
            keyword=keyword,
            is_video=False,
            duration=3.0,
            width=1080,
            height=1920
        )
    
    def _get_category_colors(self, keyword: str) -> dict:
        """Get gradient colors based on keyword category."""
        keyword_lower = keyword.lower()
        
        # Category-based color schemes (hex colors)
        if any(word in keyword_lower for word in ['money', 'cash', 'dollar', 'wealth', 'rich']):
            return {'top': '0x2d6a4f', 'bottom': '0x1b4332'}  # Green (money)
        elif any(word in keyword_lower for word in ['fire', 'hot', 'energy', 'power']):
            return {'top': '0xdc2f02', 'bottom': '0x9d0208'}  # Red/Orange
        elif any(word in keyword_lower for word in ['water', 'ocean', 'sea', 'blue', 'sky']):
            return {'top': '0x0077b6', 'bottom': '0x023e8a'}  # Blue
        elif any(word in keyword_lower for word in ['tech', 'digital', 'cyber', 'computer']):
            return {'top': '0x7209b7', 'bottom': '0x3c096c'}  # Purple (tech)
        elif any(word in keyword_lower for word in ['gold', 'luxury', 'premium']):
            return {'top': '0xf77f00', 'bottom': '0xd62828'}  # Gold/Orange
        elif any(word in keyword_lower for word in ['nature', 'green', 'plant', 'forest']):
            return {'top': '0x52b788', 'bottom': '0x2d6a4f'}  # Green
        elif any(word in keyword_lower for word in ['dark', 'night', 'black', 'shadow']):
            return {'top': '0x495057', 'bottom': '0x212529'}  # Dark
        else:
            # Default: Modern purple/blue gradient
            return {'top': '0x667eea', 'bottom': '0x764ba2'}
    
    def _get_keyword_emoji(self, keyword: str) -> str:
        """Get relevant emoji for keyword (if available)."""
        keyword_lower = keyword.lower()
        
        emoji_map = {
            'money': '💰', 'cash': '💵', 'dollar': '💲', 'wealth': '💎',
            'fire': '🔥', 'hot': '🔥', 'energy': '⚡', 'power': '💪',
            'water': '💧', 'ocean': '🌊', 'sea': '🌊',
            'tech': '💻', 'computer': '💻', 'phone': '📱',
            'heart': '❤️', 'love': '💕',
            'star': '⭐', 'win': '🏆', 'success': '🎯',
            'rocket': '🚀', 'growth': '📈', 'chart': '📊',
            'brain': '🧠', 'idea': '💡', 'think': '🤔',
            'time': '⏰', 'clock': '🕐', 'watch': '⌚',
            'food': '🍔', 'pizza': '🍕', 'coffee': '☕',
            'car': '🚗', 'house': '🏠', 'building': '🏢',
            'music': '🎵', 'camera': '📷', 'video': '🎬',
        }
        
        for key, emoji in emoji_map.items():
            if key in keyword_lower:
                return emoji
        
        return ''  # No emoji
    
    def _cache_key(self, keyword: str) -> str:
        """Generate cache key from keyword."""
        return hashlib.md5(keyword.lower().encode()).hexdigest()[:16]
    
    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()


# Singleton
_source_instance: Optional[OverlayContentSource] = None


def get_overlay_content_source() -> OverlayContentSource:
    """Get or create singleton source instance."""
    global _source_instance
    if _source_instance is None:
        _source_instance = OverlayContentSource()
    return _source_instance
