"""
keyword_extractor — Extracción de keywords visualizables desde el transcript
para superponer iconos (IconScout) en los clips de vídeo.

Flujo:
  1. extract_visual_keywords(transcript, llm_client, redis_client) → lista de keywords
  2. resolve_icon_for_keyword(keyword_data, redis_client) → URL de icono o None

Cache:
  - Resultados del LLM se cachean en Redis (ttl=7200s)
  - URLs de iconos se cachean en Redis (ttl=86400s)
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Cache helpers ──────────────────────────────────────────────────────────────

_KEYWORDS_CACHE_TTL = 7200
_ICON_CACHE_TTL = 86400


def _kw_cache_key(transcript: str) -> str:
    """Clave de caché basada en los primeros 100 caracteres del transcript."""
    prefix = transcript[:100].strip().lower()
    h = hashlib.md5(prefix.encode()).hexdigest()[:12]
    return f"kw:{h}"


def _icon_cache_key(word: str) -> str:
    """Clave de caché para un icono de una palabra."""
    return f"icon:{word.strip().lower()}"


# ── Prompt template ───────────────────────────────────────────────────────────

_KEYWORD_PROMPT_TEMPLATE = (
    "Eres un editor de vídeo para contenido de seguros en español.\n"
    "Del siguiente fragmento de transcript, identifica MÁXIMO {max_keywords} "
    "palabras o conceptos que:\n"
    "1. Tengan representación visual concreta (un objeto, persona, acción)\n"
    "2. Sean relevantes para seguros (familia, hogar, coche, salud, dinero,\n"
    "   contrato, protección, médico, accidente, ahorro, pago, documento)\n"
    "3. No sean palabras genéricas como: 'esto', 'algo', 'mucho', 'hay', 'muy'\n\n"
    "Responde SOLO con JSON: [{{\"word\": \"familia\", \"confidence\": 0.9}}, ...]\n"
    "Si no hay palabras visualizables relevantes, responde: []\n\n"
    "Transcript: {transcript}"
)


# ── Public API ────────────────────────────────────────────────────────────────


async def extract_visual_keywords(
    transcript: str,
    llm_client: Any,
    redis_client: Any,
    max_keywords: int = 3,
) -> list[dict]:
    """
    Extrae las palabras del transcript que tienen representación visual
    concreta y son relevantes para seguros.

    Parameters
    ----------
    transcript : str
        Texto del transcript del clip.
    llm_client : Any
        Cliente LLM con método ``generate(prompt: str) -> str``.
    redis_client : Any
        Cliente Redis (opcional, puede ser ``None``).
    max_keywords : int
        Máximo de keywords a devolver (default 3).

    Returns
    -------
    list[dict]
        Lista de dicts con::
            {"word": str, "timestamp_hint": float | None, "confidence": float}
        Ordenado por confidence DESC. Vacío si no se encuentran keywords.
    """
    if not transcript or not transcript.strip():
        return []

    # Intentar cache
    if redis_client is not None:
        try:
            cached = await redis_client.get(_kw_cache_key(transcript))
            if cached:
                logger.debug("[KW] Keywords recuperados de caché Redis")
                return json.loads(cached)
        except Exception as exc:
            logger.debug("[KW] Error leyendo caché Redis: %s", exc)

    # Llamar al LLM
    try:
        prompt = _KEYWORD_PROMPT_TEMPLATE.format(
            max_keywords=max_keywords,
            transcript=transcript,
        )
        response = await llm_client.generate(prompt)
        keywords = _parse_llm_response(response, max_keywords)
    except Exception as exc:
        logger.warning("[KW] LLM falló: %s", exc)
        return []

    # Filtrar confidence < 0.6
    keywords = [kw for kw in keywords if kw.get("confidence", 0) >= 0.6]

    # Calcular timestamp_hint para cada keyword
    clip_duration = _estimate_clip_duration(transcript)
    for kw in keywords:
        kw["timestamp_hint"] = _find_timestamp_hint(
            kw["word"], transcript, clip_duration,
        )

    # Ordenar por confidence DESC y limitar
    keywords.sort(key=lambda k: k.get("confidence", 0), reverse=True)
    keywords = keywords[:max_keywords]

    # Cachear
    if redis_client is not None:
        try:
            await redis_client.setex(
                _kw_cache_key(transcript),
                _KEYWORDS_CACHE_TTL,
                json.dumps(keywords),
            )
        except Exception as exc:
            logger.debug("[KW] Error escribiendo caché Redis: %s", exc)

    logger.info("[KW] %d keywords extraídas del transcript", len(keywords))
    return keywords


async def resolve_icon_for_keyword(
    keyword_data: dict,
    redis_client: Any,
) -> dict | None:
    """
    Busca un icono para la keyword usando fetch_iconscout_asset.

    Parameters
    ----------
    keyword_data : dict
        Dict con al menos ``{"word": str, ...}``.
    redis_client : Any
        Cliente Redis para cachear URLs de iconos.

    Returns
    -------
    dict | None
        Dict con::
            {"word": str, "icon_url": str, "icon_type": "3d"|"png",
             "timestamp_hint": float | None, "confidence": float}
        o ``None`` si no se encontró icono.
    """
    word = keyword_data.get("word", "").strip().lower()
    if not word:
        return None

    # Intentar cache de icono
    if redis_client is not None:
        try:
            cached = await redis_client.get(_icon_cache_key(word))
            if cached:
                logger.debug("[KW] Icono recuperado de caché para '%s'", word)
                data = json.loads(cached)
                if data.get("icon_url"):
                    return {**keyword_data, **data}
        except Exception as exc:
            logger.debug("[KW] Error leyendo caché de icono: %s", exc)

    # Llamar a fetch_iconscout_asset
    try:
        from .clip_editor import fetch_iconscout_asset

        result = await fetch_iconscout_asset(keyword=word)
        if result and result.get("url"):
            icon_data = {
                "icon_url": result["url"],
                "icon_type": result.get("type", "png"),
            }
            # Cachear
            if redis_client is not None:
                try:
                    await redis_client.setex(
                        _icon_cache_key(word),
                        _ICON_CACHE_TTL,
                        json.dumps(icon_data),
                    )
                except Exception as exc:
                    logger.debug("[KW] Error cacheando icono: %s", exc)

            return {**keyword_data, **icon_data}

        logger.debug("[KW] No se encontró icono para '%s'", word)
        return None

    except Exception as exc:
        logger.warning("[KW] fetch_iconscout_asset falló para '%s': %s", word, exc)
        return None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _parse_llm_response(response: str, max_keywords: int) -> list[dict]:
    """
    Parsea la respuesta JSON del LLM.

    Devuelve lista de dicts con ``word`` y ``confidence``.
    Si el JSON es inválido, devuelve [] y loggea una advertencia.
    """
    if not response or not response.strip():
        return []

    # Intentar extraer JSON de la respuesta (puede venir con markdown)
    text = response.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()

    try:
        data = json.loads(text)
        if not isinstance(data, list):
            logger.warning("[KW] Respuesta LLM no es una lista: %s", type(data))
            return []
        # Validar cada elemento
        result = []
        for item in data:
            if isinstance(item, dict) and "word" in item:
                result.append({
                    "word": str(item["word"]).strip(),
                    "confidence": float(item.get("confidence", 0.5)),
                })
        return result[:max_keywords]
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        logger.warning("[KW] Error parseando respuesta LLM: %s — respuesta: %s", exc, text[:200])
        return []


def _find_timestamp_hint(word: str, transcript: str, clip_duration: float) -> float | None:
    """
    Busca la posición aproximada de la palabra en el transcript
    y la convierte a timestamp en segundos.

    Returns
    -------
    float | None
        Timestamp en segundos, o ``None`` si no se encuentra la palabra.
    """
    word_lower = word.lower()
    transcript_lower = transcript.lower()
    idx = transcript_lower.find(word_lower)
    if idx < 0:
        return None
    ratio = idx / max(len(transcript), 1)
    return ratio * clip_duration


def _estimate_clip_duration(transcript: str) -> float:
    """
    Estima la duración del clip basado en la longitud del transcript.
    Aproximación: ~150 palabras por minuto.
    """
    word_count = len(transcript.split())
    return max(5.0, (word_count / 150) * 60)
