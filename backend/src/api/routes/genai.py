"""
Generative AI API — ViraClip

Endpoints for generating AI-powered thumbnails, video backgrounds,
and text effects using DALL-E and other providers.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...services.generative_ai import (
    GenerativeAIService,
    get_generative_ai_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/genai", tags=["genai"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class GenerateThumbnailRequest(BaseModel):
    video_title: str
    video_description: str = ""
    style: str = "viral"   # viral | professional | dramatic | minimal


class GenerateBackgroundRequest(BaseModel):
    theme: str
    mood: str = "energetic"


class GenerateTextEffectRequest(BaseModel):
    text: str
    effect_style: str = "bold"


class BatchThumbnailRequest(BaseModel):
    videos: List[Dict[str, str]]    # [{title, description, user_id?}]
    style: str = "viral"


class ConfigureProviderRequest(BaseModel):
    provider: str    # dalle | midjourney | stable_diffusion | openai
    api_key: str
    additional_config: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_result(result) -> Dict[str, Any]:
    return {
        "request_id": result.request_id,
        "success": result.success,
        "image_url": result.image_url,
        "local_path": str(result.local_path) if result.local_path else None,
        "generation_time_ms": result.generation_time_ms,
        "prompt_used": result.prompt_used,
        "cost_usd": result.cost_usd,
        "error_message": result.error_message,
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/thumbnail")
async def generate_thumbnail(request: Request, body: GenerateThumbnailRequest):
    """
    Generate a viral-optimised AI thumbnail using DALL-E.

    `style` options: `viral | professional | dramatic | minimal`
    """
    user = getattr(request.state, "user", None)
    user_id = user.id if user else "anonymous"

    svc = get_generative_ai_service()
    try:
        result = await svc.generate_thumbnail(
            video_title=body.video_title,
            video_description=body.video_description,
            style=body.style,
            user_id=user_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "result": _fmt_result(result)}


@router.post("/thumbnail/batch")
async def batch_generate_thumbnails(body: BatchThumbnailRequest):
    """Generate AI thumbnails for multiple videos in one call."""
    if not body.videos:
        raise HTTPException(status_code=400, detail="videos must not be empty")

    svc = get_generative_ai_service()
    try:
        results = await svc.batch_generate_thumbnails(body.videos, body.style)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "count": len(results),
        "results": [_fmt_result(r) for r in results],
    }


@router.post("/background")
async def generate_background(body: GenerateBackgroundRequest):
    """
    Generate an AI video background based on theme and mood.
    Outputs a seamless 9:16 image suitable for video overlay.
    """
    svc = get_generative_ai_service()
    try:
        result = await svc.generate_background(theme=body.theme, mood=body.mood)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "result": _fmt_result(result)}


@router.post("/text-effect")
async def generate_text_effect(body: GenerateTextEffectRequest):
    """
    Generate a stylised text graphic (e.g. title card, caption overlay).
    Returns a transparent-background PNG.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="text must not be empty")

    svc = get_generative_ai_service()
    try:
        result = await svc.generate_text_effect(
            text=body.text,
            effect_style=body.effect_style,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "success", "result": _fmt_result(result)}


@router.post("/configure")
def configure_provider(body: ConfigureProviderRequest):
    """
    Configure an API key for a generative AI provider.
    Supported: `dalle | midjourney | stable_diffusion | openai`
    """
    from ...services.generative_ai import GenerativeProvider
    try:
        provider = GenerativeProvider(body.provider)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider '{body.provider}'. Choose: {[p.value for p in GenerativeProvider]}",
        )

    svc = get_generative_ai_service()
    svc.configure_provider(provider, body.api_key, body.additional_config)
    return {"status": "configured", "provider": body.provider}


@router.get("/stats")
def get_stats(request: Request):
    """
    Get generation statistics: total requests, success rate,
    cumulative cost, and average generation time.
    """
    svc = get_generative_ai_service()
    user = getattr(request.state, "user", None)
    user_id = user.id if user else None

    stats = svc.get_generation_stats()
    response = {"status": "success", "stats": stats}

    if user_id:
        response["user_cost_usd"] = round(svc.get_user_costs(user_id), 4)

    return response
