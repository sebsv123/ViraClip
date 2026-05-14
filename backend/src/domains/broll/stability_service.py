"""
Stability AI Service - generates images using Stable Diffusion models.

Supported models:
- SDXL 1.0 - High-quality images (~$0.002/img)
- SD 3 - Latest Stable Diffusion 3 (~$0.003/img)
"""

import logging
from pathlib import Path
from typing import Optional
import aiofiles
import httpx
import os
from ...config import get_config

logger = logging.getLogger(__name__)


class StabilityService:
    """Service for generating images using Stability AI API."""
    
    def __init__(self):
        self.config = get_config()
        self.api_key = os.getenv("STABILITY_API_KEY")
        self.output_dir = Path(self.config.temp_dir) / "generated_assets"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_url = "https://api.stability.ai/v1"
        self.engine_id = "stable-diffusion-xl-1024-v1-0"  # SDXL 1.0
        
    async def is_available(self) -> bool:
        """Check if Stability AI service is available."""
        if not self.api_key:
            logger.warning("⚠️ STABILITY_API_KEY missing. Stability AI unavailable.")
            return False
        return True
    
    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "9:16",
        negative_prompt: str = "",
        **kwargs
    ) -> Optional[Path]:
        """
        Generate an image using Stability AI.
        
        Args:
            prompt: Text description
            aspect_ratio: "9:16", "16:9", or "1:1"
            negative_prompt: What to avoid in the image
            **kwargs: Additional parameters
            
        Returns:
            Path to generated image, or None if failed
        """
        if not await self.is_available():
            return None
        
        logger.info(f"[Stability AI] Generating: {prompt[:50]}...")
        
        try:
            # Get dimensions
            width, height = self._get_dimensions(aspect_ratio)
            
            # Call API
            image_data = await self._call_api(prompt, width, height, negative_prompt, **kwargs)
            
            if image_data:
                # Save image
                image_path = await self._save_image(image_data, prompt)
                if image_path:
                    logger.info(f"✅ [Stability AI] Generated: {image_path}")
                    return image_path
            
            return None
            
        except Exception as e:
            logger.error(f"❌ [Stability AI] Error: {e}")
            return None
    
    def _get_dimensions(self, aspect_ratio: str) -> tuple:
        """
        Map aspect ratio to SDXL-compatible dimensions.
        SDXL works best with dimensions that are multiples of 64.
        """
        dimensions_map = {
            "9:16": (896, 1152),   # Vertical
            "16:9": (1152, 896),   # Horizontal
            "1:1": (1024, 1024),   # Square
        }
        return dimensions_map.get(aspect_ratio, (896, 1152))
    
    async def _call_api(
        self,
        prompt: str,
        width: int,
        height: int,
        negative_prompt: str = "",
        steps: int = 30,
        cfg_scale: float = 7.0,
        **kwargs
    ) -> Optional[bytes]:
        """Call Stability AI API."""
        try:
            url = f"{self.base_url}/generation/{self.engine_id}/text-to-image"
            
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            
            payload = {
                "text_prompts": [
                    {
                        "text": prompt,
                        "weight": 1.0
                    }
                ],
                "width": width,
                "height": height,
                "steps": steps,
                "cfg_scale": cfg_scale,
                "samples": 1,
            }
            
            # Add negative prompt if provided
            if negative_prompt:
                payload["text_prompts"].append({
                    "text": negative_prompt,
                    "weight": -1.0
                })
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    artifacts = data.get("artifacts", [])
                    
                    if artifacts and len(artifacts) > 0:
                        # Get base64 encoded image
                        import base64
                        image_b64 = artifacts[0].get("base64")
                        if image_b64:
                            return base64.b64decode(image_b64)
                    
                    logger.error("❌ No image artifacts in response")
                    return None
                else:
                    logger.error(f"❌ Stability API error {response.status_code}: {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Stability API call failed: {e}")
            return None
    
    async def _save_image(self, image_data: bytes, prompt: str) -> Optional[Path]:
        """Save image data to file."""
        try:
            output_path = self.output_dir / f"stability_{hash(prompt) % 100000}.png"
            
            async with aiofiles.open(output_path, mode="wb") as f:
                await f.write(image_data)
            
            return output_path
            
        except Exception as e:
            logger.error(f"❌ Save image failed: {e}")
            return None
    
    def create_enhanced_prompt(self, base_prompt: str) -> str:
        """Enhance prompt for SDXL."""
        style = "masterpiece, best quality, highly detailed, 8k uhd, professional photography, cinematic lighting"
        return f"{base_prompt}, {style}"
    
    def get_default_negative_prompt(self) -> str:
        """Default negative prompt to avoid common issues."""
        return "low quality, blurry, distorted, watermark, text, logo, cropped, out of frame"


# Singleton instance
_stability_service: Optional[StabilityService] = None


def get_stability_service() -> StabilityService:
    """Get or create singleton Stability AI service instance."""
    global _stability_service
    if _stability_service is None:
        _stability_service = StabilityService()
    return _stability_service
