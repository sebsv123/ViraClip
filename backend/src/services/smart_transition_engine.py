"""
Smart Transition Engine — Transiciones Curadas para Clips Virales
==================================================================

Solo 3 transiciones cinematográficas probadas, las que usan los mejores
creadores de TikTok/Reels/Shorts:

  1. FADE       — fundido clásico, siempre funciona
  2. WIPE_RIGHT — barrido horizontal, dinámico y limpio
  3. ZOOM_IN    — zoom marcado solo UNA vez por sesión (como transición puntual)

Reglas:
  - Máximo 2-3 transiciones distintas por clip
  - Zoom sólo se usa UNA vez por sesión de clips
  - Sin flashes, sin glitch, sin efectos que distraigan
  - La transición debe ser invisible al ojo, no protagonista
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class TransitionType(str, Enum):
    """3 transiciones curadas para clips virales."""
    FADE       = "fade"        # Fundido clásico (el más usado en virales)
    WIPE_RIGHT = "wipe_right"  # Barrido horizontal limpio y dinámico
    ZOOM_IN    = "zoom_in"     # Zoom de impacto — solo UNA vez por sesión


class SmartTransitionEngine:
    """
    Motor de transiciones curado para clips virales.
    3 transiciones, el zoom solo ocurre una vez por sesión.
    """

    def __init__(self):
        self._zoom_used_in_session: bool = False
        # Secuencia fija: Fade → Wipe → Fade → Wipe... (el zoom irrumpe una vez)
        self._sequence = [
            TransitionType.FADE,
            TransitionType.WIPE_RIGHT,
        ]
        self._index = 0
    
    def get_next_transition(
        self,
        context: Optional[str] = None,
        is_broll: bool = True,
        energy_level: str = "medium"
    ) -> TransitionType:
        """
        Devuelve la siguiente transición siguiendo la secuencia curada.
        El zoom (impacto) solo aparece UNA vez por sesión, de forma puntual.
        """
        # El zoom se inyecta solo una vez en posición central de la sesión
        # (cuando el índice es divisible por 5 y aún no se ha usado)
        if not self._zoom_used_in_session and self._index > 0 and self._index % 5 == 0:
            self._zoom_used_in_session = True
            logger.info("[Transition] zoom_in (once per session)")
            return TransitionType.ZOOM_IN

        selected = self._sequence[self._index % len(self._sequence)]
        self._index += 1
        logger.info(f"[Transition] {selected.value}")
        return selected
    
    def build_transition_filter(
        self,
        transition_type: TransitionType,
        duration: float = 0.6
    ) -> str:
        """Devuelve el nombre del efecto xfade para FFmpeg."""
        xfade_effects = {
            TransitionType.FADE:       f"fade:duration={duration}",
            TransitionType.WIPE_RIGHT: f"wiperight:duration={duration}",
            TransitionType.ZOOM_IN:    f"zoomin:duration={duration}",
        }
        return xfade_effects.get(transition_type, f"fade:duration={duration}")


# ── API pública ────────────────────────────────────────────────────────

_engine = SmartTransitionEngine()


def get_smart_transition(
    context: Optional[str] = None,
    is_broll: bool = True,
    energy_level: str = "medium"
) -> TransitionType:
    """Obtiene la siguiente transición de forma inteligente."""
    return _engine.get_next_transition(context, is_broll, energy_level)


def build_transition_params(
    transition_type: TransitionType,
    duration: float = 0.6
) -> str:
    """Construye parámetros FFmpeg para la transición."""
    return _engine.build_transition_filter(transition_type, duration)
