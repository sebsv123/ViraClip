"""
metrics — Métricas de rendimiento por efecto (transiciones, audio, etc.).

Almacena las últimas 100 mediciones por efecto en memoria y opcionalmente
en Redis (LPUSH) para persistencia. No importa nada del dominio — es una
utilidad pura.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from functools import wraps
from typing import Any, AsyncGenerator, Callable

logger = logging.getLogger(__name__)

# Umbrales de timeout por efecto (segundos)
TIMEOUT_THRESHOLDS: dict[str, float] = {
    "match_cut": 5.0,
    "glitch": 8.0,
    "sweep_mask": 6.0,
    "mask_reveal": 12.0,
    "shape_morph": 45.0,  # SAM es lento
    "dark_riser": 3.0,
    "magic_whoosh": 2.0,
    "deep_boom": 2.0,
    "tension_riser": 3.0,
    "keyword_extraction": 8.0,
    "icon_fetch": 5.0,
}

# Almacén en memoria: effect_name -> [duration_seconds, ...]
_metrics: dict[str, list[float]] = defaultdict(list)
_MAX_SAMPLES = 100

_REDIS_KEY = "metrics:effect_timings"
_REDIS_MAX_ENTRIES = 1000


def record_effect_timing(
    effect_name: str,
    duration_seconds: float,
    redis_client: Any = None,
) -> None:
    """
    Registra el tiempo de render de un efecto.

    Guarda las últimas 100 mediciones en memoria. Si hay cliente Redis,
    también hace LPUSH para persistencia (máx 1000 entradas).

    Parameters
    ----------
    effect_name : str
        Nombre del efecto (ej. ``"match_cut"``, ``"deep_boom"``).
    duration_seconds : float
        Duración en segundos.
    redis_client : Any, optional
        Cliente Redis asíncrono (opcional).
    """
    # Memoria
    samples = _metrics[effect_name]
    samples.append(duration_seconds)
    if len(samples) > _MAX_SAMPLES:
        samples.pop(0)

    # Redis (best-effort)
    if redis_client is not None:
        try:
            import asyncio

            entry = json.dumps({
                "effect": effect_name,
                "duration": round(duration_seconds, 3),
                "ts": time.time(),
            })
            # Usar event loop existente o crear uno nuevo
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(
                        _redis_lpush(redis_client, entry)
                    )
                else:
                    loop.run_until_complete(
                        _redis_lpush(redis_client, entry)
                    )
            except RuntimeError:
                pass
        except Exception as exc:
            logger.debug("[Metrics] Redis push falló: %s", exc)

    # Log si supera el umbral
    threshold = TIMEOUT_THRESHOLDS.get(effect_name, 30.0)
    if duration_seconds > threshold:
        logger.warning(
            "SLOW_EFFECT: %s tardó %.2fs (umbral: %.1fs)",
            effect_name, duration_seconds, threshold,
        )


async def _redis_lpush(redis_client: Any, entry: str) -> None:
    """Hace LPUSH + LTRIM en Redis."""
    try:
        await redis_client.lpush(_REDIS_KEY, entry)
        await redis_client.ltrim(_REDIS_KEY, 0, _REDIS_MAX_ENTRIES - 1)
    except Exception:
        pass


def get_effect_stats(effect_name: str) -> dict:
    """
    Devuelve estadísticas de un efecto.

    Returns
    -------
    dict
        ``{"effect", "p50_ms", "p95_ms", "p99_ms", "count", "avg_ms", "slow_count"}``
    """
    samples = _metrics.get(effect_name, [])
    if not samples:
        return {
            "effect": effect_name,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "count": 0,
            "avg_ms": 0.0,
            "slow_count": 0,
        }

    sorted_samples = sorted(samples)
    n = len(sorted_samples)
    threshold = TIMEOUT_THRESHOLDS.get(effect_name, 30.0)

    def percentile(p: float) -> float:
        idx = max(0, min(n - 1, int(n * p / 100)))
        return sorted_samples[idx] * 1000  # convertir a ms

    return {
        "effect": effect_name,
        "p50_ms": round(percentile(50), 1),
        "p95_ms": round(percentile(95), 1),
        "p99_ms": round(percentile(99), 1),
        "count": n,
        "avg_ms": round((sum(sorted_samples) / n) * 1000, 1),
        "slow_count": sum(1 for s in samples if s > threshold),
    }


def get_all_effects_stats() -> dict[str, dict]:
    """
    Devuelve estadísticas de todos los efectos registrados.

    Returns
    -------
    dict
        ``{"match_cut": {...}, "glitch": {...}, ...}``
    """
    return {
        name: get_effect_stats(name)
        for name in sorted(_metrics.keys())
    }


@asynccontextmanager
async def measure_effect(
    effect_name: str,
    redis_client: Any = None,
) -> AsyncGenerator[None, None]:
    """
    Context manager async para medir el tiempo de un efecto.

    Uso::

        async with measure_effect("match_cut", redis_client):
            resultado = await match_cut_transition(...)

    Parameters
    ----------
    effect_name : str
        Nombre del efecto.
    redis_client : Any, optional
        Cliente Redis opcional.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        record_effect_timing(effect_name, elapsed, redis_client)


def measure_sync(effect_name: str, redis_client: Any = None) -> Callable:
    """
    Decorador síncrono para medir el tiempo de una función.

    Uso::

        @measure_sync("match_cut")
        def apply_match_cut(...):
            ...

    Parameters
    ----------
    effect_name : str
        Nombre del efecto.
    redis_client : Any, optional
        Cliente Redis opcional.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - start
                record_effect_timing(effect_name, elapsed, redis_client)
        return wrapper
    return decorator
