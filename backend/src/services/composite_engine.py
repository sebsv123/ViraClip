"""
CompositeEngine - Compone persona sobre fondo generado
"""

import os
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CompositeEngine:
    """Compone persona segmentada sobre fondo generado."""

    async def composite(
        self,
        person_clip: str,
        background_clip: str,
        task_id: str
    ) -> Optional[str]:
        """
        Compone persona sobre fondo generado.
        Retorna ruta del video compuesto o None si falla.
        """
        try:
            # Importar orchestrator
            from .comfyui.orchestrator import comfyui_orchestrator

            # Copiar ambos archivos al input de ComfyUI
            comfyui_input = Path(os.getenv("COMFYUI_INPUT_DIR", "/comfyui/input"))

            person_filename = f"{task_id}_person_input.webm"
            bg_filename = f"{task_id}_bg_input.mp4"

            person_dst = comfyui_input / person_filename
            bg_dst = comfyui_input / bg_filename

            try:
                shutil.copy2(person_clip, person_dst)
                shutil.copy2(background_clip, bg_dst)
                logger.info(f"📁 Copied person and background to ComfyUI")
            except Exception as e:
                logger.error(f"❌ Failed to copy inputs: {e}")
                return None

            # Workflow de composición
            workflow = {
                "1": {
                    "inputs": {
                        "video": person_filename,
                        "force_rate": 24,
                        "frame_load_cap": 0,
                        "choose video to upload": "input"
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "2": {
                    "inputs": {
                        "video": bg_filename,
                        "force_rate": 24,
                        "frame_load_cap": 0,
                        "choose video to upload": "input"
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "3": {
                    "inputs": {
                        "destination": ["2", 0],
                        "source": ["1", 0],
                        "x": 0,
                        "y": 0,
                        "resize_source": True
                    },
                    "class_type": "ImageCompositeMasked"
                },
                "4": {
                    "inputs": {
                        "images": ["3", 0],
                        "frame_rate": 24,
                        "loop_count": 0,
                        "filename_prefix": f"{task_id}_composite",
                        "format": "video/h264-mp4",
                        "crf": 18,
                        "save_metadata": False
                    },
                    "class_type": "VHS_VideoCombine"
                }
            }

            # Ejecutar con timeout
            timeout = int(os.getenv("COMFYUI_TIMEOUT", "600"))

            logger.info(f"🎬 Starting composite for {task_id}")

            result = await asyncio.wait_for(
                comfyui_orchestrator._execute(workflow, f"{task_id}_comp", "mp4"),
                timeout=timeout
            )

            if result and Path(result).exists():
                logger.info(f"✅ Composite complete: {result}")
                return result
            else:
                logger.warning(f"⚠️ Composite returned no output for {task_id}")
                return None

        except asyncio.TimeoutError:
            logger.error(f"⏱️ Composite timeout for {task_id}")
            return None
        except Exception as e:
            logger.error(f"❌ Composite error for {task_id}: {e}")
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────
composite_engine = CompositeEngine()
