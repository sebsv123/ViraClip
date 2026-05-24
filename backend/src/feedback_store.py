"""
feedback_store — Registro de feedback del selector de transiciones.

Cuando el usuario cambia manualmente una transición en el editor (P4),
se registra la corrección para análisis posterior. Nunca modifica el
comportamiento del selector directamente — solo recomienda ajustes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY = "feedback:transitions"
_REDIS_MAX_ENTRIES = 1000


def _transcript_hash(transcript: str) -> str:
    """Hash corto del transcript para no exponer datos completos."""
    return hashlib.md5(transcript.encode()).hexdigest()[:12]


async def record_transition_feedback(
    transcript: str,
    auto_choice: str,
    manual_choice: str,
    auto_scores: dict,
    redis_client: Any,
) -> None:
    """
    Registra una corrección manual del usuario en el selector de transiciones.

    Guarda en Redis lista ``feedback:transitions`` (LPUSH, máx 1000 entradas).

    Parameters
    ----------
    transcript : str
        Transcript del clip (solo se guarda el hash).
    auto_choice : str
        Transición que eligió el selector automático.
    manual_choice : str
        Transición que eligió el usuario manualmente.
    auto_scores : dict
        Scores del selector automático (del editor_config).
    redis_client : Any
        Cliente Redis asíncrono.
    """
    if redis_client is None:
        logger.debug("[Feedback] Redis no disponible, saltando registro")
        return

    entry = {
        "transcript_hash": _transcript_hash(transcript),
        "auto": auto_choice,
        "manual": manual_choice,
        "scores": auto_scores,
        "timestamp": time.time(),
    }

    try:
        await redis_client.lpush(_REDIS_KEY, json.dumps(entry))
        await redis_client.ltrim(_REDIS_KEY, 0, _REDIS_MAX_ENTRIES - 1)
        logger.debug(
            "[Feedback] Corrección registrada: %s → %s",
            auto_choice, manual_choice,
        )
    except Exception as exc:
        logger.warning("[Feedback] Error guardando en Redis: %s", exc)


async def get_transition_feedback_stats(redis_client: Any) -> dict:
    """
    Lee todas las entradas de feedback y devuelve estadísticas.

    Parameters
    ----------
    redis_client : Any
        Cliente Redis asíncrono.

    Returns
    -------
    dict
        ``{"total_corrections", "most_corrected", "correction_matrix",
           "override_rate"}``
    """
    if redis_client is None:
        return _empty_stats()

    try:
        raw_entries = await redis_client.lrange(_REDIS_KEY, 0, -1)
    except Exception as exc:
        logger.warning("[Feedback] Error leyendo de Redis: %s", exc)
        return _empty_stats()

    if not raw_entries:
        return _empty_stats()

    entries: list[dict] = []
    for raw in raw_entries:
        try:
            entries.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue

    total = len(entries)
    if total == 0:
        return _empty_stats()

    # Contar correcciones por auto_choice
    auto_counter: Counter = Counter()
    # Matriz de correcciones: "auto→manual" -> count
    matrix: Counter = Counter()

    for e in entries:
        auto = e.get("auto", "unknown")
        manual = e.get("manual", "unknown")
        if auto != manual:
            auto_counter[auto] += 1
            matrix[f"{auto}→{manual}"] += 1

    # Total de guardados (incluye los que no cambiaron)
    total_saves = total

    # Override rate
    total_overrides = sum(auto_counter.values())
    override_rate = round(total_overrides / total_saves, 3) if total_saves > 0 else 0.0

    # Más corregido
    most_corrected = None
    if auto_counter:
        most_common = auto_counter.most_common(1)[0]
        most_corrected = {
            "auto_choice": most_common[0],
            "count": most_common[1],
        }

    return {
        "total_corrections": total_overrides,
        "total_saves": total_saves,
        "most_corrected": most_corrected,
        "correction_matrix": dict(matrix.most_common(10)),
        "override_rate": override_rate,
    }


def _empty_stats() -> dict:
    return {
        "total_corrections": 0,
        "total_saves": 0,
        "most_corrected": None,
        "correction_matrix": {},
        "override_rate": 0.0,
    }


def adjust_selector_weights(
    scores: dict,
    feedback_stats: dict,
) -> dict:
    """
    Ajuste SIMPLE de pesos basado en feedback acumulado.

    NO cambia thresholds automáticamente — solo loggea recomendaciones.
    El ajuste automático es peligroso sin más datos.

    Parameters
    ----------
    scores : dict
        Scores actuales del selector (``{"match_cut": 0.71, ...}``).
    feedback_stats : dict
        Estadísticas de feedback (de ``get_transition_feedback_stats()``).

    Returns
    -------
    dict
        ``{"recommendations": [str, ...], "auto_adjusted": False}``
    """
    recommendations: list[str] = []
    matrix = feedback_stats.get("correction_matrix", {})

    # Analizar la matriz de correcciones
    for pair, count in matrix.items():
        if count < 5:
            continue  # Poco datos, no recomendar aún
        parts = pair.split("→")
        if len(parts) != 2:
            continue
        auto_type, manual_type = parts

        # Si un tipo X tiene >5 correcciones hacia Y, loggear recomendación
        recommendations.append(
            f"Considera bajar threshold de '{auto_type}' de "
            f"{scores.get(auto_type, 0.65):.2f} a "
            f"{min(scores.get(auto_type, 0.65) + 0.07, 0.95):.2f} "
            f"({count} correcciones hacia '{manual_type}')"
        )

    if recommendations:
        for rec in recommendations:
            logger.info("[Feedback] Recomendación de ajuste: %s", rec)

    return {
        "recommendations": recommendations,
        "auto_adjusted": False,
    }
