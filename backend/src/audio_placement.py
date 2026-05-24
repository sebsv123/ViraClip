"""
audio_placement — Detección y colocación de eventos de audio (SFX) en clips de vídeo.

Flujo:
  1. detect_audio_events(transcript, language) → lista de eventos con timestamp y tipo.
  2. apply_audio_events(clip_path, events, output_path) → vídeo con SFX incrustados.

La detección usa LLM (vía ai.py) para analizar el transcript y encontrar puntos
donde tiene sentido insertar efectos de sonido: palabras clave, cambios de tema,
énfasis del hablante, etc.

Los resultados se cachean en Redis (ttl=7200s) para evitar llamadas LLM repetidas.
"""

import hashlib
import json
import logging
import os
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .sfx_generator import (
    generate_dark_riser,
    generate_deep_boom,
    generate_magic_whoosh,
    generate_silence,
    generate_tension_riser,
)

logger = logging.getLogger(__name__)

# ── Cache ─────────────────────────────────────────────────────────────────────

_REDIS_AVAILABLE = False
try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore[assignment]

_REDIS_CLIENT: Any = None


async def _get_redis() -> Any:
    """Devuelve el cliente Redis compartido (singleton perezoso)."""
    global _REDIS_CLIENT
    if not _REDIS_AVAILABLE:
        return None
    if _REDIS_CLIENT is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        try:
            _REDIS_CLIENT = aioredis.from_url(redis_url, decode_responses=True)
        except Exception as exc:
            logger.warning("Redis no disponible, caché desactivada: %s", exc)
            return None
    return _REDIS_CLIENT


def _cache_key(transcript: str) -> str:
    """Clave de caché basada en los primeros 80 caracteres del transcript."""
    prefix = transcript[:80].strip().lower()
    h = hashlib.md5(prefix.encode()).hexdigest()[:12]
    return f"audio_events:{h}"


# ── Modelos ───────────────────────────────────────────────────────────────────

AUDIO_EVENT_TYPES = {
    "dark_riser": {"generator": generate_dark_riser, "default_duration": 2.0},
    "magic_whoosh": {"generator": generate_magic_whoosh, "default_duration": 0.45},
    "deep_boom": {"generator": generate_deep_boom, "default_duration": 0.8},
    "tension_riser": {"generator": generate_tension_riser, "default_duration": 3.0},
    "silence": {"generator": generate_silence, "default_duration": 0.5},
}

# Mapa de palabras clave → tipo de SFX
KEYWORD_SFX_MAP: dict[str, str] = {
    # Español
    "impacto": "deep_boom",
    "golpe": "deep_boom",
    "explosión": "deep_boom",
    "boom": "deep_boom",
    "sorpresa": "magic_whoosh",
    "increíble": "magic_whoosh",
    "wow": "magic_whoosh",
    "guau": "magic_whoosh",
    "misterio": "tension_riser",
    "secreto": "tension_riser",
    "revelación": "dark_riser",
    "descubrimiento": "dark_riser",
    "transformación": "dark_riser",
    # Inglés
    "impact": "deep_boom",
    "explosion": "deep_boom",
    "surprise": "magic_whoosh",
    "amazing": "magic_whoosh",
    "mystery": "tension_riser",
    "secret": "tension_riser",
    "reveal": "dark_riser",
    "discovery": "dark_riser",
    "transformation": "dark_riser",
}

# ── Detección de eventos ──────────────────────────────────────────────────────

# Variable compartida para rotar variantes de boom entre clips
boom_variant_counter: list[int] = [0]


