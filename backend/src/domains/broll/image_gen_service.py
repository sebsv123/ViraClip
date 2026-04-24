"""
Image Generation Service - creates semantic B-roll assets using multiple AI art models.

Supports:
- DALL-E 3 (OpenAI)
- Google Imagen 3
- Replicate (Flux.1, SDXL)
- Stability AI (SDXL)
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
import aiofiles
import requests
import httpx
import os
from ...config import Config

logger = logging.getLogger(__name__)

class ImageGenService:
    """Service for generating context-aware B-roll images with multi-provider support."""
    
    def __init__(self, provider: str = "auto"):
        """
        Initialize image generation service.
        
        Args:
            provider: Provider to use (auto, dalle, google_imagen, replicate, stability, sdxl)
                     "auto" = try all available providers in order
        """
        self.config = Config()
        self.provider = provider
        self.output_dir = Path(self.config.temp_dir) / "generated_assets"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Define provider priority order (from config or default)
        self.provider_order = self._get_provider_order()

    def _get_provider_order(self) -> List[str]:
        """Get provider order from config or use default."""
        # Read from env var or use default order
        order_str = os.getenv("IMAGE_GEN_PROVIDERS", "google_imagen,replicate,stability,dalle")
        return [p.strip() for p in order_str.split(",")]

    async def generate_image(self, prompt: str, aspect_ratio: str = "9:16") -> Optional[Path]:
        """
        Generates an image based on a prompt and returns the local Path.
        
        If provider="auto", tries all available providers in order until success.
        """
        logger.info(f"Generating image with provider '{self.provider}' for prompt: {str(prompt)[:50]}...")
        
        if self.provider == "auto":
            return await self._generate_auto(prompt, aspect_ratio)
        elif self.provider == "dalle":
            return await self._generate_dalle(prompt, aspect_ratio)
        elif self.provider == "google_imagen":
            return await self._generate_google_imagen(prompt, aspect_ratio)
        elif self.provider == "replicate":
            return await self._generate_replicate(prompt, aspect_ratio)
        elif self.provider == "stability":
            return await self._generate_stability(prompt, aspect_ratio)
        elif self.provider == "sdxl":
            return await self._generate_sdxl_local(prompt, aspect_ratio)
        else:
            logger.error(f"Unsupported image provider: {self.provider}")
            return None
    
    async def _generate_auto(self, prompt: str, aspect_ratio: str) -> Optional[Path]:
        """Try all available providers in order until one succeeds."""
        for provider in self.provider_order:
            logger.info(f"[Auto] Trying provider: {provider}")
            
            try:
                if provider == "google_imagen":
                    result = await self._generate_google_imagen(prompt, aspect_ratio)
                elif provider == "replicate":
                    result = await self._generate_replicate(prompt, aspect_ratio)
                elif provider == "stability":
                    result = await self._generate_stability(prompt, aspect_ratio)
                elif provider == "dalle":
                    result = await self._generate_dalle(prompt, aspect_ratio)
                else:
                    continue
                
                if result:
                    logger.info(f"✅ [Auto] Success with provider: {provider}")
                    return result
            except Exception as e:
                logger.warning(f"⚠️ [Auto] Provider {provider} failed: {e}")
                continue
        
        logger.error("❌ [Auto] All providers failed")
        return None
    
    async def _generate_google_imagen(self, prompt: str, aspect_ratio: str) -> Optional[Path]:
        """Generate using Google Imagen 3."""
        try:
            from .google_imagen_service import get_imagen_service
            service = get_imagen_service()
            return await service.generate_image(prompt, aspect_ratio)
        except Exception as e:
            logger.error(f"❌ Google Imagen generation failed: {e}")
            return None
    
    async def _generate_replicate(self, prompt: str, aspect_ratio: str) -> Optional[Path]:
        """Generate using Replicate."""
        try:
            from .replicate_service import get_replicate_service
            service = get_replicate_service()
            return await service.generate_image(prompt, aspect_ratio)
        except Exception as e:
            logger.error(f"❌ Replicate generation failed: {e}")
            return None
    
    async def _generate_stability(self, prompt: str, aspect_ratio: str) -> Optional[Path]:
        """Generate using Stability AI."""
        try:
            from .stability_service import get_stability_service
            service = get_stability_service()
            return await service.generate_image(prompt, aspect_ratio)
        except Exception as e:
            logger.error(f"❌ Stability generation failed: {e}")
            return None

    async def _generate_dalle(self, prompt: str, aspect_ratio: str) -> Optional[Path]:
        """Generate using OpenAI's DALL-E 3."""
        api_key = self.config.openai_api_key
        if not api_key:
            logger.warning("⚠️ OpenAI API Key missing. Skipping DALL-E generation.")
            return None
            
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=api_key)
            
            # Format aspect ratio for DALL-E
            size = "1024x1792" if aspect_ratio == "9:16" else "1024x1024"
            
            response = await client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="hd",
                n=1,
            )
            
            image_url = response.data[0].url
            if not image_url:
                return None
                
            # Download and save
            output_path = self.output_dir / f"ai_broll_{hash(prompt) % 10000}.png"
            async with httpx.AsyncClient() as http_client:
                img_resp = await http_client.get(image_url)
                if img_resp.status_code == 200:
                    async with aiofiles.open(output_path, mode="wb") as f:
                        await f.write(img_resp.content)
                    return output_path
                    
            return None
        except Exception as e:
            logger.error(f"❌ DALL-E generation failed: {e}")
            return None

    async def _generate_sdxl_local(self, prompt: str, aspect_ratio: str) -> Optional[Path]:
        """Placeholder for local SDXL Turbo integration via diffusers/torch."""
        logger.warning("Local SDXL service requires 'diffusers' package. Staging integration.")
        return None

    def create_ken_burns_prompt(self, video_context: str, transcript_segment: str) -> str:
        """
        Combines video context and segment text to create a high-quality visual prompt.
        Inspired by Meta AI aesthetics (detailed, cinematic, vibrant).
        """
        base_style = "Cinematic, high-fidelity, vibrant colors, professional lighting, 8k resolution, photorealistic."
        return f"{transcript_segment}. {video_context}. Style: {base_style}"
