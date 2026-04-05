"""
Dynamic Templates API — ViraClip

Endpoints for fetching niche-specific video templates, generating
complete style configs, and matching templates to content.
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.dynamic_templates import (
    DynamicTemplateSystem,
    NicheTemplateType,
    get_dynamic_template_system,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/templates", tags=["templates"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class OptimalSettingsRequest(BaseModel):
    niche: str
    content_duration: int = 60
    target_platform: str = "tiktok"


class StyleConfigRequest(BaseModel):
    niche: str
    content_type: str = "general"
    target_platform: str = "tiktok"


class SuggestRequest(BaseModel):
    content_description: str
    keywords: List[str] = []


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_niche(value: str) -> NicheTemplateType:
    try:
        return NicheTemplateType(value.lower())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown niche '{value}'. Valid niches: {[n.value for n in NicheTemplateType]}",
        )


def _fmt_template(tmpl) -> Dict[str, Any]:
    return {
        "niche": tmpl.niche.value,
        "name": tmpl.name,
        "description": tmpl.description,
        "style": {
            "primary_color": tmpl.style.primary_color,
            "secondary_color": tmpl.style.secondary_color,
            "accent_color": tmpl.style.accent_color,
            "font_family": tmpl.style.font_family,
            "title_style": tmpl.style.title_style,
            "animation_speed": tmpl.style.animation_speed,
            "effect_intensity": tmpl.style.effect_intensity,
        },
        "timing": {
            "intro_seconds": tmpl.intro_duration,
            "outro_seconds": tmpl.outro_duration,
            "optimal_duration_min": tmpl.optimal_duration_range[0],
            "optimal_duration_max": tmpl.optimal_duration_range[1],
        },
        "content": {
            "caption_style": tmpl.caption_style,
            "recommended_music": tmpl.recommended_music_genres,
            "suggested_effects": tmpl.suggested_effects,
            "hashtags": tmpl.hashtag_recommendations,
            "best_posting_times": tmpl.best_posting_times,
        },
    }


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.get("")
def list_templates():
    """List all 10 niche-specific templates with their full configuration."""
    system = get_dynamic_template_system()
    templates = [_fmt_template(t) for t in system.TEMPLATES.values()]
    return {"count": len(templates), "templates": templates}


@router.get("/{niche}")
def get_template(niche: str):
    """Get the full template configuration for a specific content niche."""
    niche_type = _parse_niche(niche)
    system = get_dynamic_template_system()
    tmpl = system.get_template(niche_type)
    return {"status": "success", "template": _fmt_template(tmpl)}


@router.post("/optimal-settings")
def get_optimal_settings(body: OptimalSettingsRequest):
    """
    Get optimal rendering settings for a niche, content duration,
    and target platform. Returns style, timing, music, and posting recommendations.
    """
    niche_type = _parse_niche(body.niche)
    system = get_dynamic_template_system()
    settings = system.get_optimal_settings(
        niche_type, body.content_duration, body.target_platform
    )
    return {"status": "success", "settings": settings}


@router.post("/style-config")
def generate_style_config(body: StyleConfigRequest):
    """
    Generate a complete style configuration ready for the render pipeline.
    Includes colors, typography, effects, audio levels, platform safe zones,
    and hashtag recommendations.
    """
    system = get_dynamic_template_system()
    config = system.generate_complete_style_config(
        body.niche, body.content_type, body.target_platform
    )
    return {"status": "success", "config": config}


@router.post("/suggest")
def suggest_templates(body: SuggestRequest):
    """
    Suggest the top 3 templates that best match a content description and keywords.
    Each suggestion includes a confidence score and color/font preview.
    """
    if not body.content_description and not body.keywords:
        raise HTTPException(
            status_code=400,
            detail="Provide at least content_description or keywords",
        )
    system = get_dynamic_template_system()
    suggestions = system.suggest_templates_for_content(
        body.content_description, body.keywords
    )
    return {
        "status": "success",
        "count": len(suggestions),
        "suggestions": suggestions,
    }


@router.get("/niches/list")
def list_niches():
    """List all available niche types."""
    return {"niches": [n.value for n in NicheTemplateType]}
