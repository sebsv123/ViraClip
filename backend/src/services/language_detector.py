"""
Language Detector — detect transcript language and return locale-aware
LLM prompt hints for virality scoring, hashtag generation, and hook detection.

Supports EN, ES, PT, HI, FR, DE, IT, AR, ZH, KO, JA, RU, NL, PL, TR (15 languages).
Uses langdetect (pure Python, no network) with confidence-based fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ── Supported locale table ─────────────────────────────────────────────────────

SUPPORTED_LOCALES: dict[str, dict] = {
    "en": {
        "name": "English",
        "territory": "global",
        "hashtag_suffix": "",
        "hook_starters": ["Did you know", "Here's why", "Stop doing this", "The truth about"],
        "cta_templates": ["Follow for more!", "Like if this helped!", "Save this for later!"],
        "trending_territory": "US",
        "caption_dir": "ltr",
    },
    "es": {
        "name": "Spanish",
        "territory": "latam",
        "hashtag_suffix": "es",
        "hook_starters": ["¿Sabías que", "La verdad sobre", "Para de hacer esto", "Así es como"],
        "cta_templates": ["¡Sígueme para más!", "¡Guarda esto para después!", "¡Comparte si te ayudó!"],
        "trending_territory": "MX",
        "caption_dir": "ltr",
    },
    "pt": {
        "name": "Portuguese",
        "territory": "latam",
        "hashtag_suffix": "pt",
        "hook_starters": ["Você sabia que", "A verdade sobre", "Pare de fazer isso", "É assim que"],
        "cta_templates": ["Siga para mais!", "Salva pra depois!", "Compartilha se ajudou!"],
        "trending_territory": "BR",
        "caption_dir": "ltr",
    },
    "hi": {
        "name": "Hindi",
        "territory": "india",
        "hashtag_suffix": "hi",
        "hook_starters": ["क्या आप जानते हैं", "इसकी सच्चाई", "यह करना बंद करें"],
        "cta_templates": ["फॉलो करें!", "सेव करें!", "शेयर करें!"],
        "trending_territory": "IN",
        "caption_dir": "ltr",
    },
    "fr": {
        "name": "French",
        "territory": "fr",
        "hashtag_suffix": "fr",
        "hook_starters": ["Le saviez-vous", "La vérité sur", "Arrêtez de faire ça", "Voici comment"],
        "cta_templates": ["Suivez pour plus!", "Sauvegardez ça!", "Partagez si utile!"],
        "trending_territory": "FR",
        "caption_dir": "ltr",
    },
    "de": {
        "name": "German",
        "territory": "de",
        "hashtag_suffix": "de",
        "hook_starters": ["Wusstest du das", "Die Wahrheit über", "Hör auf damit", "So geht das"],
        "cta_templates": ["Folgen für mehr!", "Speichern für später!", "Teilen wenn hilfreich!"],
        "trending_territory": "DE",
        "caption_dir": "ltr",
    },
    "it": {
        "name": "Italian",
        "territory": "it",
        "hashtag_suffix": "it",
        "hook_starters": ["Lo sapevi che", "La verità su", "Smetti di fare questo"],
        "cta_templates": ["Seguimi per altro!", "Salva per dopo!", "Condividi se utile!"],
        "trending_territory": "IT",
        "caption_dir": "ltr",
    },
    "ar": {
        "name": "Arabic",
        "territory": "ar",
        "hashtag_suffix": "ar",
        "hook_starters": ["هل تعلم أن", "الحقيقة حول", "توقف عن فعل هذا"],
        "cta_templates": ["تابعني للمزيد!", "احفظ هذا!", "شارك إذا أفاد!"],
        "trending_territory": "SA",
        "caption_dir": "rtl",
    },
    "zh": {
        "name": "Chinese",
        "territory": "cn",
        "hashtag_suffix": "zh",
        "hook_starters": ["你知道吗", "关于的真相", "停止这样做", "方法是这样的"],
        "cta_templates": ["关注更多!", "收藏备用!", "分享给朋友!"],
        "trending_territory": "TW",
        "caption_dir": "ltr",
    },
    "ko": {
        "name": "Korean",
        "territory": "kr",
        "hashtag_suffix": "ko",
        "hook_starters": ["알고 계셨나요", "이것의 진실", "이것을 그만하세요"],
        "cta_templates": ["팔로우 해주세요!", "저장해두세요!", "공유해주세요!"],
        "trending_territory": "KR",
        "caption_dir": "ltr",
    },
    "ja": {
        "name": "Japanese",
        "territory": "jp",
        "hashtag_suffix": "ja",
        "hook_starters": ["知っていましたか", "これの真実", "これをやめてください"],
        "cta_templates": ["フォローしてください!", "保存してください!", "シェアしてください!"],
        "trending_territory": "JP",
        "caption_dir": "ltr",
    },
    "ru": {
        "name": "Russian",
        "territory": "ru",
        "hashtag_suffix": "ru",
        "hook_starters": ["Знали ли вы", "Правда о", "Прекратите делать это"],
        "cta_templates": ["Подписывайтесь!", "Сохраните!", "Поделитесь!"],
        "trending_territory": "RU",
        "caption_dir": "ltr",
    },
    "nl": {
        "name": "Dutch",
        "territory": "nl",
        "hashtag_suffix": "nl",
        "hook_starters": ["Wist je dat", "De waarheid over", "Stop hiermee"],
        "cta_templates": ["Volg voor meer!", "Bewaar dit!", "Deel als het hielp!"],
        "trending_territory": "NL",
        "caption_dir": "ltr",
    },
    "pl": {
        "name": "Polish",
        "territory": "pl",
        "hashtag_suffix": "pl",
        "hook_starters": ["Czy wiedziałeś", "Prawda o tym", "Przestań to robić"],
        "cta_templates": ["Obserwuj po więcej!", "Zapisz na później!", "Udostępnij jeśli pomogło!"],
        "trending_territory": "PL",
        "caption_dir": "ltr",
    },
    "tr": {
        "name": "Turkish",
        "territory": "tr",
        "hashtag_suffix": "tr",
        "hook_starters": ["Bunu biliyor muydunuz", "Bu konudaki gerçek", "Bunu yapmayı bırakın"],
        "cta_templates": ["Daha fazlası için takip et!", "Sonra bakmak için kaydet!", "Faydalıysa paylaş!"],
        "trending_territory": "TR",
        "caption_dir": "ltr",
    },
}


@dataclass
class DetectionResult:
    language: str           # ISO 639-1 code (en, es, pt, …)
    confidence: float       # 0-1
    locale: dict            # full locale entry from SUPPORTED_LOCALES
    is_supported: bool


def detect_language(text: str, fallback: str = "en") -> DetectionResult:
    """
    Detect language from transcript text.
    Uses langdetect if available; falls back to 'en'.
    """
    if not text or len(text.split()) < 5:
        lang = fallback
        conf = 0.5
    else:
        try:
            from langdetect import detect_langs  # type: ignore
            results = detect_langs(text[:500])
            if results:
                top = results[0]
                lang = top.lang
                conf = float(top.prob)
            else:
                lang, conf = fallback, 0.5
        except Exception as e:
            logger.debug("langdetect unavailable: %s — using fallback '%s'", e, fallback)
            lang, conf = fallback, 0.5

    lang = lang.lower()[:2]
    is_supported = lang in SUPPORTED_LOCALES
    locale = SUPPORTED_LOCALES.get(lang, SUPPORTED_LOCALES["en"])

    return DetectionResult(
        language=lang,
        confidence=round(conf, 3),
        locale=locale,
        is_supported=is_supported,
    )


def get_locale(language: str) -> dict:
    """Return locale config for an explicit ISO 639-1 language code."""
    return SUPPORTED_LOCALES.get(language.lower()[:2], SUPPORTED_LOCALES["en"])


def build_locale_prompt(
    text: str,
    task: str,
    language: Optional[str] = None,
) -> str:
    """
    Return a locale-aware system prompt prefix for LLM calls.

    task: "virality" | "hashtags" | "hook" | "cta"
    """
    if language:
        result = DetectionResult(
            language=language,
            confidence=1.0,
            locale=get_locale(language),
            is_supported=language in SUPPORTED_LOCALES,
        )
    else:
        result = detect_language(text)

    loc = result.locale
    lang_name = loc["name"]
    territory = loc["territory"].upper()

    prompts = {
        "virality": (
            f"You are a viral content expert for {lang_name}-speaking audiences "
            f"in {territory}. Analyse the following transcript and score its viral "
            f"potential (0-10) considering cultural resonance with {lang_name} speakers. "
            f"Respond in {lang_name}."
        ),
        "hashtags": (
            f"Generate trending hashtags for {lang_name}-speaking {territory} audiences. "
            f"Mix {lang_name} hashtags with universal English ones. "
            f"Return 10-15 hashtags, prioritise what's trending on TikTok {territory}."
        ),
        "hook": (
            f"You are a hook specialist for {lang_name} short-form video. "
            f"Identify the strongest hook in the transcript that resonates with "
            f"{lang_name}-speaking viewers. Use cultural context from {territory}."
        ),
        "cta": (
            f"Generate a platform-native CTA in {lang_name} that drives "
            f"follows/saves for {territory} audiences. Keep it under 8 words."
        ),
    }
    return prompts.get(task, prompts["virality"])


def supported_languages() -> list[dict]:
    """Return list of supported languages for API response."""
    return [
        {"code": code, "name": info["name"], "territory": info["territory"],
         "caption_dir": info["caption_dir"]}
        for code, info in SUPPORTED_LOCALES.items()
    ]
