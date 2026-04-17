"""Language Detection API — detect language and get locale-aware LLM prompts."""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/language-detect", tags=["Language Detection"])


class DetectRequest(BaseModel):
    text: str
    fallback: str = "en"


class LocalePromptRequest(BaseModel):
    text: str
    task: str = "virality"       # virality | hashtags | hook | cta
    language: Optional[str] = None


@router.post("/detect")
def detect_language(req: DetectRequest):
    """Detect language from transcript text."""
    from src.services.language_detector import detect_language as _detect
    result = _detect(req.text, fallback=req.fallback)
    return {
        "language": result.language,
        "confidence": result.confidence,
        "is_supported": result.is_supported,
        "locale": result.locale,
    }


@router.post("/locale-prompt")
def get_locale_prompt(req: LocalePromptRequest):
    """Return a locale-aware LLM system prompt for the given task."""
    from src.services.language_detector import build_locale_prompt
    prompt = build_locale_prompt(req.text, req.task, language=req.language)
    return {"task": req.task, "prompt": prompt}


@router.get("/supported")
def list_supported_languages():
    """Return all 15 supported languages."""
    from src.services.language_detector import supported_languages
    return {"languages": supported_languages()}


@router.get("/locale/{language_code}")
def get_locale(language_code: str):
    """Return locale config for an explicit language code."""
    from src.services.language_detector import get_locale as _get
    locale = _get(language_code)
    return {"language": language_code, "locale": locale}
