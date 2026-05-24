"""
Generador sintético de assets de audio usando FFmpeg (sin librosa/pydub/numpy).

Todas las funciones generan archivos WAV mono 44100 Hz mediante subprocess ffmpeg.
Los archivos temporales se crean en /tmp/sfx_{uuid}.wav y deben limpiarse tras su uso.
Volúmenes calibrados para evitar clipping al mezclar:
  - risers ≤ 0.35
  - whoosh ≤ 0.45
  - boom ≤ 0.5
  - tension ≤ 0.25
"""

import logging
import subprocess
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
#  Risers oscuros (crecimiento lento, grave→agudo)
# ──────────────────────────────────────────────


def generate_dark_riser(duration: float = 2.0, output_path: str | None = None) -> str:
    """
    Genera un riser oscuro de 'duration' segundos.

    Capas:
      1. Sub-graves: sin(50 Hz) con amplitud creciente t/duration, filtro bandpass 70 Hz.
      2. Agudos: sin(7 kHz) con amplitud creciente t/duration, bandpass 6.5 kHz.
    Mezcla con amix, normaliza volumen a 0.35.

    Returns
    -------
    str
        Ruta al archivo WAV generado, o cadena vacía si falla.
    """
    out = output_path or f"/tmp/sfx_{uuid.uuid4().hex}.wav"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-filter_complex",
            (
                # Capa grave: 50 Hz con fade-in lineal
                "aevalsrc=0.6*sin(2*PI*50*t)*t/"
                f"{duration}:duration={duration}:rate=44100"
                ",bandpass=f=70:width_type=o:w=2"
                f"[low];"
                # Capa aguda: 7 kHz con fade-in lineal
                "aevalsrc=0.25*sin(2*PI*7000*t)*t/"
                f"{duration}:duration={duration}:rate=44100"
                ",bandpass=f=6500:width_type=o:w=1.5"
                f"[high];"
                # Mezcla
                "[low][high]amix=inputs=2:duration=first"
                ",volume=0.35"
                f"[out]"
            ),
            "-map", "[out]",
            "-ac", "1",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.debug("dark_riser generado → %s (%.1fs)", out, duration)
        return out
    except Exception as exc:
        logger.warning("generate_dark_riser falló: %s", exc)
        return ""


# ──────────────────────────────────────────────
#  Whoosh mágico (descenso de frecuencia)
# ──────────────────────────────────────────────


def generate_magic_whoosh(variant: int = 0, output_path: str | None = None) -> str:
    """
    Genera un whoosh corto tipo "magia".

    Variants (duración):
      0 → 0.3 s
      1 → 0.45 s
      2 → 0.6 s

    Señal: sin(2*PI*(2500-2200*t/dur)*t) con highpass 300 Hz.
    Volumen final: 0.45.

    Returns
    -------
    str
        Ruta al archivo WAV generado, o cadena vacía si falla.
    """
    durations = [0.3, 0.45, 0.6]
    dur = durations[variant] if 0 <= variant < len(durations) else 0.45
    out = output_path or f"/tmp/sfx_{uuid.uuid4().hex}.wav"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-filter_complex",
            (
                f"aevalsrc=0.5*sin(2*PI*(2500-2200*t/{dur})*t)"
                f":duration={dur}:rate=44100"
                ",highpass=f=300"
                ",volume=0.45"
                "[out]"
            ),
            "-map", "[out]",
            "-ac", "1",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.debug("magic_whoosh(variant=%d) generado → %s", variant, out)
        return out
    except Exception as exc:
        logger.warning("generate_magic_whoosh falló: %s", exc)
        return ""


# ──────────────────────────────────────────────
#  Golpe grave (deep boom)
# ──────────────────────────────────────────────


