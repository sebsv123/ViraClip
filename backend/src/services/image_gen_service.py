"""
Image Generation Service - creates semantic B-roll assets using AI art models.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any
import aiofiles
import requests
import httpx
from ..config import Config

logger = logging.getLogger(__name__)

class ImageGenService:
    """Service for generating context-aware B-roll images."""
    
    def __init__(self, provider: str = "dalle"):
        self.config = Config()
        self.provider = provider
        self.output_dir = Path(self.config.temp_dir) / "generated_assets"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    async def generate_image(self, prompt: str, aspect_ratio: str = "9:16") -> Optional[Path]:
        """
        Generates an image based on a prompt and returns the local Path.
        """
        logger.info(f"Generating image with provider {self.provider} for prompt: {str(prompt)[:50]}...")
        
        if self.provider == "dalle":
            return await self._generate_dalle(prompt, aspect_ratio)
        elif self.provider == "sdxl":
            return await self._generate_sdxl_local(prompt, aspect_ratio)
        else:
            logger.error(f"Unsupported image provider: {self.provider}")
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
