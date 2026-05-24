"""
subtitle_resync — Resincronización de subtítulos tras cortes de audio.

Cuando audio_placement.py inserta silencios (60-120ms) en el timeline,
los timestamps de subtítulos se desfasan. Este módulo recalcula los
timestamps para mantener sincronía.

Funciones puras — sin efectos secundarios, fáciles de testear.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def apply_silence_offsets(
    subtitle_events: list[dict],
    silence_insertions: list[dict],
) -> list[dict]:
    """
    Recalcula timestamps de subtítulos después de insertar silencios.

    Por cada silencio insertado en ``time`` con ``duration_ms``:
      Todos los subtítulos con ``start >= time`` se desplazan
      ``+duration_ms/1000`` segundos.

    Parameters
    ----------
    subtitle_events : list[dict]
        Lista de subtítulos con ``{"start": float, "end": float, "text": str, ...}``.
    silence_insertions : list[dict]
        Lista de silencios insertados, ordenados por ``time`` ASC.
        Cada dict: ``{"time": float, "duration_ms": int}``.

    Returns
    -------
    list[dict]
        Nueva lista con timestamps corregidos.
    """
    if not silence_insertions:
        return list(subtitle_events)

    # Ordenar silencios por time ASC por si acaso
    sorted_silences = sorted(silence_insertions, key=lambda s: s.get("time", 0))

    corrected: list[dict] = []
    for sub in subtitle_events:
        start = float(sub.get("start", 0))
        end = float(sub.get("end", start + 0.5))
        cumulative_offset = 0.0

        for silence in sorted_silences:
            silence_time = float(silence.get("time", 0))
            offset = float(silence.get("duration_ms", 0)) / 1000.0
            if silence_time <= start:
                cumulative_offset += offset

        corrected.append({
            **sub,
            "start": round(start + cumulative_offset, 3),
            "end": round(end + cumulative_offset, 3),
        })

    return corrected


def apply_cut_offsets(
    subtitle_events: list[dict],
    cuts: list[float],
) -> list[dict]:
    """
    Elimina subtítulos que caen en frames cortados y recalcula offsets.

    Cuando hay silence removal o trim de segmentos, los subtítulos que
    caen dentro de un corte se eliminan. Los subtítulos después del corte
    se desplazan hacia atrás.

    Parameters
    ----------
    subtitle_events : list[dict]
        Lista de subtítulos con ``{"start": float, "end": float, "text": str}``.
    cuts : list[float]
        Tiempos de corte en el timeline original (segundos), ordenados ASC.

    Returns
    -------
    list[dict]
        Subtítulos filtrados y con timestamps corregidos.
    """
    if not cuts:
        return list(subtitle_events)

    sorted_cuts = sorted(cuts)
    corrected: list[dict] = []

    for sub in subtitle_events:
        start = float(sub.get("start", 0))
        end = float(sub.get("end", start + 0.5))

        # Calcular cuánto corte hay antes de este subtítulo
        total_cut_before = 0.0
        for cut in sorted_cuts:
            if cut <= start:
                total_cut_before += cut  # aproximación: cada corte elimina ese punto
            else:
                break

        # Verificar si el subtítulo cae dentro de un corte
        # (simplificación: si start está cerca de un corte, se elimina)
        is_cut = any(abs(start - c) < 0.1 for c in sorted_cuts)

        if is_cut:
            continue  # eliminar subtítulo

        corrected.append({
            **sub,
            "start": round(start - total_cut_before, 3),
            "end": round(end - total_cut_before, 3),
        })

    return corrected


def extract_silence_insertions(sfx_events: list[dict]) -> list[dict]:
    """
    Extrae la lista de silencios insertados desde los eventos SFX.

    Los eventos de tipo ``"pre_silence"`` y ``"post_silence"`` representan
    silencios insertados en el timeline de audio.

    Parameters
    ----------
    sfx_events : list[dict]
        Lista de eventos SFX (como los que devuelve ``detect_audio_events``).

    Returns
    -------
    list[dict]
        Lista de silencios: ``[{"time": float, "duration_ms": int}, ...]``
    """
    insertions: list[dict] = []
    for ev in sfx_events:
        sfx_type = ev.get("type", "")
        if sfx_type in ("pre_silence", "post_silence"):
            insertions.append({
                "time": float(ev.get("timestamp", 0)),
                "duration_ms": int(ev.get("duration", 0.5) * 1000),
            })
    return insertions