async def detect_audio_events(
    transcript: str,
    language: str = "es",
    video_duration: float = 60.0,
) -> list[dict]:
    """
    Analiza el transcript con LLM para encontrar puntos donde insertar SFX.

    Estrategia:
      1. Busca palabras clave conocidas en el transcript (rápido, sin LLM).
      2. Usa LLM para detectar cambios de tema, afirmaciones contundentes,
         y momentos de énfasis.
      3. Combina y ordena los eventos por timestamp.
      4. Cachea el resultado en Redis (ttl=7200s).

    Returns
    -------
    list[dict]
        Cada dict con::
            {"timestamp": float, "type": str, "duration": float, "reason": str}
        Vacío si falla la detección.
    """
    # Intentar cache
    redis_conn = await _get_redis()
    if redis_conn:
        try:
            cached = await redis_conn.get(_cache_key(transcript))
            if cached:
                logger.info("[AUDIO_PLACEMENT] Eventos recuperados de caché Redis")
                return json.loads(cached)
        except Exception as exc:
            logger.debug("[AUDIO_PLACEMENT] Error leyendo caché: %s", exc)

    events: list[dict] = []

    # ── Fase 1: Palabras clave ──
    lines = transcript.split("\n")
    for line in lines:
        line_lower = line.lower().strip()
        if not line_lower:
            continue
        # Intentar extraer timestamp si está en formato [MM:SS] o MM:SS
        ts = _extract_timestamp(line)
        if ts is None:
            continue
        text = _strip_timestamp(line)
        for keyword, sfx_type in KEYWORD_SFX_MAP.items():
            if keyword in text.lower():
                duration = AUDIO_EVENT_TYPES[sfx_type]["default_duration"]
                events.append({
                    "timestamp": ts,
                    "type": sfx_type,
                    "duration": duration,
                    "reason": f"keyword:{keyword}",
                })
                break  # solo un SFX por línea

    # ── Fase 2: LLM para detección semántica ──
    try:
        llm_events = await _detect_events_via_llm(transcript, language, video_duration)
        events.extend(llm_events)
    except Exception as exc:
        logger.warning("[AUDIO_PLACEMENT] LLM detection failed: %s", exc)

    # Ordenar por timestamp
    events.sort(key=lambda e: e["timestamp"])

    # Fusionar eventos muy cercanos (< 0.5s)
    merged = _merge_nearby_events(events)

    # Cachear
    if redis_conn:
        try:
            await redis_conn.setex(_cache_key(transcript), 7200, json.dumps(merged))
        except Exception as exc:
            logger.debug("[AUDIO_PLACEMENT] Error escribiendo caché: %s", exc)

    logger.info(
        "[AUDIO_PLACEMENT] %d eventos detectados (%d tras fusión)",
        len(events), len(merged),
    )
    return merged


def _extract_timestamp(line: str) -> float | None:
    """Extrae timestamp en formato [MM:SS], [M:SS], MM:SS o SS del inicio de línea."""
    import re
    # [MM:SS] o [M:SS]
    m = re.match(r"\[?(\d{1,2}):(\d{2})\]?", line.strip())
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    # SS al inicio
    m = re.match(r"(\d+\.?\d*)\s", line.strip())
    if m:
        return float(m.group(1))
    return None


def _strip_timestamp(line: str) -> str:
    """Elimina el timestamp del inicio de la línea."""
    import re
    return re.sub(r"^\[?\d{1,2}:\d{2}\]?\s*", "", line).strip()


