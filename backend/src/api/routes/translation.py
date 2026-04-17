"""
Auto-Translation API endpoints — ViraClip

Exposes AutoTranslationService for multi-language clip localization.
"""

import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.auto_translation import get_translation_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/translations", tags=["translations"])


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class TranslateClipRequest(BaseModel):
    clip_id: str
    title: str
    captions: List[dict] = []        # [{"start": 0.0, "end": 1.5, "text": "..."}]
    description: str = ""
    source_language: str = "en"
    target_languages: Optional[List[str]] = None   # None → top-5 defaults


class QuickTranslateRequest(BaseModel):
    text: str
    target_language: str
    source_language: str = "en"


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/clip")
async def translate_clip(body: TranslateClipRequest):
    """
    Translate a clip's title, captions, description and generate
    region-specific hashtags for all requested target languages.

    Default target languages (if not specified): es, fr, de, pt, ja
    """
    svc = get_translation_service()

    result = await svc.translate_clip_content(
        clip_id=body.clip_id,
        title=body.title,
        captions=body.captions,
        description=body.description,
        source_language=body.source_language,
        target_languages=body.target_languages,
    )

    return {
        "status": "success",
        "clip_id": result.clip_id,
        "generated_at": result.generated_at,
        "title_translations": result.title_translations,
        "description_translations": result.description_translations,
        "hashtag_suggestions": result.hashtag_suggestions,
        "caption_translations": result.caption_translations,
        "languages_count": len(result.title_translations),
    }


@router.post("/quick")
async def quick_translate(body: QuickTranslateRequest):
    """
    Translate a single text string to the target language.
    Useful for real-time caption translation or UI text.
    """
    svc = get_translation_service()

    result = await svc.translate_text(
        text=body.text,
        source_lang=body.source_language,
        target_lang=body.target_language,
    )

    return {
        "status": "success",
        "original": result.original_text,
        "translated": result.translated_text,
        "source_language": result.source_language,
        "target_language": result.target_language,
        "provider": result.provider.value,
        "confidence": result.confidence,
    }


@router.get("/languages")
async def list_languages():
    """List all supported translation languages."""
    svc = get_translation_service()
    return {
        "status": "success",
        "languages": svc.get_supported_languages(),
        "count": len(svc.get_supported_languages()),
    }


@router.get("/stats")
async def translation_stats():
    """Get translation usage statistics (cache size, provider, usage by language)."""
    svc = get_translation_service()
    return {"status": "success", "stats": svc.get_translation_stats()}


@router.post("/detect")
async def detect_language(text: str):
    """Detect the language of a text string."""
    svc = get_translation_service()
    lang = await svc.detect_language(text)
    languages = svc.get_supported_languages()
    return {
        "status": "success",
        "detected_language": lang,
        "language_name": languages.get(lang, "Unknown"),
    }
