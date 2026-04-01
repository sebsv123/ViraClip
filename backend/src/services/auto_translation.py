"""
Multi-language Auto-Translation Service
Translates clip captions and metadata for global audiences.
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class TranslationProvider(Enum):
    """Supported translation providers."""
    GOOGLE_TRANSLATE = "google"
    DEEPL = "deepl"
    OPENAI = "openai"
    LIBRETRANSLATE = "libre"


@dataclass
class TranslatedContent:
    """Translated content result."""
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    provider: TranslationProvider
    confidence: float
    timestamp: str


@dataclass
class ClipTranslation:
    """Complete clip translation package."""
    clip_id: str
    title_translations: Dict[str, str]
    caption_translations: Dict[str, str]
    description_translations: Dict[str, str]
    hashtag_suggestions: Dict[str, List[str]]
    generated_at: str


class AutoTranslationService:
    """
    Automatic translation service for clip localization.
    """
    
    # Language codes and their market priorities
    SUPPORTED_LANGUAGES = {
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "pt": "Portuguese",
        "it": "Italian",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
        "ru": "Russian",
        "ar": "Arabic",
        "hi": "Hindi",
        "nl": "Dutch",
        "pl": "Polish",
        "tr": "Turkish",
        "vi": "Vietnamese"
    }
    
    # Regional content adaptations
    REGIONAL_ADAPTATIONS = {
        "es": {
            "formality": "informal",
            "emoji_style": "high",
            "hashtag_language": "spanglish"
        },
        "ja": {
            "formality": "formal",
            "emoji_style": "minimal",
            "hashtag_language": "katakana_english"
        },
        "ar": {
            "formality": "formal",
            "emoji_style": "moderate",
            "text_direction": "rtl"
        }
    }
    
    def __init__(self, provider: TranslationProvider = TranslationProvider.OPENAI):
        self.provider = provider
        self._cache: Dict[str, TranslatedContent] = {}
        self._usage_stats: Dict[str, int] = {}
    
    async def translate_clip_content(
        self,
        clip_id: str,
        title: str,
        captions: List[Dict[str, Any]],
        description: str,
        source_language: str = "en",
        target_languages: Optional[List[str]] = None
    ) -> ClipTranslation:
        """
        Translate all clip content to multiple languages.
        
        Args:
            clip_id: Clip identifier
            title: Clip title
            captions: List of caption segments with text
            description: Clip description
            source_language: Source language code
            target_languages: Target languages (defaults to top 5)
        """
        if not target_languages:
            # Default to top 5 languages by market size
            target_languages = ["es", "fr", "de", "pt", "ja"]
        
        # Validate languages
        target_languages = [
            lang for lang in target_languages
            if lang in self.SUPPORTED_LANGUAGES
        ]
        
        title_translations = {}
        caption_translations = {}
        description_translations = {}
        hashtag_suggestions = {}
        
        # Translate title for each language
        for lang in target_languages:
            translated = await self.translate_text(
                title,
                source_language,
                lang,
                context="video_title"
            )
            title_translations[lang] = translated.translated_text
        
        # Translate captions
        for lang in target_languages:
            translated_captions = []
            for caption in captions:
                translated = await self.translate_text(
                    caption.get("text", ""),
                    source_language,
                    lang,
                    context="caption"
                )
                translated_captions.append({
                    "start": caption.get("start"),
                    "end": caption.get("end"),
                    "text": translated.translated_text
                })
            
            caption_translations[lang] = translated_captions
        
        # Translate description
        for lang in target_languages:
            translated = await self.translate_text(
                description,
                source_language,
                lang,
                context="description"
            )
            description_translations[lang] = translated.translated_text
        
        # Generate region-specific hashtags
        for lang in target_languages:
            hashtags = await self._generate_localized_hashtags(
                title,
                description,
                lang
            )
            hashtag_suggestions[lang] = hashtags
        
        return ClipTranslation(
            clip_id=clip_id,
            title_translations=title_translations,
            caption_translations=caption_translations,
            description_translations=description_translations,
            hashtag_suggestions=hashtag_suggestions,
            generated_at=datetime.now().isoformat()
        )
    
    async def translate_text(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: str = "general"
    ) -> TranslatedContent:
        """Translate a single text segment."""
        if not text or not text.strip():
            return TranslatedContent(
                original_text=text,
                translated_text=text,
                source_language=source_lang,
                target_language=target_lang,
                provider=self.provider,
                confidence=1.0,
                timestamp=datetime.now().isoformat()
            )
        
        # Check cache
        cache_key = f"{hash(text)}:{source_lang}:{target_lang}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Perform translation based on provider
        try:
            if self.provider == TranslationProvider.OPENAI:
                translated = await self._translate_with_openai(
                    text, source_lang, target_lang, context
                )
            elif self.provider == TranslationProvider.GOOGLE_TRANSLATE:
                translated = await self._translate_with_google(
                    text, source_lang, target_lang
                )
            elif self.provider == TranslationProvider.DEEPL:
                translated = await self._translate_with_deepl(
                    text, source_lang, target_lang
                )
            else:
                # Fallback to mock translation for demo
                translated = self._mock_translate(text, target_lang)
            
            # Cache result
            self._cache[cache_key] = translated
            
            # Track usage
            self._usage_stats[target_lang] = self._usage_stats.get(target_lang, 0) + 1
            
            return translated
            
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            # Return original as fallback
            return TranslatedContent(
                original_text=text,
                translated_text=text,
                source_language=source_lang,
                target_language=target_lang,
                provider=self.provider,
                confidence=0.0,
                timestamp=datetime.now().isoformat()
            )
    
    async def _translate_with_openai(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: str
    ) -> TranslatedContent:
        """Translate using OpenAI API."""
        # This would use OpenAI API for translation
        # For now, return mock translation
        return self._mock_translate(text, target_lang)
    
    async def _translate_with_google(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> TranslatedContent:
        """Translate using Google Translate API."""
        # Implementation would use google-cloud-translate
        return self._mock_translate(text, target_lang)
    
    async def _translate_with_deepl(
        self,
        text: str,
        source_lang: str,
        target_lang: str
    ) -> TranslatedContent:
        """Translate using DeepL API."""
        # Implementation would use DeepL API
        return self._mock_translate(text, target_lang)
    
    def _mock_translate(self, text: str, target_lang: str) -> TranslatedContent:
        """Mock translation for development."""
        # Simple mock - add language indicator
        lang_name = self.SUPPORTED_LANGUAGES.get(target_lang, target_lang)
        mock_translated = f"[{lang_name}] {text}"
        
        return TranslatedContent(
            original_text=text,
            translated_text=mock_translated,
            source_language="en",
            target_language=target_lang,
            provider=self.provider,
            confidence=0.85,
            timestamp=datetime.now().isoformat()
        )
    
    async def _generate_localized_hashtags(
        self,
        title: str,
        description: str,
        language: str
    ) -> List[str]:
        """Generate culture-specific hashtags."""
        base_hashtags = ["viral", "trending", "content"]
        
        # Language-specific popular tags
        lang_hashtags = {
            "es": ["viral", "tendencia", "video", "contenido"],
            "fr": ["viral", "tendance", "contenu", "video"],
            "de": ["viral", "trend", "inhalt", "video"],
            "ja": ["バイラル", "トレンド", "コンテンツ"],
            "ko": ["바이럴", "트렌드", "콘텐츠"],
            "pt": ["viral", "tendencia", "conteudo"],
            "zh": ["病毒式", "趋势", "内容"]
        }
        
        specific = lang_hashtags.get(language, base_hashtags)
        
        # Add regional adaptations
        adaptations = self.REGIONAL_ADAPTATIONS.get(language, {})
        if adaptations.get("hashtag_language") == "spanglish":
            specific.extend(["viralcontent", "mustwatch"])
        
        return specific[:8]  # Top 8 hashtags
    
    async def detect_language(self, text: str) -> str:
        """Detect language of text."""
        # Implementation would use language detection
        # For now, return English as default
        return "en"
    
    def get_supported_languages(self) -> Dict[str, str]:
        """Get list of supported languages."""
        return self.SUPPORTED_LANGUAGES
    
    def get_translation_stats(self) -> Dict[str, Any]:
        """Get translation usage statistics."""
        return {
            "provider": self.provider.value,
            "cache_size": len(self._cache),
            "translations_by_language": self._usage_stats,
            "supported_languages": len(self.SUPPORTED_LANGUAGES)
        }


# Global instance
_translation_service: Optional[AutoTranslationService] = None


def get_translation_service() -> AutoTranslationService:
    """Get global translation service."""
    global _translation_service
    if _translation_service is None:
        _translation_service = AutoTranslationService()
    return _translation_service


# Convenience functions
async def translate_clip_for_export(
    clip_id: str,
    title: str,
    captions: List[Dict[str, Any]],
    description: str,
    languages: Optional[List[str]] = None
) -> ClipTranslation:
    """Translate a clip for multi-language export."""
    return await get_translation_service().translate_clip_content(
        clip_id, title, captions, description, target_languages=languages
    )


async def quick_translate(text: str, target_lang: str) -> str:
    """Quick single text translation."""
    result = await get_translation_service().translate_text(
        text, "en", target_lang
    )
    return result.translated_text
