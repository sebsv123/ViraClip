"""
Multi-Language API — ViraClip

Endpoints for language detection, transcription config recommendations,
subtitle styling, and keyword translation across 15 supported languages.
"""

import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services.multilanguage_service import (
    MultiLanguageService,
    SupportedLanguage,
    get_language_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/languages", tags=["languages"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class DetectLanguageRequest(BaseModel):
    text_sample: Optional[str] = None
    audio_path: Optional[str] = None    # server-side path


class TranscriptionConfigRequest(BaseModel):
    language_code: str          # e.g. "en", "es", "zh"
    processing_mode: str = "balanced"   # fast | balanced | quality


class SubtitleStyleRequest(BaseModel):
    language_code: str


class TranslateKeywordsRequest(BaseModel):
    keywords: List[str]
    source_language: str = "en"
    target_language: str


class FontRequest(BaseModel):
    language_code: str
    preference: str = "modern"   # modern | traditional | fallback


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _parse_language(code: str) -> SupportedLanguage:
    lang = SupportedLanguage.from_code(code)
    if lang is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language code '{code}'. See GET /languages for supported codes.",
        )
    return lang


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@router.post("/detect")
async def detect_language(body: DetectLanguageRequest):
    """
    Detect the language from a text sample or audio file path.

    - **text_sample**: Detects using character/word heuristics (fast).
    - **audio_path**: Detects via Whisper model (more accurate, slower).
    - Both can be provided; audio takes priority.
    """
    if not body.text_sample and not body.audio_path:
        raise HTTPException(
            status_code=400,
            detail="Provide at least one of: text_sample, audio_path",
        )

    svc = get_language_service()
    audio = Path(body.audio_path) if body.audio_path else None
    try:
        result = await svc.detect_language(
            audio_path=audio,
            text_sample=body.text_sample,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "success",
        "detected_language": result.detected_language.code,
        "language_name": result.detected_language.full_name,
        "confidence": round(result.confidence, 3),
        "is_reliable": result.is_reliable,
        "alternatives": [
            {"code": lang.code, "name": lang.full_name, "confidence": round(conf, 3)}
            for lang, conf in result.alternative_languages
        ],
    }


@router.post("/transcription-config")
def get_transcription_config(body: TranscriptionConfigRequest):
    """
    Get the optimal Whisper transcription settings for a language.

    Returns model size, VAD flag, word timestamp flag, recommended font,
    and subtitle style for the language.
    """
    lang = _parse_language(body.language_code)
    svc = get_language_service()
    config = svc.get_transcription_config(lang, body.processing_mode)

    return {
        "status": "success",
        "language_code": lang.code,
        "language_name": lang.full_name,
        "model_size": config.model_size,
        "use_vad": config.use_vad,
        "word_timestamps": config.word_timestamps,
        "font": svc.get_font_for_language(lang),
        "subtitle_style": svc.get_subtitle_style(lang),
    }


@router.post("/subtitle-style")
def get_subtitle_style(body: SubtitleStyleRequest):
    """
    Get subtitle rendering recommendations for a language (font size,
    position, RTL flag, CJK line width, etc.).
    """
    lang = _parse_language(body.language_code)
    svc = get_language_service()
    style = svc.get_subtitle_style(lang)
    font = svc.get_font_for_language(lang)
    return {
        "status": "success",
        "language_code": lang.code,
        "font": font,
        "style": style,
    }


@router.post("/translate-keywords")
def translate_keywords(body: TranslateKeywordsRequest):
    """
    Translate a list of viral keywords from one language to another.
    Useful for adapting hashtags and metadata for international content.
    """
    if not body.keywords:
        raise HTTPException(status_code=400, detail="keywords must not be empty")

    source = _parse_language(body.source_language)
    target = _parse_language(body.target_language)
    svc = get_language_service()
    translations = svc.translate_keywords(body.keywords, source, target)
    return {
        "status": "success",
        "source_language": source.code,
        "target_language": target.code,
        "translations": translations,
    }


@router.get("/font")
def get_font(language_code: str, preference: str = "modern"):
    """Get the recommended font for a language and style preference."""
    lang = _parse_language(language_code)
    svc = get_language_service()
    font = svc.get_font_for_language(lang, preference)
    return {
        "language_code": lang.code,
        "preference": preference,
        "font": font,
    }


@router.get("")
def list_languages():
    """List all 15 supported languages with their codes and names."""
    return {
        "count": len(list(SupportedLanguage)),
        "languages": [
            {"code": lang.code, "name": lang.full_name, "iso3": lang.iso3_code}
            for lang in SupportedLanguage
        ],
    }
