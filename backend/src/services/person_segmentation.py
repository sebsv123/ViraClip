"""
PersonSegmentationService - Segmentación de persona con SAM2 (kijai plugin) via ComfyUI.

Produce un MP4 greyscale con la MÁSCARA de la persona (blanco=persona, negro=fondo).
El composite final lo hace composite_engine con FFmpeg (alphamerge + overlay).

Dependencies en el contenedor ComfyUI (~/CascadeProjects/ViraClip/comfyui/custom_nodes/):
  - ComfyUI-segment-anything-2 (kijai)  -> Sam2Segmentation + DownloadAndLoadSAM2Model
  - ComfyUI-VideoHelperSuite           -> VHS_LoadVideo + VHS_VideoCombine
El modelo SAM2 en `.safetensors` se descarga automáticamente la primera vez
en ~/CascadeProjects/ViraClip/models/sam2/ (montado en /comfyui/models/sam2).
"""

import os
import json
import shutil
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _probe_dimensions(video_path: str) -> Tuple[int, int]:
    """Return (width, height) for the given video using ffprobe. Falls back to 1080x1920."""
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                video_path,
            ],
            capture_output=True, text=True, timeout=10,
        )
        w_str, h_str = out.stdout.strip().split("x")
        return int(w_str), int(h_str)
    except Exception as exc:
        logger.debug(f"[SAM2] ffprobe failed ({exc}); defaulting to 1080x1920")
        return 1080, 1920


class PersonSegmentationService:
    """Segmenta persona del fondo usando SAM2 (kijai plugin) en ComfyUI."""

    async def extract_person(
        self,
        clip_path: str,
        task_id: str,
    ) -> Optional[str]:
        """
        Ejecuta SAM2 sobre el clip y devuelve la ruta a un MP4 greyscale cuya
        luminosidad representa la máscara de la persona (blanco=persona, negro=fondo).
        Devuelve None si falla; el caller degrada a Modo B.
        """
        try:
            from .comfyui.orchestrator import comfyui_orchestrator

            # 1) Copiar clip al volumen compartido `uploads`.
            #    En el worker está montado en /app/temp/uploads/broll;
            #    en el contenedor comfyui es /comfyui/input. Se comunican
            #    pasando sólo el filename al nodo VHS_LoadVideo.
            input_filename = f"{task_id}_seg_input.mp4"
            shared_input = Path(
                os.getenv("COMFYUI_SHARED_INPUT_DIR", "/app/temp/uploads/broll")
            )
            shared_input.mkdir(parents=True, exist_ok=True)
            comfyui_input_path = shared_input / input_filename

            try:
                shutil.copy2(clip_path, comfyui_input_path)
                logger.info(f"[SAM2] Copied input to ComfyUI: {comfyui_input_path}")
            except Exception as e:
                logger.error(f"[SAM2] Failed to copy input: {e}")
                return None

            # 2) Heurística: punto en el centro del frame (aproximación de la persona).
            #    En clips 9:16 de talking-head el sujeto casi siempre está centrado.
            w, h = _probe_dimensions(str(comfyui_input_path))
            center_x = w // 2
            center_y = int(h * 0.45)   # un pelín por encima del centro (cara > tronco)
            coords_positive = json.dumps([{"x": center_x, "y": center_y}])

            # 3) Modelo SAM2 (.safetensors autodescargable por el loader del plugin)
            sam2_model = os.getenv("SAM2_MODEL", "sam2_hiera_small.safetensors")
            # El loader exige terminación .safetensors; si el env traía .pt, corregimos
            if sam2_model.endswith(".pt"):
                sam2_model = sam2_model[:-3] + ".safetensors"

            workflow = {
                "1": {
                    "inputs": {
                        "video": input_filename,
                        "force_rate": 0,
                        "custom_width": 0,
                        "custom_height": 0,
                        "frame_load_cap": 0,
                        "skip_first_frames": 0,
                        "select_every_nth": 1,
                    },
                    "class_type": "VHS_LoadVideo",
                },
                "2": {
                    "inputs": {
                        "model": sam2_model,
                        "segmentor": "video",
                        "device": "cuda",
                        "precision": "fp16",
                    },
                    "class_type": "DownloadAndLoadSAM2Model",
                },
                "3": {
                    "inputs": {
                        "sam2_model": ["2", 0],
                        "image": ["1", 0],
                        "keep_model_loaded": False,
                        "coordinates_positive": coords_positive,
                        "individual_objects": False,
                    },
                    "class_type": "Sam2Segmentation",
                },
                "4": {
                    "inputs": {"mask": ["3", 0]},
                    "class_type": "MaskToImage",
                },
                "5": {
                    "inputs": {
                        "images": ["4", 0],
                        "frame_rate": 30,
                        "loop_count": 0,
                        "filename_prefix": f"{task_id}_mask",
                        "format": "video/h264-mp4",
                        "pix_fmt": "yuv420p",
                        "crf": 18,
                        "save_metadata": False,
                        "save_output": True,
                        "pingpong": False,
                    },
                    "class_type": "VHS_VideoCombine",
                },
            }

            timeout = int(os.getenv("COMFYUI_TIMEOUT", "600"))
            logger.info(f"[SAM2] Starting segmentation for {task_id} (center=({center_x},{center_y}))")

            result = await asyncio.wait_for(
                comfyui_orchestrator._execute(workflow, f"{task_id}_seg", "mp4"),
                timeout=timeout,
            )

            if result and Path(result).exists():
                logger.info(f"[SAM2] ✅ Mask video created: {result}")
                return result

            logger.warning(f"[SAM2] ⚠️ No output for {task_id}")
            return None

        except asyncio.TimeoutError:
            logger.error(f"[SAM2] ⏱️ Timeout for {task_id}")
            return None
        except Exception as e:
            logger.error(f"[SAM2] ❌ Error for {task_id}: {e}")
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────
person_segmentation_service = PersonSegmentationService()
