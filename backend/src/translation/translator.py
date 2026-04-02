"""
Local translation module using argostranslate.

Provides fully local text translation without external paid APIs.
Falls back gracefully when language packages are not installed.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Supported language codes and their human-readable names
SUPPORTED_LANGUAGES: dict[str, str] = {
    "es": "Spanish",
    "en": "English",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
    "ja": "Japanese",
}


def ensure_language_pair(source: str, target: str) -> bool:
    """
    Ensure the argostranslate package for *source* → *target* is installed.

    Downloads the package from the official Argos repository if it is missing.
    Returns True when the pair is available (already installed or freshly
    downloaded), False on failure.
    """
    try:
        import argostranslate.package as _pkg
        import argostranslate.translate as _tr

        # Fast path: pair is already available
        available = _tr.get_installed_languages()
        src_langs = [lg for lg in available if lg.code == source]
        tgt_langs = [lg for lg in available if lg.code == target]
        if src_langs and tgt_langs:
            for translation in src_langs[0].translations_to:
                if translation.to_lang.code == target:
                    return True

        # Need to download
        logger.info("Downloading argostranslate package %s→%s …", source, target)
        _pkg.update_package_index()
        available_packages = _pkg.get_available_packages()
        matching = [
            p
            for p in available_packages
            if p.from_code == source and p.to_code == target
        ]
        if not matching:
            logger.warning(
                "No argostranslate package found for %s→%s", source, target
            )
            return False
        _pkg.install_from_path(matching[0].download())
        logger.info("Installed argostranslate package %s→%s", source, target)
        return True
    except Exception as exc:
        logger.warning(
            "Could not ensure argostranslate pair %s→%s: %s", source, target, exc
        )
        return False


def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translate *text* from *source_lang* to *target_lang* using argostranslate.

    Behaviour:
    - Returns the original text unchanged when source == target.
    - Tries the direct pair first.
    - Falls back to pivot translation via English (source→en→target) if the
      direct pair is unavailable.
    - On any error returns the original text and logs a warning so the rest
      of the pipeline can continue gracefully.
    """
    if source_lang == target_lang:
        return text

    if not text or not text.strip():
        return text

    try:
        import argostranslate.translate as _tr

        def _do_translate(src: str, tgt: str, t: str) -> Optional[str]:
            available = _tr.get_installed_languages()
            src_langs = [lg for lg in available if lg.code == src]
            tgt_langs = [lg for lg in available if lg.code == tgt]
            if not src_langs or not tgt_langs:
                return None
            for translation in src_langs[0].translations_to:
                if translation.to_lang.code == tgt:
                    return translation.translate(t)
            return None

        # Try direct translation
        result = _do_translate(source_lang, target_lang, text)
        if result is not None:
            return result

        # Try downloading the pair, then retry
        if ensure_language_pair(source_lang, target_lang):
            result = _do_translate(source_lang, target_lang, text)
            if result is not None:
                return result

        # Pivot via English
        if source_lang != "en" and target_lang != "en":
            logger.info(
                "Direct pair %s→%s unavailable; pivoting via English",
                source_lang,
                target_lang,
            )
            en_text = translate_text(text, source_lang, "en")
            return translate_text(en_text, "en", target_lang)

        logger.warning(
            "argostranslate could not translate %s→%s — returning original text",
            source_lang,
            target_lang,
        )
        return text

    except Exception as exc:
        logger.warning(
            "Translation failed (%s→%s): %s — returning original text",
            source_lang,
            target_lang,
            exc,
        )
        return text


def auto_detect_language(text: str) -> str:
    """
    Detect the language of *text*.

    Uses *langdetect* if available; falls back to "en" on any error.
    """
    if not text or not text.strip():
        return "en"

    try:
        from langdetect import detect  # type: ignore[import-untyped]

        code = detect(text)
        return str(code) if code else "en"
    except Exception as exc:
        logger.debug("Language detection failed: %s — defaulting to 'en'", exc)
        return "en"
