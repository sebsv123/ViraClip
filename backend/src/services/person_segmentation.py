"""
PersonSegmentationService - Segmentación de persona con SAM2 via ComfyUI

SETUP REQUERIDO EN HOST (no en Docker):
cd ~/ComfyUI/custom_nodes
git clone https://github.com/kijai/ComfyUI-segment-anything-2
Descargar modelo SAM2 (~180MB):
mkdir -p ~/ComfyUI/models/sam2
wget -O ~/ComfyUI/models/sam2/sam2_hiera_small.pt \
  https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt
Reiniciar ComfyUI tras instalar
"""

import os
import shutil
import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PersonSegmentationService:
    """Segmenta persona del fondo usando SAM2 en ComfyUI."""

    async def extract_person(
        self,
        clip_path: str,
        task_id: str
    ) -> Optional[str]:
        """
        Segmenta la persona del fondo usando SAM2 en ComfyUI.
        Retorna ruta del video con alpha (webm) o None si falla.
        """
        try:
            # Importar orchestrator
            from .comfyui.orchestrator import comfyui_orchestrator

            # Copiar clip al volumen compartido de ComfyUI
            input_filename = f"{task_id}_seg_input.mp4"
            comfyui_input = Path(os.getenv("COMFYUI_INPUT_DIR", "/comfyui/input"))
            comfyui_input_path = comfyui_input / input_filename

            try:
                shutil.copy2(clip_path, comfyui_input_path)
                logger.info(f"📁 Copied input to ComfyUI: {comfyui_input_path}")
            except Exception as e:
                logger.error(f"❌ Failed to copy input to ComfyUI: {e}")
                return None

            # Construir workflow SAM2
            sam2_model = os.getenv("SAM2_MODEL", "sam2_hiera_small.pt")

            workflow = {
                "1": {
                    "inputs": {
                        "video": input_filename,
                        "force_rate": 24,
                        "frame_load_cap": 0,
                        "choose video to upload": "input"
                    },
                    "class_type": "VHS_LoadVideo"
                },
                "2": {
                    "inputs": {
                        "model": sam2_model,
                        "frames": ["1", 0],
                        "bboxes": [],
                        "labels": [],
                        "threshold": 0.5,
                        "prediction_step": 2
                    },
                    "class_type": "SAM2VideoSegmentation"
                },
                "3": {
                    "inputs": {
                        "images": ["1", 0],
                        "mask": ["2", 0]
                    },
                    "class_type": "ApplyMaskToImages"
                },
                "4": {
                    "inputs": {
                        "images": ["3", 0],
                        "frame_rate": 24,
                        "loop_count": 0,
                        "filename_prefix": f"{task_id}_person",
                        "format": "video/webm-vp9",
                        "crf": 20,
                        "save_metadata": False
                    },
                    "class_type": "VHS_VideoCombine"
                }
            }

            # Ejecutar workflow con timeout
            timeout = int(os.getenv("COMFYUI_TIMEOUT", "600"))

            logger.info(f"🎨 Starting SAM2 segmentation for {task_id}")

            result = await asyncio.wait_for(
                comfyui_orchestrator._execute(workflow, f"{task_id}_seg", "webm"),
                timeout=timeout
            )

            if result and Path(result).exists():
                logger.info(f"✅ SAM2 segmentation complete: {result}")
                return result
            else:
                logger.warning(f"⚠️ SAM2 segmentation returned no output for {task_id}")
                return None

        except asyncio.TimeoutError:
            logger.error(f"⏱️ SAM2 segmentation timeout for {task_id}")
            return None
        except Exception as e:
            logger.error(f"❌ SAM2 segmentation error for {task_id}: {e}")
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────
person_segmentation_service = PersonSegmentationService()
