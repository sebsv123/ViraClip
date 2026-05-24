"""
sam_singleton — Singleton de SAM para el worker ARQ.

Carga el modelo Segment Anything una sola vez al arrancar el worker
y lo reutiliza en todas las llamadas a shape_morph_transition.

Dependencia unidireccional: sam_singleton NO importa nada de clip_editor.
clip_editor importa get_sam_predictor() desde aquí.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_sam_predictor = None       # SamPredictor o None
_sam_model_type: str | None = None  # 'vit_h' | 'vit_b' | None
_sam_available = False


def initialize_sam(models_dir: str = "/app/models") -> bool:
    """
    Carga SAM en memoria. Llamar una sola vez al startup del worker.

    Intenta cargar ``vit_h`` primero (calidad ultra), fallback a ``vit_b``.
    Si ninguno está disponible, ``_sam_available = False`` y no lanza excepción.

    Parameters
    ----------
    models_dir : str
        Directorio donde buscar los checkpoints ``sam_vit_h.pth`` y
        ``sam_vit_b.pth``.

    Returns
    -------
    bool
        ``True`` si se cargó correctamente, ``False`` si no hay modelos.
    """
    global _sam_predictor, _sam_model_type, _sam_available

    models_path = Path(models_dir)
    vit_h_path = models_path / "sam_vit_h.pth"
    vit_b_path = models_path / "sam_vit_b.pth"

    # Determinar qué checkpoint usar
    if vit_h_path.exists():
        checkpoint = str(vit_h_path)
        model_type = "vit_h"
    elif vit_b_path.exists():
        checkpoint = str(vit_b_path)
        model_type = "vit_b"
    else:
        logger.warning(
            "[SAM] No se encontraron checkpoints en %s — "
            "shape_morph_transition usará rembg como fallback. "
            "Esperaba: sam_vit_h.pth o sam_vit_b.pth",
            models_dir,
        )
        _sam_available = False
        return False

    try:
        from segment_anything import SamPredictor, sam_model_registry

        start = time.monotonic()
        logger.info("[SAM] Cargando modelo %s desde %s ...", model_type, checkpoint)
        sam = sam_model_registry[model_type](checkpoint=checkpoint)
        _sam_predictor = SamPredictor(sam)
        _sam_model_type = model_type
        _sam_available = True
        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "[SAM] %s cargado en memoria (%.0f ms)",
            model_type, elapsed,
        )
        return True

    except Exception as exc:
        logger.warning(
            "[SAM] Error cargando modelo %s: %s — "
            "shape_morph_transition usará rembg como fallback",
            model_type, exc,
        )
        _sam_available = False
        return False


def get_sam_predictor():
    """
    Devuelve el predictor SAM cargado, o ``None`` si no está disponible.

    No lanza excepción — el caller decide si degradar.
    """
    return _sam_predictor if _sam_available else None


def get_sam_model_type() -> Optional[str]:
    """Devuelve el tipo de modelo SAM cargado (``'vit_h'`` o ``'vit_b'``)."""
    return _sam_model_type if _sam_available else None


def is_sam_available() -> bool:
    """Devuelve ``True`` si SAM está cargado y listo para usar."""
    return _sam_available
