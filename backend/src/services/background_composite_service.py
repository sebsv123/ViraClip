"""
BackgroundCompositeService - Servicio principal de composite SAM2 + LTX
"""

import os
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BackgroundCompositeService:
    """
    Servicio principal que orquesta el pipeline de background composite.
    Decide modo (A/B/C) y ejecuta el flujo correspondiente.
    """

    async def process(
        self,
        clip_path: str,
        task_id: str,
        viral_score: float,
        duration: float,
        broll_prompt: str
    ) -> dict:
        """
        Retorna:
        {
          "output_path": str|None,
          "mode_used": "A"|"B"|"C",
          "success": bool,
          "reason": str
        }
        """
        # 1. Check si está habilitado
        if os.getenv("BACKGROUND_COMPOSITE_ENABLED", "false").lower() != "true":
            return {
                "output_path": None,
                "mode_used": "C",
                "success": True,
                "reason": "feature_disabled"
            }

        # 2. Importar y llamar scene analyzer
        from .scene_analyzer import scene_analyzer

        try:
            analysis = await scene_analyzer.analyze(clip_path, viral_score, duration)
        except Exception as e:
            logger.warning(f"Scene analysis failed: {e}, defaulting to Mode B")
            analysis = {"mode": "B", "confidence": 0.5, "reason": "analyzer_error"}

        mode = analysis.get("mode", "B")

        # 3. Modo C - Clip limpio
        if mode == "C":
            return {
                "output_path": None,
                "mode_used": "C",
                "success": True,
                "reason": analysis.get("reason", "unknown")
            }

        # 4. Modo B - B-roll estándar
        if mode == "B":
            return {
                "output_path": None,
                "mode_used": "B",
                "success": True,
                "reason": analysis.get("reason", "not_suitable_for_composite")
            }

        # 5. Modo A - Composite SAM2 + LTX
        if mode == "A":
            logger.info(f"🎨 Modo A activado para {task_id} — composite SAM2+LTX")

            from .person_segmentation import person_segmentation_service
            from .composite_engine import composite_engine

            # Lanzar en paralelo
            try:
                person_result, bg_result = await asyncio.gather(
                    person_segmentation_service.extract_person(clip_path, task_id),
                    self._generate_ltx_background(clip_path, task_id, broll_prompt, duration),
                    return_exceptions=True
                )

                # Verificar resultados
                if isinstance(person_result, Exception) or person_result is None:
                    logger.warning(f"⚠️ Composite fallback a Modo B: person segmentation failed for {task_id}")
                    return {
                        "output_path": None,
                        "mode_used": "B",
                        "success": True,
                        "reason": "person_segmentation_failed"
                    }

                if isinstance(bg_result, Exception) or bg_result is None:
                    logger.warning(f"⚠️ Composite fallback a Modo B: LTX background failed for {task_id}")
                    return {
                        "output_path": None,
                        "mode_used": "B",
                        "success": True,
                        "reason": "ltx_background_failed"
                    }

                # Componer (original + mask SAM2 + fondo LTX)
                composite_result = await composite_engine.composite(
                    original_clip=clip_path,
                    mask_clip=person_result,
                    background_clip=bg_result,
                    task_id=task_id,
                )

                if composite_result is None:
                    return {
                        "output_path": None,
                        "mode_used": "B",
                        "success": True,
                        "reason": "composite_render_failed"
                    }

                logger.info(f"✅ Composite Mode A completado: {composite_result}")
                return {
                    "output_path": composite_result,
                    "mode_used": "A",
                    "success": True,
                    "reason": "ok"
                }

            except Exception as e:
                logger.warning(f"⚠️ Composite error, fallback to Mode B: {e}")
                return {
                    "output_path": None,
                    "mode_used": "B",
                    "success": True,
                    "reason": f"composite_error: {type(e).__name__}"
                }

        # Fallback por si acaso
        return {
            "output_path": None,
            "mode_used": "B",
            "success": True,
            "reason": "unexpected_mode"
        }

    async def _generate_ltx_background(
        self,
        clip_path: str,
        task_id: str,
        prompt,
        duration: float,
    ) -> Optional[str]:
        """
        Genera un video de FONDO con LTX-Video directamente desde un prompt
        semánticamente relacionado con el clip. Aspecto 9:16 (576x1024).
        """
        from .comfyui.orchestrator import comfyui_orchestrator

        # Normalizar prompt: acepta str o list[str]
        if isinstance(prompt, list):
            keywords = ", ".join(str(k) for k in prompt if k)
        else:
            keywords = str(prompt or "")

        # Construir prompt cinematográfico
        full_prompt = (
            f"cinematic background, {keywords}, "
            "atmospheric lighting, shallow depth of field, "
            "subtle camera motion, 35mm film, photorealistic, high quality"
        ).strip(", ")

        try:
            result = await comfyui_orchestrator.generate_broll_with_ltx(
                prompt=full_prompt,
                task_id=f"{task_id}_bg",
                duration_seconds=min(max(duration, 3.0), 8.0),
                width=576,
                height=1024,
            )
            if result:
                logger.info(f"[LTX-BG] ✅ Fondo generado: {result}")
            return result
        except Exception as e:
            logger.warning(f"[LTX-BG] Generation failed: {e}")
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────
background_composite_service = BackgroundCompositeService()
