"""
Replicate Service - generates images and videos using various AI models.

Supported models:
- Flux.1 (Schnell) - Fast, high-quality images (~$0.003/img)
- Flux.1 (Dev) - Higher quality (~$0.005/img)
- SDXL - Stable Diffusion XL (~$0.002/img)
- AnimateDiff - Video generation (~$0.02/video)
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any
import aiofiles
import httpx
import os
from ...config import Config

logger = logging.getLogger(__name__)


class ReplicateService:
    """Service for generating images/videos using Replicate API."""
    
    # Model identifiers
    FLUX_SCHNELL = "black-forest-labs/flux-schnell"
    FLUX_DEV = "black-forest-labs/flux-dev"
    SDXL = "stability-ai/sdxl"
    
    def __init__(self):
        self.config = Config()
        self.api_token = os.getenv("REPLICATE_API_TOKEN")
        self.output_dir = Path(self.config.temp_dir) / "generated_assets"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_url = "https://api.replicate.com/v1"
        self.default_model = self.FLUX_SCHNELL  # Fast and cheap
        
    async def is_available(self) -> bool:
        """Check if Replicate service is available."""
        if not self.api_token:
            logger.warning("⚠️ REPLICATE_API_TOKEN missing. Replicate unavailable.")
            return False
        return True
    
    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "9:16",
        model: str = None,
        **kwargs
    ) -> Optional[Path]:
        """
        Generate an image using Replicate.
        
        Args:
            prompt: Text description
            aspect_ratio: "9:16", "16:9", or "1:1"
            model: Model to use (defaults to Flux Schnell)
            **kwargs: Additional model-specific parameters
            
        Returns:
            Path to generated image, or None if failed
        """
        if not await self.is_available():
            return None
        
        model = model or self.default_model
        logger.info(f"[Replicate] Generating with {model}: {prompt[:50]}...")
        
        try:
            # Get dimensions
            width, height = self._get_dimensions(aspect_ratio)
            
            # Prepare input
            input_data = {
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_outputs": 1,
                **kwargs
            }
            
            # Create prediction
            prediction = await self._create_prediction(model, input_data)
            
            if not prediction:
                return None
            
            # Wait for completion and download
            image_url = await self._wait_for_prediction(prediction["id"])
            
            if image_url:
                image_path = await self._download_image(image_url, prompt)
                if image_path:
                    logger.info(f"✅ [Replicate] Generated: {image_path}")
                    return image_path
            
            return None
            
        except Exception as e:
            logger.error(f"❌ [Replicate] Error: {e}")
            return None
    
    def _get_dimensions(self, aspect_ratio: str) -> tuple:
        """Map aspect ratio to dimensions."""
        dimensions_map = {
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
            "1:1": (1024, 1024),
        }
        return dimensions_map.get(aspect_ratio, (1080, 1920))
    
    async def _create_prediction(
        self,
        model: str,
        input_data: Dict[str, Any]
    ) -> Optional[Dict]:
        """Create a prediction on Replicate."""
        try:
            url = f"{self.base_url}/predictions"
            headers = {
                "Authorization": f"Token {self.api_token}",
                "Content-Type": "application/json",
            }
            
            payload = {
                "version": await self._get_model_version(model),
                "input": input_data
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                
                if response.status_code == 201:
                    return response.json()
                else:
                    logger.error(f"❌ Replicate API error {response.status_code}: {response.text}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Create prediction failed: {e}")
            return None
    
    async def _get_model_version(self, model: str) -> str:
        """
        Get the latest version ID for a model.
        
        Note: In production, these should be cached or stored as env vars.
        For now, using placeholder version strings.
        """
        # These are placeholder version IDs - update with actual latest versions
        version_map = {
            self.FLUX_SCHNELL: "flux-schnell-latest",
            self.FLUX_DEV: "flux-dev-latest",
            self.SDXL: "sdxl-latest",
        }
        return version_map.get(model, "latest")
    
    async def _wait_for_prediction(
        self,
        prediction_id: str,
        max_wait: int = 60
    ) -> Optional[str]:
        """
        Wait for prediction to complete and return image URL.
        
        Args:
            prediction_id: Prediction ID from Replicate
            max_wait: Maximum seconds to wait
            
        Returns:
            Image URL or None
        """
        try:
            url = f"{self.base_url}/predictions/{prediction_id}"
            headers = {"Authorization": f"Token {self.api_token}"}
            
            import asyncio
            
            async with httpx.AsyncClient(timeout=max_wait + 10) as client:
                # Poll every 2 seconds
                for _ in range(max_wait // 2):
                    response = await client.get(url, headers=headers)
                    
                    if response.status_code != 200:
                        logger.error(f"❌ Prediction status check failed: {response.status_code}")
                        return None
                    
                    data = response.json()
                    status = data.get("status")
                    
                    if status == "succeeded":
                        output = data.get("output")
                        if isinstance(output, list) and len(output) > 0:
                            return output[0]
                        elif isinstance(output, str):
                            return output
                        else:
                            logger.error(f"❌ Unexpected output format: {output}")
                            return None
                    
                    elif status == "failed":
                        error = data.get("error", "Unknown error")
                        logger.error(f"❌ Prediction failed: {error}")
                        return None
                    
                    # Still processing, wait
                    await asyncio.sleep(2)
                
                logger.warning(f"⚠️ Prediction timeout after {max_wait}s")
                return None
                
        except Exception as e:
            logger.error(f"❌ Wait for prediction failed: {e}")
            return None
    
    async def _download_image(self, image_url: str, prompt: str) -> Optional[Path]:
        """Download generated image from URL."""
        try:
            output_path = self.output_dir / f"replicate_{hash(prompt) % 100000}.png"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(image_url)
                
                if response.status_code == 200:
                    async with aiofiles.open(output_path, mode="wb") as f:
                        await f.write(response.content)
                    return output_path
                else:
                    logger.error(f"❌ Image download failed: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Image download error: {e}")
            return None
    
    def create_enhanced_prompt(self, base_prompt: str) -> str:
        """Enhance prompt for Flux.1."""
        style = "Professional photography, cinematic lighting, 8k uhd, high quality, trending on artstation"
        return f"{base_prompt}, {style}"


# Singleton instance
_replicate_service: Optional[ReplicateService] = None


def get_replicate_service() -> ReplicateService:
    """Get or create singleton Replicate service instance."""
    global _replicate_service
    if _replicate_service is None:
        _replicate_service = ReplicateService()
    return _replicate_service
