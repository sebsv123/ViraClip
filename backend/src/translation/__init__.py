"""
Local voice translation system for ViraClip.

Provides fully local (no external paid APIs) video voice translation:
  transcribe → translate → synthesize speech → mix into video.
"""

from .translator import translate_text, SUPPORTED_LANGUAGES, auto_detect_language
from .tts import synthesize_speech
from .pipeline import translate_video_audio

__all__ = [
    "translate_text",
    "SUPPORTED_LANGUAGES",
    "auto_detect_language",
    "synthesize_speech",
    "translate_video_audio",
]
