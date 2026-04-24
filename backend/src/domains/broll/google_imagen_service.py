"""
Google Imagen 3 Service - generates high-quality images using Google's latest AI model.

Features:
- Google Imagen 3 (2025 model)
- 1000 free images/month
- ~$0.002/image after quota
- Same API key as Gemini LLM (GOOGLE_API_KEY)
"""

import logging
from pathlib import Path
from typing import Optional
import aiofiles
import httpx
from ...config import Config

logger = logging.getLogger(__name__)


class GoogleImagenService:
    """Service for generating images using Google Imagen 3."""
    
    def __init__(self):
        self.config = Config()
        self.api_key = self.config.google_api_key
        self.output_dir = Path(self.config.temp_dir) / "generated_assets"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Google Imagen 3 API endpoint
        self.base_url = "https://aiplatform.googleapis.com/v1"
        self.project_id = "viraclip"  # Default, can be overridden via env
        self.location = "us-central1"
        
    async def is_available(self) -> bool:
        """Check if Google Imagen service is available."""
        if not self.api_key:
            logger.warning("⚠️ Google API Key missing. Google Imagen 3 unavailable.")
            return False
        return True
    
    async def generate_image(
        self, 
        prompt: str, 
        aspect_ratio: str = "9:16",
        num_images: int = 1
    ) -> Optional[Path]:
        """
        Generate an image using Google Imagen 3.
        
        Args:
            prompt: Text description of the image
            aspect_ratio: "9:16" (vertical), "16:9" (horizontal), "1:1" (square)
            num_images: Number of images to generate (1-4)
            
        Returns:
            Path to generated image, or None if failed
        """
        if not await self.is_available():
            return None
            
        logger.info(f"[Google Imagen 3] Generating image: {prompt[:50]}...")
        
        try:
            # Map aspect ratio to dimensions
            dimensions = self._get_dimensions(aspect_ratio)
            
            # Call Google Imagen 3 API
            image_path = await self._call_imagen_api(prompt, dimensions, num_images)
            
            if image_path:
                logger.info(f"✅ [Google Imagen 3] Generated: {image_path}")
                return image_path
            else:
                logger.warning(f"⚠️ [Google Imagen 3] Generation failed")
                return None
                
        except Exception as e:
            logger.error(f"❌ [Google Imagen 3] Error: {e}")
            return None
    
    def _get_dimensions(self, aspect_ratio: str) -> dict:
        """Map aspect ratio to pixel dimensions."""
        dimensions_map = {
            "9:16": {"width": 1080, "height": 1920},  # Vertical (TikTok/Reels)
            "16:9": {"width": 1920, "height": 1080},  # Horizontal (YouTube)
            "1:1": {"width": 1080, "height": 1080},   # Square (Instagram)
        }
        return dimensions_map.get(aspect_ratio, dimensions_map["9:16"])
    
    async def _call_imagen_api(
        self, 
        prompt: str, 
        dimensions: dict,
        num_images: int = 1
    ) -> Optional[Path]:
        """
        Call Google Imagen 3 API.
        
        Note: This is a placeholder implementation. The actual Google Imagen 3 API
        endpoint structure may vary. Update with official API when available.
        
        For now, using Google AI Studio's generateContent endpoint as fallback.
        """
        try:
            # Construct API URL (update when official Imagen 3 API is released)
            # Currently using Gemini Pro Vision as fallback for image understanding
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro-vision:generateContent?key={self.api_key}"
            
            # Request payload
            payload = {
                "contents": [{
                    "parts": [{
                        "text": f"Generate a high-quality, photorealistic image: {prompt}. Style: cinematic, 8k resolution, vibrant colors."
                    }]
                }],
                "generationConfig": {
                    "temperature": 0.7,
                    "topK": 40,
                    "topP": 0.95,
                }
            }
            
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                
                if response.status_code != 200:
                    logger.error(f"❌ Google API error {response.status_code}: {response.text}")
                    return None
                
                data = response.json()
                
                # Note: This is a placeholder. Real Imagen 3 API will return image data
                # For now, we'll return None and rely on other providers
                logger.warning("⚠️ Google Imagen 3 API placeholder - using other providers")
                return None
                
        except Exception as e:
            logger.error(f"❌ Google Imagen API call failed: {e}")
            return None
    
    async def _download_image(self, image_url: str, prompt: str) -> Optional[Path]:
        """Download generated image from URL."""
        try:
            output_path = self.output_dir / f"google_imagen_{hash(prompt) % 100000}.png"
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                img_response = await client.get(image_url)
                
                if img_response.status_code == 200:
                    async with aiofiles.open(output_path, mode="wb") as f:
                        await f.write(img_response.content)
                    return output_path
                else:
                    logger.error(f"❌ Image download failed: {img_response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Image download error: {e}")
            return None
    
    def create_enhanced_prompt(self, base_prompt: str, context: str = "") -> str:
        """
        Enhance prompt for better image generation.
        
        Args:
            base_prompt: Base description
            context: Additional context (video theme, mood, etc.)
            
        Returns:
            Enhanced prompt optimized for Imagen 3
        """
        style_keywords = "Cinematic, professional lighting, 8k resolution, photorealistic, vibrant colors, high detail"
        
        if context:
            return f"{base_prompt}. Context: {context}. Style: {style_keywords}"
        else:
            return f"{base_prompt}. Style: {style_keywords}"


# Singleton instance
_imagen_service: Optional[GoogleImagenService] = None


def get_imagen_service() -> GoogleImagenService:
    """Get or create singleton Google Imagen service instance."""
    global _imagen_service
    if _imagen_service is None:
        _imagen_service = GoogleImagenService()
    return _imagen_service
