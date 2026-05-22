"""
B-Roll Effects Engine — Efectos Cinematográficos Curados
=========================================================

Solo 5 efectos probados y estables para B-rolls virales:
  1. Ken Burns In   — zoom suave 1.0 → 1.08 (entrada, ease-in-out)
  2. Ken Burns Out  — zoom suave 1.08 → 1.0 (reveal, ease-in-out)
  3. Pan Right      — desplazamiento horizontal derecha (z=1.08, ease-in-out)
  4. Pan Left       — desplazamiento horizontal izquierda (z=1.08, ease-in-out)
  5. Pan Up         — desplazamiento vertical arriba (z=1.08, ease-in-out)

Reglas:
  - Máximo UN efecto por B-roll
  - Zoom máximo 1.08 (nunca más)
  - Duración mínima de movimiento de cámara >= 0.6s
  - Easing ease-in-out (no lineal)
  - Sin flashes, sin rotaciones, sin efectos que marean
  - Alterna entre efectos para no repetir
"""
from __future__ import annotations

import logging
import math
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
MAX_ZOOM = 1.08          # Capa máxima de zoom (antes 1.10 / 1.12)
MIN_DURATION_S = 0.6     # Duración mínima de cualquier movimiento de cámara
FPS = 30                 # Frames por segundo para cálculos


class BrollEffectType(str, Enum):
    """5 efectos curados y estables para B-roll viral."""
    KEN_BURNS_IN  = "ken_burns_in"   # Zoom 1.0 → 1.08 (ease-in-out)
    KEN_BURNS_OUT = "ken_burns_out"  # Zoom 1.08 → 1.0 (ease-in-out)
    PAN_RIGHT     = "pan_right"      # Desplazamiento izquierda→derecha (z=1.08)
    PAN_LEFT      = "pan_left"       # Desplazamiento derecha→izquierda (z=1.08)
    PAN_UP        = "pan_up"         # Desplazamiento abajo→arriba (z=1.08)