async def _detect_events_via_llm(
    transcript: str,
    language: str,
    video_duration: float,
) -> list[dict]:
    """
    Usa LLM para detectar eventos de audio basados en análisis semántico.

    Busca:
      - Cambios de tema (topic change) → dark_riser
      - Afirmaciones contundentes (strong statement) → deep_boom
      - Énfasis del hablante (emphasis) → magic_whoosh
      - Suspense / misterio → tension_riser
    """
    try:
        from .ai import get_most_relevant_parts_by_transcript

        segments = await get_most_relevant_parts_by_transcript(
            transcript=transcript,
            video_duration=video_duration,
            num_clips=5,
            language=language,
            min_score=0.3,
        )
    except Exception as exc:
        logger.warning("[AUDIO_PLACEMENT] LLM call failed: %s", exc)
        return []

    events: list[dict] = []
    for seg in segments:
        ts = _parse_timestamp_sec(seg.get("start_time", 0))
        text = str(seg.get("text", ""))
        reasoning = str(seg.get("reasoning", "")).lower()

        # Clasificar según el razonamiento del LLM
        if any(w in reasoning for w in ("suspense", "misterio", "tension", "mystery", "tension")):
            events.append({
                "timestamp": ts,
                "type": "tension_riser",
                "duration": 3.0,
                "reason": "llm:tension",
            })
        elif any(w in reasoning for w in ("revelación", "reveal", "descubrimiento", "discovery", "transformación", "transformation")):
            events.append({
                "timestamp": ts,
                "type": "dark_riser",
                "duration": 2.0,
                "reason": "llm:reveal",
            })
        elif any(w in reasoning for w in ("impacto", "impact", "contundente", "strong", "poderoso", "powerful")):
            events.append({
                "timestamp": ts,
                "type": "deep_boom",
                "duration": 0.8,
                "reason": "llm:impact",
            })
        elif any(w in reasoning for w in ("sorpresa", "surprise", "increíble", "amazing", "emphasis", "énfasis")):
            events.append({
                "timestamp": ts,
                "type": "magic_whoosh",
                "duration": 0.45,
                "reason": "llm:emphasis",
            })

    return events


def _parse_timestamp_sec(ts: Any) -> float:
    """Convierte timestamp a segundos."""
    if isinstance(ts, (int, float)):
        return float(ts)
    try:
        parts = str(ts).strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def _merge_nearby_events(events: list[dict], gap: float = 0.5) -> list[dict]:
    """
    Fusiona eventos que están a menos de `gap` segundos.
    El evento con mayor duración se queda; el otro se descarta.
    """
    if not events:
        return []
    merged = [events[0]]
    for ev in events[1:]:
        last = merged[-1]
        if abs(ev["timestamp"] - last["timestamp"]) < gap:
            # Quedarse con el de mayor duración
            if ev.get("duration", 0) > last.get("duration", 0):
                merged[-1] = ev
        else:
            merged.append(ev)
    return merged


# ── Aplicación de eventos ─────────────────────────────────────────────────────


async def apply_audio_events(
    clip_path: str,
    events: list[dict],
    output_path: str,
) -> str:
    """
    Aplica eventos de audio (SFX) a un clip de vídeo.

    Para cada evento, genera el SFX correspondiente y lo mezcla en el audio
    del vídeo en el timestamp indicado. Los SFX se generan con ffmpeg
    (sfx_generator.py) y se limpian tras su uso.

    Parameters
    ----------
    clip_path : str
        Ruta al vídeo de entrada.
    events : list[dict]
        Lista de eventos con timestamp, type, duration.
    output_path : str
        Ruta donde guardar el vídeo resultante.

    Returns
    -------
    str
        Ruta al vídeo con SFX, o la ruta original si falla.
    """
    if not events:
        logger.debug("[AUDIO_PLACEMENT] No hay eventos que aplicar")
        return clip_path

    temp_files: list[str] = []
    try:
        # Obtener duración del clip
        duration = _get_clip_duration(clip_path)
        if duration <= 0:
            logger.warning("[AUDIO_PLACEMENT] No se pudo obtener duración del clip")
            return clip_path

        # Generar todos los SFX
        sfx_paths: list[tuple[float, str]] = []  # (timestamp, ruta_sfx)
        for ev in events:
            ts = float(ev.get("timestamp", 0))
            if ts < 0 or ts >= duration:
                continue
            sfx_type = ev.get("type", "deep_boom")
            sfx_duration = float(ev.get("duration", 0.8))

            sfx_path = _generate_sfx(sfx_type, sfx_duration)
            if not sfx_path:
                continue
            temp_files.append(sfx_path)
            sfx_paths.append((ts, sfx_path))

        if not sfx_paths:
            logger.debug("[AUDIO_PLACEMENT] No se generó ningún SFX")
            return clip_path

        # Construir filtro FFmpeg para mezclar SFX en el audio original
        result_path = _mix_sfx_into_video(clip_path, sfx_paths, output_path, duration)
        if result_path:
            return result_path

        return clip_path

    except Exception as exc:
        logger.warning("[AUDIO_PLACEMENT] Error aplicando eventos: %s", exc)
        return clip_path
    finally:
        # Limpiar archivos temporales
        for fp in temp_files:
            try:
                Path(fp).unlink(missing_ok=True)
            except Exception:
                pass


