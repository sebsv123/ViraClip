"""
Image Generation API Routes
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...services.image_gen_service import ImageGenService

router = APIRouter(prefix="/image-gen", tags=["Image Generation"])


class GenerateImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    aspect_ratio: str = Field("9:16", pattern="^(9:16|16:9|1:1|4:5)$")
    provider: str = Field("dalle", pattern="^(dalle|sdxl)$")


class KenBurnsPromptRequest(BaseModel):
    video_context: str = Field(..., min_length=1)
    transcript_segment: str = Field(..., min_length=1)
    provider: str = Field("dalle", pattern="^(dalle|sdxl)$")


@router.post("/generate")
async def generate_image(body: GenerateImageRequest) -> Dict[str, Any]:
    """Generate a context-aware image using DALL-E 3 or local SDXL."""
    svc = ImageGenService(provider=body.provider)
    try:
        result = await svc.generate_image(body.prompt, aspect_ratio=body.aspect_ratio)
        if result is None:
            raise HTTPException(
                status_code=503,
                detail="Image generation unavailable — check OPENAI_API_KEY or SDXL setup",
            )
        return {
            "prompt": body.prompt,
            "aspect_ratio": body.aspect_ratio,
            "provider": body.provider,
            "output_path": str(result),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ken-burns-prompt")
async def build_ken_burns_prompt(body: KenBurnsPromptRequest) -> Dict[str, Any]:
    """Generate an optimised cinematic prompt for Ken Burns / B-roll image generation."""
    svc = ImageGenService(provider=body.provider)
    try:
        prompt = svc.create_ken_burns_prompt(body.video_context, body.transcript_segment)
        return {
            "video_context": body.video_context,
            "transcript_segment": body.transcript_segment,
            "generated_prompt": prompt,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