class BrollEffectsEngine:
    """
    Motor de efectos inteligente para B-rolls.
    Rota efectos automáticamente para evitar repetición.
    """

    def __init__(self):
        self._effect_history: list[BrollEffectType] = []
        self._max_history = 5

        # Secuencia preferida — alterna zoom y pan de forma natural
        # El orden importa: nunca dos zooms seguidos, nunca dos pans iguales
        self._preferred_sequence = [
            BrollEffectType.KEN_BURNS_IN,
            BrollEffectType.PAN_RIGHT,
            BrollEffectType.KEN_BURNS_OUT,
            BrollEffectType.PAN_LEFT,
            BrollEffectType.PAN_UP,
        ]
        self._sequence_index = 0

    def get_next_effect(
        self,
        is_image: bool = False,
        context: Optional[str] = None
    ) -> BrollEffectType:
        """
        Selecciona el siguiente efecto siguiendo la secuencia curada.
        Alterna entre zoom y pan para que nunca se repita el mismo tipo.
        """
        selected = self._preferred_sequence[self._sequence_index % len(self._preferred_sequence)]
        self._sequence_index += 1
        self._effect_history.append(selected)
        logger.info(f"[BrollEffects] effect={selected.value}")
        return selected

    def build_effect_filter(
        self,
        effect_type: BrollEffectType,
        width: int,
        height: int,
        duration_frames: int
    ) -> str:
        """Construye filtro FFmpeg para el efecto especificado."""
        if effect_type == BrollEffectType.KEN_BURNS_IN:
            return self._ken_burns_in(width, height, duration_frames)
        elif effect_type == BrollEffectType.KEN_BURNS_OUT:
            return self._ken_burns_out(width, height, duration_frames)
        elif effect_type == BrollEffectType.PAN_RIGHT:
            return self._pan_right(width, height, duration_frames)
        elif effect_type == BrollEffectType.PAN_LEFT:
            return self._pan_left(width, height, duration_frames)
        elif effect_type == BrollEffectType.PAN_UP:
            return self._pan_up(width, height, duration_frames)
        else:
            return self._ken_burns_in(width, height, duration_frames)

    # ── Helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _ease_in_out(t: float) -> float:
        """
        Función de easing ease-in-out cúbica.
        t en [0, 1] → retorna valor easeado en [0, 1].
        """
        if t < 0.5:
            return 4.0 * t * t * t
        else:
            return 1.0 - pow(-2.0 * t + 2.0, 3.0) / 2.0

    @staticmethod
    def _build_zoompan_expr(
        zoom_start: float,
        zoom_end: float,
        frames: int,
        w: int,
        h: int,
    ) -> str:
        """
        Construye expresión zoompan con ease-in-out cúbico.
        Genera una expresión FFmpeg que interpola entre zoom_start y zoom_end
        usando la función de easing.
        """
        # Generamos una tabla de valores de zoom por frame (easeada)
        # FFmpeg zoompan no tiene funciones trigonométricas avanzadas,
        # así que usamos una aproximación polinómica por tramos.
        # Estrategia: usar la expresión 'if' anidada para aproximar ease-in-out.
        # Para simplificar y mantener compatibilidad, usamos una curva
        # cuadrática suave: z(t) = start + (end-start) * (3*t^2 - 2*t^3)
        # que es la fórmula de smoothstep (equivalente a ease-in-out cúbico).

        zoom_range = zoom_end - zoom_start
        # Construimos la expresión smoothstep: z = start + range * (3*t^2 - 2*t^3)
        # donde t = on / frames (normalizado a [0,1])
        # FFmpeg evalúa en punto flotante, así que funciona.
        expr = (
            f"zoom={zoom_start}+{zoom_range}*"
            f"(3*pow(on/{frames},2)-2*pow(on/{frames},3))"
        )
        return (
            f"zoompan=z='{expr}':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}"
        )

    # ── 5 efectos curados con ease-in-out y zoom cap ────────────────────

    def _ken_burns_in(self, w: int, h: int, frames: int) -> str:
        """Zoom in ease-in-out 1.0 → 1.08. Se hace UNA sola vez."""
        return self._build_zoompan_expr(
            zoom_start=1.0, zoom_end=MAX_ZOOM,
            frames=frames, w=w, h=h,
        )

    def _ken_burns_out(self, w: int, h: int, frames: int) -> str:
        """Zoom out ease-in-out 1.08 → 1.0. Se hace UNA sola vez."""
        return self._build_zoompan_expr(
            zoom_start=MAX_ZOOM, zoom_end=1.0,
            frames=frames, w=w, h=h,
        )

    def _pan_right(self, w: int, h: int, frames: int) -> str:
        """Pan izquierda → derecha con ease-in-out, z=1.08."""
        speed = round(w * 0.08 / max(frames, 1), 2)
        # Usamos smoothstep para la posición x también
        return (
            f"zoompan=z='{MAX_ZOOM}':d={frames}:"
            f"x='iw/2-(iw/{MAX_ZOOM}/2)+{speed}*{frames}*"
            f"(3*pow(on/{frames},2)-2*pow(on/{frames},3))':"
            f"y='ih/2-(ih/{MAX_ZOOM}/2)':s={w}x{h}"
        )

    def _pan_left(self, w: int, h: int, frames: int) -> str:
        """Pan derecha → izquierda con ease-in-out, z=1.08."""
        speed = round(w * 0.08 / max(frames, 1), 2)
        return (
            f"zoompan=z='{MAX_ZOOM}':d={frames}:"
            f"x='iw/2-(iw/{MAX_ZOOM}/2)-{speed}*{frames}*"
            f"(3*pow(on/{frames},2)-2*pow(on/{frames},3))':"
            f"y='ih/2-(ih/{MAX_ZOOM}/2)':s={w}x{h}"
        )

    def _pan_up(self, w: int, h: int, frames: int) -> str:
        """Pan abajo → arriba con ease-in-out, z=1.08."""
        speed = round(h * 0.05 / max(frames, 1), 2)
        return (
            f"zoompan=z='{MAX_ZOOM}':d={frames}:"
            f"x='iw/2-(iw/{MAX_ZOOM}/2)':"
            f"y='ih/2-(ih/{MAX_ZOOM}/2)-{speed}*{frames}*"
            f"(3*pow(on/{frames},2)-2*pow(on/{frames},3))':s={w}x{h}"
        )


# ── API pública ────────────────────────────────────────────────────────

# Instancia global del motor
_engine = BrollEffectsEngine()


def get_smart_broll_effect(
    is_image: bool = False,
    context: Optional[str] = None
) -> BrollEffectType:
    """Obtiene el siguiente efecto de forma inteligente."""
    return _engine.get_next_effect(is_image=is_image, context=context)


def build_broll_effect_filter(
    effect_type: BrollEffectType,
    width: int,
    height: int,
    duration: float,
    fps: int = FPS
) -> str:
    """
    Construye filtro FFmpeg para el efecto especificado.

    Enforces minimum duration >= MIN_DURATION_S (0.6s) for camera movements.
    If duration is below the minimum, it's clamped up and a WARNING is logged.
    """
    if duration < MIN_DURATION_S:
        logger.warning(
            "[BrollEffects] Clamping duration from %.2fs to %.2fs (min=%.1fs) — effect=%s",
            duration, MIN_DURATION_S, MIN_DURATION_S, effect_type.value,
        )
        duration = MIN_DURATION_S

    frames = int(duration * fps)
    return _engine.build_effect_filter(effect_type, width, height, frames)