def _get_clip_duration(clip_path: str) -> float:
    """Obtiene la duración en segundos de un clip usando ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            clip_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
        return 0.0
    except Exception as exc:
        logger.warning("Error obteniendo duración: %s", exc)
        return 0.0


def _generate_sfx(sfx_type: str, duration: float) -> str:
    """Genera un archivo SFX usando sfx_generator."""
    global boom_variant_counter

    if sfx_type == "dark_riser":
        return generate_dark_riser(duration=duration)
    elif sfx_type == "magic_whoosh":
        variant = hash(str(duration)) % 3
        return generate_magic_whoosh(variant=variant)
    elif sfx_type == "deep_boom":
        variant = boom_variant_counter[0] % 4
        boom_variant_counter[0] += 1
        return generate_deep_boom(variant=variant)
    elif sfx_type == "tension_riser":
        return generate_tension_riser(duration=duration)
    elif sfx_type == "silence":
        return generate_silence(duration_ms=int(duration * 1000))
    else:
        logger.warning("Tipo SFX desconocido: %s", sfx_type)
        return ""


def _mix_sfx_into_video(
    clip_path: str,
    sfx_paths: list[tuple[float, str]],
    output_path: str,
    clip_duration: float,
) -> str | None:
    """
    Mezcla múltiples SFX en el audio de un vídeo usando FFmpeg.

    Construye un filter_complex que:
      1. Extrae el audio del vídeo original.
      2. Para cada SFX, lo coloca en su timestamp con adelay.
      3. Mezcla todo con amix.
      4. Reemplaza el audio del vídeo original.
    """
    try:
        filter_parts: list[str] = []
        input_labels: list[str] = []
        stream_index = 0

        # Audio original
        filter_parts.append(f"[0:a]acopy[a{stream_index}]")
        input_labels.append(f"[a{stream_index}]")
        stream_index += 1

        # Cada SFX con adelay
        for ts, sfx_path in sfx_paths:
            delay_ms = int(ts * 1000)
            label_in = f"s{stream_index}"
            label_delayed = f"d{stream_index}"
            filter_parts.append(
                f"[1:{stream_index - 1}]adelay={delay_ms}|{delay_ms}[{label_delayed}]"
            )
            input_labels.append(f"[{label_delayed}]")
            stream_index += 1

        # Mezcla
        inputs_str = "".join(input_labels)
        filter_parts.append(f"{inputs_str}amix=inputs={len(input_labels)}:duration=first[aout]")

        filter_complex = ";".join(filter_parts)

        # Inputs: vídeo + todos los SFX
        inputs = ["-i", clip_path]
        for _, sfx_path in sfx_paths:
            inputs.extend(["-i", sfx_path])

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(
                "[AUDIO_PLACEMENT] FFmpeg mix falló: %s",
                result.stderr[:500],
            )
            return None

        if Path(output_path).exists():
            logger.info(
                "[AUDIO_PLACEMENT] %d SFX mezclados en %s",
                len(sfx_paths), Path(output_path).name,
            )
            return output_path

        return None

    except Exception as exc:
        logger.warning("[AUDIO_PLACEMENT] mix_sfx_into_video falló: %s", exc)
        return None
