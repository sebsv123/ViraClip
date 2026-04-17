"""
B-Roll Effects Engine — Efectos Cinematográficos Curados
=========================================================

Solo 5 efectos probados y estables para B-rolls virales:
  1. Ken Burns In   — zoom suave 1.0 → 1.10 (entrada)
  2. Ken Burns Out  — zoom suave 1.10 → 1.0 (reveal)
  3. Pan Right      — desplazamiento horizontal derecha
  4. Pan Left       — desplazamiento horizontal izquierda
  5. Pan Up         — desplazamiento vertical arriba

Reglas:
  - Máximo UN efecto por B-roll
  - El zoom solo pasa UNA vez (lineal, sin pulso ni bounce)
  - Sin flashes, sin rotaciones, sin efectos que marean
  - Alterna entre efectos para no repetir
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class BrollEffectType(str, Enum):
    """5 efectos curados y estables para B-roll viral."""
    KEN_BURNS_IN  = "ken_burns_in"   # Zoom 1.0 → 1.10  (suave, una sola vez)
    KEN_BURNS_OUT = "ken_burns_out"  # Zoom 1.10 → 1.0  (reveal, una sola vez)
    PAN_RIGHT     = "pan_right"      # Desplazamiento izquierda→derecha
    PAN_LEFT      = "pan_left"       # Desplazamiento derecha→izquierda
    PAN_UP        = "pan_up"         # Desplazamiento abajo→arriba


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
    
    # ── 5 efectos curados ────────────────────────────────────────────────

    def _ken_burns_in(self, w: int, h: int, frames: int) -> str:
        """Zoom in lineal suave 1.0 → 1.10. Se hace UNA sola vez."""
        step = round(0.10 / max(frames, 1), 6)
        return (
            f"zoompan=z='min(zoom+{step},1.10)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}"
        )

    def _ken_burns_out(self, w: int, h: int, frames: int) -> str:
        """Zoom out lineal suave 1.10 → 1.0. Se hace UNA sola vez."""
        step = round(0.10 / max(frames, 1), 6)
        return (
            f"zoompan=z='if(eq(on,1),1.10,max(1.0,zoom-{step}))':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}"
        )

    def _pan_right(self, w: int, h: int, frames: int) -> str:
        """Pan izquierda → derecha a velocidad constante."""
        speed = round(w * 0.08 / max(frames, 1), 2)
        return (
            f"zoompan=z='1.12':d={frames}:"
            f"x='iw/2-(iw/zoom/2)+on*{speed}':y='ih/2-(ih/zoom/2)':s={w}x{h}"
        )

    def _pan_left(self, w: int, h: int, frames: int) -> str:
        """Pan derecha → izquierda a velocidad constante."""
        speed = round(w * 0.08 / max(frames, 1), 2)
        return (
            f"zoompan=z='1.12':d={frames}:"
            f"x='iw/2-(iw/zoom/2)-on*{speed}':y='ih/2-(ih/zoom/2)':s={w}x{h}"
        )

    def _pan_up(self, w: int, h: int, frames: int) -> str:
        """Pan abajo → arriba a velocidad constante."""
        speed = round(h * 0.05 / max(frames, 1), 2)
        return (
            f"zoompan=z='1.12':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)-on*{speed}':s={w}x{h}"
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
    fps: int = 30
) -> str:
    """Construye filtro FFmpeg para el efecto especificado."""
    frames = int(duration * fps)
    return _engine.build_effect_filter(effect_type, width, height, frames)