def generate_deep_boom(variant: int = 0, output_path: str | None = None) -> str:
    """
    Genera un golpe grave (boom) de corta duración.

    Variants:
      0 → 45 Hz, 0.8 s, volumen 0.5
      1 → 60 Hz, 0.5 s, volumen 0.5
      2 → 35 Hz, 1.2 s, volumen 0.5
      3 → Doble frecuencia: 45 Hz + 75 Hz mezclados, 0.8 s, volumen 0.5

    Returns
    -------
    str
        Ruta al archivo WAV generado, o cadena vacía si falla.
    """
    params = [(45, 0.8), (60, 0.5), (35, 1.2), None]
    if variant < 0 or variant >= len(params):
        variant = 0

    out = output_path or f"/tmp/sfx_{uuid.uuid4().hex}.wav"
    try:
        if variant == 3:
            # Doble frecuencia: mezcla de 45 Hz + 75 Hz
            freq_a, freq_b = 45, 75
            dur = 0.8
            cmd = [
                "ffmpeg", "-y",
                "-filter_complex",
                (
                    f"aevalsrc=0.5*sin(2*PI*{freq_a}*t)*exp(-3*t/{dur})"
                    f":duration={dur}:rate=44100"
                    f"[a];"
                    f"aevalsrc=0.3*sin(2*PI*{freq_b}*t)*exp(-3*t/{dur})"
                    f":duration={dur}:rate=44100"
                    f"[b];"
                    "[a][b]amix=inputs=2:duration=first"
                    ",volume=0.5"
                    "[out]"
                ),
                "-map", "[out]",
                "-ac", "1",
                out,
            ]
        else:
            freq, dur = params[variant]
            cmd = [
                "ffmpeg", "-y",
                "-filter_complex",
                (
                    f"aevalsrc=0.8*sin(2*PI*{freq}*t)*exp(-3*t/{dur})"
                    f":duration={dur}:rate=44100"
                    ",volume=0.5"
                    "[out]"
                ),
                "-map", "[out]",
                "-ac", "1",
                out,
            ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.debug("deep_boom(variant=%d) generado → %s", variant, out)
        return out
    except Exception as exc:
        logger.warning("generate_deep_boom falló: %s", exc)
        return ""


# ──────────────────────────────────────────────
#  Riser de tensión (textura granular)
# ──────────────────────────────────────────────


def generate_tension_riser(duration: float = 3.0, output_path: str | None = None) -> str:
    """
    Genera un riser de tensión con textura granular.

    Capas:
      1. Sub: sin(20→35 Hz) con fade-in, lowpass 120 Hz.
      2. Mid: ruido blanco (random) con bandpass 450 Hz, volumen 0.12.
    Mezcla, volumen final 0.25.

    Returns
    -------
    str
        Ruta al archivo WAV generado, o cadena vacía si falla.
    """
    out = output_path or f"/tmp/sfx_{uuid.uuid4().hex}.wav"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-filter_complex",
            (
                # Sub: frecuencia ascendente 20→35 Hz con fade-in
                "aevalsrc=0.5*sin(2*PI*(20+15*t/"
                f"{duration})*t)*t/{duration}"
                f":duration={duration}:rate=44100"
                ",lowpass=f=120"
                f"[sub];"
                # Mid: ruido blanco filtrado
                f"aevalsrc=random(0):duration={duration}:rate=44100"
                ",bandpass=f=450:width_type=h:w=600"
                ",volume=0.12"
                f"[mid];"
                # Mezcla
                "[sub][mid]amix=inputs=2:duration=first"
                ",volume=0.25"
                "[out]"
            ),
            "-map", "[out]",
            "-ac", "1",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.debug("tension_riser generado → %s (%.1fs)", out, duration)
        return out
    except Exception as exc:
        logger.warning("generate_tension_riser falló: %s", exc)
        return ""


# ──────────────────────────────────────────────
#  Silencio
# ──────────────────────────────────────────────


def generate_silence(duration_ms: int = 500, output_path: str | None = None) -> str:
    """
    Genera un archivo de silencio de 'duration_ms' milisegundos.

    Returns
    -------
    str
        Ruta al archivo WAV generado, o cadena vacía si falla.
    """
    dur_sec = duration_ms / 1000.0
    out = output_path or f"/tmp/sfx_{uuid.uuid4().hex}.wav"
    try:
        cmd = [
            "ffmpeg", "-y",
            "-filter_complex",
            f"aevalsrc=0:duration={dur_sec}:rate=44100[out]",
            "-map", "[out]",
            "-ac", "1",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.debug("silencio generado → %s (%dms)", out, duration_ms)
        return out
    except Exception as exc:
        logger.warning("generate_silence falló: %s", exc)
        return ""
