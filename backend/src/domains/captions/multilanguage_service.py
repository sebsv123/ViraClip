"""
Multi-language Support Module with Automatic Language Detection
Handles transcription, subtitles, and UI for multiple languages.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class SupportedLanguage(Enum):
    """Languages supported by the system."""
    ENGLISH = ("en", "English", "eng")
    SPANISH = ("es", "Spanish", "spa")
    FRENCH = ("fr", "French", "fra")
    GERMAN = ("de", "German", "deu")
    ITALIAN = ("it", "Italian", "ita")
    PORTUGUESE = ("pt", "Portuguese", "por")
    DUTCH = ("nl", "Dutch", "nld")
    RUSSIAN = ("ru", "Russian", "rus")
    CHINESE = ("zh", "Chinese", "zho")
    JAPANESE = ("ja", "Japanese", "jpn")
    KOREAN = ("ko", "Korean", "kor")
    ARABIC = ("ar", "Arabic", "ara")
    HINDI = ("hi", "Hindi", "hin")
    TURKISH = ("tr", "Turkish", "tur")
    POLISH = ("pl", "Polish", "pol")
    
    def __init__(self, code: str, name: str, iso3: str):
        self.code = code
        self.full_name = name
        self.iso3_code = iso3
    
    @classmethod
    def from_code(cls, code: str) -> Optional["SupportedLanguage"]:
        """Get language from 2-letter or 3-letter code."""
        code = code.lower()
        for lang in cls:
            if lang.code == code or lang.iso3_code == code:
                return lang
        return None


@dataclass
class LanguageDetectionResult:
    """Result of language detection."""
    detected_language: SupportedLanguage
    confidence: float
    is_reliable: bool
    alternative_languages: List[Tuple[SupportedLanguage, float]]


@dataclass
class TranscriptionConfig:
    """Configuration for transcription in a specific language."""
    language: SupportedLanguage
    model_size: str = "medium"  # tiny, base, small, medium, large
    use_vad: bool = True
    word_timestamps: bool = True
    
    # Language-specific optimizations
    profanity_filter: bool = False
    custom_vocabulary: Optional[List[str]] = None


class MultiLanguageService:
    """
    Service for multi-language support with automatic detection.
    """
    
    # Language-specific settings
    LANGUAGE_SETTINGS = {
        SupportedLanguage.ENGLISH: {
            "whisper_code": "en",
            "fast_mode": True,
            "default_model": "medium",
        },
        SupportedLanguage.SPANISH: {
            "whisper_code": "es",
            "fast_mode": True,
            "default_model": "medium",
        },
        SupportedLanguage.FRENCH: {
            "whisper_code": "fr",
            "fast_mode": True,
            "default_model": "medium",
        },
        SupportedLanguage.GERMAN: {
            "whisper_code": "de",
            "fast_mode": True,
            "default_model": "medium",
        },
        SupportedLanguage.CHINESE: {
            "whisper_code": "zh",
            "fast_mode": False,
            "default_model": "large",
        },
        SupportedLanguage.JAPANESE: {
            "whisper_code": "ja",
            "fast_mode": False,
            "default_model": "large",
        },
        SupportedLanguage.ARABIC: {
            "whisper_code": "ar",
            "fast_mode": False,
            "default_model": "large",
        },
    }
    
    # Font recommendations by language (for subtitles)
    FONT_RECOMMENDATIONS = {
        SupportedLanguage.ENGLISH: ["TikTokSans-Regular", "Arial", "Roboto"],
        SupportedLanguage.SPANISH: ["TikTokSans-Regular", "Arial", "Noto Sans"],
        SupportedLanguage.FRENCH: ["TikTokSans-Regular", "Arial", "Noto Sans"],
        SupportedLanguage.GERMAN: ["TikTokSans-Regular", "Arial", "Noto Sans"],
        SupportedLanguage.CHINESE: ["Noto Sans CJK SC", "SimHei", "Microsoft YaHei"],
        SupportedLanguage.JAPANESE: ["Noto Sans CJK JP", "Hiragino Kaku Gothic", "Meiryo"],
        SupportedLanguage.KOREAN: ["Noto Sans CJK KR", "Malgun Gothic", "Apple Gothic"],
        SupportedLanguage.ARABIC: ["Noto Sans Arabic", "Arial Unicode MS", "Scheherazade"],
        SupportedLanguage.HINDI: ["Noto Sans Devanagari", "Mangal", "Arial Unicode MS"],
        SupportedLanguage.RUSSIAN: ["Noto Sans", "Arial", "Roboto"],
    }
    
    def __init__(self):
        self._detection_cache: Dict[str, LanguageDetectionResult] = {}
    
    async def detect_language(
        self,
        audio_path: Optional[Path] = None,
        text_sample: Optional[str] = None,
        use_fast_heuristic: bool = True
    ) -> LanguageDetectionResult:
        """
        Detect language from audio or text sample.
        
        Priority:
        1. Audio-based detection (more accurate)
        2. Text-based detection (faster)
        3. Heuristic detection (fastest)
        """
        # If we have audio, use Whisper for detection
        if audio_path and audio_path.exists():
            return await self._detect_from_audio(audio_path)
        
        # If we have text, detect from text
        if text_sample and len(text_sample) > 10:
            return self._detect_from_text(text_sample)
        
        # Fallback to English
        return LanguageDetectionResult(
            detected_language=SupportedLanguage.ENGLISH,
            confidence=0.5,
            is_reliable=False,
            alternative_languages=[]
        )
    
    async def _detect_from_audio(self, audio_path: Path) -> LanguageDetectionResult:
        """Detect language using Whisper model."""
        try:
            from faster_whisper import WhisperModel
            
            # Load tiny model just for detection (fast)
            model = WhisperModel("tiny", device="cpu")
            
            segments, info = model.transcribe(
                str(audio_path),
                beam_size=1,
                language=None,  # Auto-detect
                task="transcribe"
            )
            
            # Get detected language
            detected_code = info.language
            confidence = info.language_probability
            
            lang = SupportedLanguage.from_code(detected_code)
            
            if lang:
                return LanguageDetectionResult(
                    detected_language=lang,
                    confidence=confidence,
                    is_reliable=confidence > 0.7,
                    alternative_languages=[]
                )
            
        except Exception as e:
            logger.warning(f"Audio language detection failed: {e}")
        
        # Fallback
        return await self.detect_language(text_sample="fallback")
    
    def _detect_from_text(self, text: str) -> LanguageDetectionResult:
        """Detect language from text using heuristics."""
        text = text.lower()
        
        # Character-based detection for non-Latin scripts
        scripts = {
            SupportedLanguage.CHINESE: (r'[\u4e00-\u9fff]', 0.3),
            SupportedLanguage.JAPANESE: (r'[\u3040-\u309f\u30a0-\u30ff]', 0.3),
            SupportedLanguage.KOREAN: (r'[\uac00-\ud7af]', 0.3),
            SupportedLanguage.ARABIC: (r'[\u0600-\u06ff]', 0.3),
            SupportedLanguage.HINDI: (r'[\u0900-\u097f]', 0.3),
            SupportedLanguage.RUSSIAN: (r'[\u0400-\u04ff]', 0.3),
        }
        
        import re
        
        for lang, (pattern, threshold) in scripts.items():
            matches = len(re.findall(pattern, text))
            ratio = matches / len(text) if text else 0
            
            if ratio > threshold:
                return LanguageDetectionResult(
                    detected_language=lang,
                    confidence=min(1.0, ratio * 2),
                    is_reliable=ratio > 0.5,
                    alternative_languages=[]
                )
        
        # Word-based detection for Latin scripts
        lang_markers = {
            SupportedLanguage.SPANISH: ['el', 'la', 'los', 'las', 'un', 'una', 'es', 'son', 'muy', 'está'],
            SupportedLanguage.FRENCH: ['le', 'la', 'les', 'un', 'une', 'est', 'sont', 'très', 'dans', 'sur'],
            SupportedLanguage.GERMAN: ['der', 'die', 'das', 'ein', 'eine', 'ist', 'sind', 'sehr', 'in', 'auf'],
            SupportedLanguage.ITALIAN: ['il', 'la', 'i', 'gli', 'un', 'una', 'è', 'sono', 'molto', 'in'],
            SupportedLanguage.PORTUGUESE: ['o', 'a', 'os', 'as', 'um', 'uma', 'é', 'são', 'muito', 'em'],
        }
        
        words = set(text.split())
        scores = {}
        
        for lang, markers in lang_markers.items():
            matches = sum(1 for m in markers if m in words)
            scores[lang] = matches / len(markers)
        
        if scores:
            best_lang = max(scores, key=scores.get)
            best_score = scores[best_lang]
            
            if best_score > 0.3:
                # Get alternatives
                alternatives = sorted(
                    [(l, s) for l, s in scores.items() if l != best_lang and s > 0.1],
                    key=lambda x: x[1],
                    reverse=True
                )[:2]
                
                return LanguageDetectionResult(
                    detected_language=best_lang,
                    confidence=best_score,
                    is_reliable=best_score > 0.5,
                    alternative_languages=alternatives
                )
        
        # Default to English
        return LanguageDetectionResult(
            detected_language=SupportedLanguage.ENGLISH,
            confidence=0.6,
            is_reliable=False,
            alternative_languages=[]
        )
    
    def get_transcription_config(
        self,
        language: SupportedLanguage,
        processing_mode: str = "balanced"
    ) -> TranscriptionConfig:
        """Get optimal transcription configuration for a language."""
        settings = self.LANGUAGE_SETTINGS.get(language, {})
        
        # Determine model size
        if processing_mode == "fast":
            model_size = "small"
        elif processing_mode == "quality":
            model_size = settings.get("default_model", "large")
        else:
            model_size = settings.get("default_model", "medium")
        
        return TranscriptionConfig(
            language=language,
            model_size=model_size,
            use_vad=True,
            word_timestamps=True
        )
    
    def get_font_for_language(
        self,
        language: SupportedLanguage,
        preference: str = "modern"
    ) -> str:
        """Get recommended font for a language."""
        fonts = self.FONT_RECOMMENDATIONS.get(language, ["Arial"])
        
        if preference == "modern" and len(fonts) > 0:
            return fonts[0]
        elif preference == "traditional" and len(fonts) > 1:
            return fonts[1]
        else:
            return fonts[-1]
    
    def get_subtitle_style(
        self,
        language: SupportedLanguage
    ) -> Dict[str, Any]:
        """Get subtitle style recommendations for a language."""
        base_style = {
            "font_size": 24,
            "position": "bottom",
            "max_width": 80,
            "word_highlight": True,
        }
        
        # Language-specific adjustments
        if language in [SupportedLanguage.CHINESE, SupportedLanguage.JAPANESE, SupportedLanguage.KOREAN]:
            # CJK languages need larger fonts
            base_style.update({
                "font_size": 28,
                "line_height": 1.5,
                "max_chars_per_line": 15,
            })
        elif language == SupportedLanguage.ARABIC:
            # Arabic needs RTL support
            base_style.update({
                "rtl": True,
                "text_align": "right",
            })
        elif language == SupportedLanguage.RUSSIAN:
            # Russian can be slightly larger
            base_style.update({
                "font_size": 26,
            })
        
        return base_style
    
    def translate_keywords(
        self,
        keywords: List[str],
        source_lang: SupportedLanguage,
        target_lang: SupportedLanguage
    ) -> Dict[str, str]:
        """Translate keywords for cross-language content."""
        # Simple dictionary-based translation for common keywords
        # In production, this would use a translation API
        
        basic_translations = {
            ("viral", SupportedLanguage.SPANISH): "viral",
            ("clip", SupportedLanguage.SPANISH): "clip",
            ("trend", SupportedLanguage.SPANISH): "tendencia",
            ("hook", SupportedLanguage.SPANISH): "gancho",
            ("engagement", SupportedLanguage.SPANISH): "interacción",
        }
        
        translations = {}
        for keyword in keywords:
            key = (keyword.lower(), target_lang)
            translations[keyword] = basic_translations.get(key, keyword)
        
        return translations


# Global instance
_language_service: Optional[MultiLanguageService] = None


def get_language_service() -> MultiLanguageService:
    """Get global multi-language service instance."""
    global _language_service
    if _language_service is None:
        _language_service = MultiLanguageService()
    return _language_service


async def detect_video_language(
    video_path: Optional[Path] = None,
    text_sample: Optional[str] = None
) -> LanguageDetectionResult:
    """
    Convenience function to detect language of video content.
    
    Args:
        video_path: Path to video file for audio-based detection
        text_sample: Text sample for text-based detection
    
    Returns:
        LanguageDetectionResult with detected language and confidence
    """
    service = get_language_service()
    return await service.detect_language(video_path, text_sample)


def get_optimal_transcription_settings(
    language_code: str,
    processing_mode: str = "balanced"
) -> Dict[str, Any]:
    """
    Get optimal settings for transcription.
    
    Args:
        language_code: ISO language code
        processing_mode: 'fast', 'balanced', or 'quality'
    
    Returns:
        Dict with transcription configuration
    """
    service = get_language_service()
    lang = SupportedLanguage.from_code(language_code) or SupportedLanguage.ENGLISH
    config = service.get_transcription_config(lang, processing_mode)
    
    return {
        "language_code": config.language.code,
        "model_size": config.model_size,
        "use_vad": config.use_vad,
        "word_timestamps": config.word_timestamps,
        "font": service.get_font_for_language(config.language),
        "subtitle_style": service.get_subtitle_style(config.language),
    }
