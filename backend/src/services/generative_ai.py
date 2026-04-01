"""
Generative AI Integration Service
Integration with DALL-E, Midjourney, and other generative AI services for content enhancement.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class GenerativeProvider(Enum):
    """Supported generative AI providers."""
    DALLE = "dalle"
    MIDJOURNEY = "midjourney"
    STABLE_DIFFUSION = "stable_diffusion"
    OPENAI = "openai"


class ContentType(Enum):
    """Types of generative content."""
    THUMBNAIL = "thumbnail"
    BACKGROUND = "background"
    OVERLAY = "overlay"
    TEXT_EFFECT = "text_effect"
    AVATAR = "avatar"


@dataclass
class GenerationRequest:
    """Request for generative content."""
    request_id: str
    provider: GenerativeProvider
    content_type: ContentType
    prompt: str
    negative_prompt: Optional[str]
    style: str
    dimensions: tuple  # (width, height)
    user_id: str
    created_at: str


@dataclass
class GenerationResult:
    """Result of generative content creation."""
    request_id: str
    success: bool
    image_url: Optional[str]
    local_path: Optional[Path]
    generation_time_ms: int
    prompt_used: str
    cost_usd: float
    error_message: Optional[str]


class GenerativeAIService:
    """
    Service for generating AI-powered visual content.
    """
    
    def __init__(self):
        self._api_keys: Dict[GenerativeProvider, str] = {}
        self._generation_history: List[Dict[str, Any]] = []
        self._cost_tracker: Dict[str, float] = {}
    
    def configure_provider(
        self,
        provider: GenerativeProvider,
        api_key: str,
        additional_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Configure API key for a provider."""
        self._api_keys[provider] = api_key
        logger.info(f"Configured {provider.value} integration")
    
    async def generate_thumbnail(
        self,
        video_title: str,
        video_description: str,
        style: str = "viral",
        user_id: str = "anonymous"
    ) -> GenerationResult:
        """
        Generate AI-powered thumbnail for video.
        
        Args:
            video_title: Video title for context
            video_description: Video description
            style: Visual style (viral, professional, minimal, dramatic)
            user_id: User requesting generation
        """
        import uuid
        
        request_id = str(uuid.uuid4())
        
        # Build optimized prompt for viral thumbnails
        prompt = self._build_thumbnail_prompt(
            video_title, video_description, style
        )
        
        request = GenerationRequest(
            request_id=request_id,
            provider=GenerativeProvider.DALLE,  # Default to DALL-E
            content_type=ContentType.THUMBNAIL,
            prompt=prompt,
            negative_prompt="blurry, low quality, text, watermark, logo",
            style=style,
            dimensions=(1080, 1920),  # Vertical 9:16
            user_id=user_id,
            created_at=datetime.now().isoformat()
        )
        
        # Generate
        result = await self._generate_with_dalle(request)
        
        # Track
        self._track_generation(request, result)
        
        return result
    
    def _build_thumbnail_prompt(
        self,
        title: str,
        description: str,
        style: str
    ) -> str:
        """Build optimized prompt for thumbnail generation."""
        base_prompt = f"YouTube thumbnail style image: {title}. "
        
        style_modifiers = {
            "viral": "eye-catching, high contrast, vibrant colors, dramatic lighting, professional photography, 4k, trending on social media",
            "professional": "clean, corporate, minimalist, high quality, professional lighting, business aesthetic",
            "dramatic": "cinematic, dramatic lighting, intense colors, movie poster style, epic composition",
            "minimal": "minimalist, clean background, simple composition, modern aesthetic, negative space"
        }
        
        modifier = style_modifiers.get(style, style_modifiers["viral"])
        
        return f"{base_prompt}{modifier}"
    
    async def _generate_with_dalle(self, request: GenerationRequest) -> GenerationResult:
        """Generate image using DALL-E."""
        import aiohttp
        import os
        
        api_key = self._api_keys.get(GenerativeProvider.DALLE)
        
        if not api_key:
            return GenerationResult(
                request_id=request.request_id,
                success=False,
                image_url=None,
                local_path=None,
                generation_time_ms=0,
                prompt_used=request.prompt,
                cost_usd=0.0,
                error_message="DALL-E API key not configured"
            )
        
        start_time = datetime.now()
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "dall-e-3",
                        "prompt": request.prompt,
                        "size": "1024x1792",  # Vertical orientation
                        "quality": "standard",
                        "n": 1
                    },
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        image_url = data["data"][0]["url"]
                        
                        # Download image locally
                        local_path = await self._download_image(image_url, request.request_id)
                        
                        generation_time = (datetime.now() - start_time).total_seconds() * 1000
                        
                        return GenerationResult(
                            request_id=request.request_id,
                            success=True,
                            image_url=image_url,
                            local_path=local_path,
                            generation_time_ms=int(generation_time),
                            prompt_used=request.prompt,
                            cost_usd=0.04,  # DALL-E 3 standard pricing
                            error_message=None
                        )
                    else:
                        error_text = await response.text()
                        return GenerationResult(
                            request_id=request.request_id,
                            success=False,
                            image_url=None,
                            local_path=None,
                            generation_time_ms=0,
                            prompt_used=request.prompt,
                            cost_usd=0.0,
                            error_message=f"API error: {error_text}"
                        )
                        
        except Exception as e:
            return GenerationResult(
                request_id=request.request_id,
                success=False,
                image_url=None,
                local_path=None,
                generation_time_ms=0,
                prompt_used=request.prompt,
                cost_usd=0.0,
                error_message=str(e)
            )
    
    async def _download_image(self, url: str, request_id: str) -> Optional[Path]:
        """Download generated image to local storage."""
        import aiohttp
        
        output_dir = Path("/app/temp/generated_images")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        output_path = output_dir / f"gen_{request_id}.png"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        with open(output_path, 'wb') as f:
                            f.write(content)
                        return output_path
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
        
        return None
    
    async def generate_background(
        self,
        theme: str,
        mood: str,
        dimensions: tuple = (1080, 1920)
    ) -> GenerationResult:
        """Generate background image for video."""
        import uuid
        
        request = GenerationRequest(
            request_id=str(uuid.uuid4()),
            provider=GenerativeProvider.DALLE,
            content_type=ContentType.BACKGROUND,
            prompt=f"Seamless video background: {theme}, {mood} atmosphere, abstract, subtle motion texture, high quality, 4k",
            negative_prompt="people, text, logos, watermarks, busy patterns",
            style="minimal",
            dimensions=dimensions,
            user_id="system",
            created_at=datetime.now().isoformat()
        )
        
        return await self._generate_with_dalle(request)
    
    async def generate_text_effect(
        self,
        text: str,
        effect_style: str,
        dimensions: tuple = (1080, 200)
    ) -> GenerationResult:
        """Generate stylized text image."""
        import uuid
        
        request = GenerationRequest(
            request_id=str(uuid.uuid4()),
            provider=GenerativeProvider.DALLE,
            content_type=ContentType.TEXT_EFFECT,
            prompt=f'Text graphic: "{text}" in {effect_style} style, transparent background, bold typography, viral social media style',
            negative_prompt="background, cluttered, hard to read",
            style=effect_style,
            dimensions=dimensions,
            user_id="system",
            created_at=datetime.now().isoformat()
        )
        
        return await self._generate_with_dalle(request)
    
    async def batch_generate_thumbnails(
        self,
        videos: List[Dict[str, str]],
        style: str = "viral"
    ) -> List[GenerationResult]:
        """Generate thumbnails for multiple videos."""
        results = []
        
        for video in videos:
            result = await self.generate_thumbnail(
                video.get("title", ""),
                video.get("description", ""),
                style,
                video.get("user_id", "anonymous")
            )
            results.append(result)
        
        return results
    
    def _track_generation(
        self,
        request: GenerationRequest,
        result: GenerationResult
    ) -> None:
        """Track generation in history."""
        self._generation_history.append({
            "request_id": request.request_id,
            "provider": request.provider.value,
            "content_type": request.content_type.value,
            "timestamp": request.created_at,
            "success": result.success,
            "cost_usd": result.cost_usd,
            "generation_time_ms": result.generation_time_ms
        })
        
        # Track cost by user
        if request.user_id not in self._cost_tracker:
            self._cost_tracker[request.user_id] = 0.0
        self._cost_tracker[request.user_id] += result.cost_usd
    
    def get_user_costs(self, user_id: str) -> float:
        """Get total generation costs for user."""
        return self._cost_tracker.get(user_id, 0.0)
    
    def get_generation_stats(self) -> Dict[str, Any]:
        """Get generation statistics."""
        total = len(self._generation_history)
        successful = sum(1 for g in self._generation_history if g["success"])
        total_cost = sum(g["cost_usd"] for g in self._generation_history)
        
        return {
            "total_generations": total,
            "successful": successful,
            "failed": total - successful,
            "total_cost_usd": round(total_cost, 2),
            "avg_generation_time_ms": (
                sum(g["generation_time_ms"] for g in self._generation_history) / total
                if total > 0 else 0
            )
        }


# Global instance
_gen_ai_service: Optional[GenerativeAIService] = None


def get_generative_ai_service() -> GenerativeAIService:
    """Get global generative AI service."""
    global _gen_ai_service
    if _gen_ai_service is None:
        _gen_ai_service = GenerativeAIService()
    return _gen_ai_service


# Convenience functions
async def generate_ai_thumbnail(
    title: str,
    description: str,
    style: str = "viral"
) -> Optional[Path]:
    """Generate AI thumbnail for video."""
    service = get_generative_ai_service()
    result = await service.generate_thumbnail(title, description, style)
    return result.local_path if result.success else None


async def generate_video_background(theme: str, mood: str) -> Optional[Path]:
    """Generate AI background for video."""
    service = get_generative_ai_service()
    result = await service.generate_background(theme, mood)
    return result.local_path if result.success else None
