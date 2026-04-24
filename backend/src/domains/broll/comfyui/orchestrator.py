"""
ComfyUIOrchestrator - Integración ViraClip con ComfyUI
Optimizado para RTX 5070 8GB VRAM
"""

import os
import aiohttp
import asyncio
import random
import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ComfyUIOrchestrator:
    """Orquesta workflows de ComfyUI para ViraClip"""
    
    def __init__(self, base_url: Optional[str] = None):
        if not base_url:
            host = os.getenv("COMFYUI_HOST", "localhost")
            port = os.getenv("COMFYUI_PORT", "8188")
            base_url = f"http://{host}:{port}"
        self.url = base_url.rstrip("/")
    
    async def subtitles(self, video_path: str, task_id: str) -> str:
        """Generar subtítulos con Whisper"""
        workflow = {
            "1": {
                "inputs": {
                    "video": f"/comfyui/input/{task_id}.mp4",
                    "force_rate": 30,
                    "frame_load_cap": 0
                },
                "class_type": "VHS_LoadVideo"
            },
            "2": {
                "inputs": {
                    "audio": ["1", 1],
                    "model": "base",
                    "language": "auto",
                    "transcription_format": "srt"
                },
                "class_type": "WhisperTranscribe"
            },
            "3": {
                "inputs": {
                    "transcription": ["2", 0],
                    "file_path": f"/comfyui/output/{task_id}.srt"
                },
                "class_type": "WhisperSaveTranscription"
            }
        }
        return await self._execute(workflow, task_id, "srt")
    
    async def reframe_9_16(self, video_path: str, task_id: str, 
                           chunk_size: int = 300) -> str:
        """Reencuadre 9:16 con chunking para videos largos"""
        workflow = {
            "1": {
                "inputs": {
                    "video": f"/comfyui/input/{task_id}.mp4",
                    "force_rate": 30,
                    "frame_load_cap": chunk_size
                },
                "class_type": "VHS_LoadVideo"
            },
            "2": {
                "inputs": {
                    "video": ["1", 0],
                    "width": 1080,
                    "height": 1920,
                    "interpolation": "bilinear"
                },
                "class_type": "VHS_ResizeVideo"
            },
            "3": {
                "inputs": {
                    "images": ["2", 0],
                    "frame_rate": 30,
                    "format": "video/h264-mp4",
                    "crf": 23
                },
                "class_type": "VHS_VideoCombine"
            },
            "4": {
                "inputs": {
                    "video": ["3", 0],
                    "filename_prefix": f"{task_id}_9_16"
                },
                "class_type": "VHS_SaveVideo"
            }
        }
        return await self._execute(workflow, task_id, "mp4")
    
    async def thumbnail(self, keyframe_path: str, task_id: str,
                        prompt: str = "cinematic viral thumbnail") -> str:
        """Generar thumbnail con SDXL-Turbo"""
        sdxl_model = os.getenv("COMFYUI_SDXL_MODEL", "sd_xl_turbo_1.0_fp16.safetensors")
        workflow = {
            "1": {
                "inputs": {
                    "text": f"{prompt}, bold colors, trending, best quality",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "2": {
                "inputs": {
                    "text": "blurry, low quality, watermark",
                    "clip": ["4", 1]
                },
                "class_type": "CLIPTextEncode"
            },
            "3": {
                "inputs": {
                    "width": 1920,
                    "height": 1080,
                    "batch_size": 1
                },
                "class_type": "EmptyLatentImage"
            },
            "4": {
                "inputs": {
                    "ckpt_name": sdxl_model
                },
                "class_type": "CheckpointLoaderSimple"
            },
            "5": {
                "inputs": {
                    "seed": random.randint(1, 1000000),
                    "steps": 4,
                    "cfg": 1.0,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": 0.9,
                    "model": ["4", 0],
                    "positive": ["1", 0],
                    "negative": ["2", 0],
                    "latent_image": ["3", 0]
                },
                "class_type": "KSampler"
            },
            "6": {
                "inputs": {
                    "samples": ["5", 0],
                    "vae": ["4", 2]
                },
                "class_type": "VAEDecode"
            },
            "7": {
                "inputs": {
                    "filename_prefix": f"thumb_{task_id}",
                    "images": ["6", 0]
                },
                "class_type": "SaveImage"
            }
        }
        return await self._execute(workflow, task_id, "png")

    async def generate_broll_with_ltx(
        self,
        prompt: str,
        task_id: str,
        duration_seconds: float = 3.0,
        width: int = 768,
        height: int = 512,
    ) -> str:
        """
        Generar video desde texto con LTX-Video.
        Workflow validado experimentalmente (test_ltx_workflow.json) con:
          - CheckpointLoaderSimple (ltxv-2b-0.9.8-distilled-fp8)
          - CLIPLoader tipo "ltxv" apuntando a t5xxl_fp8_e4m3fn.safetensors
          - KSampler estándar (euler/normal) — el checkpoint distilled corre con pocos pasos
          - VAEDecode + VHS_VideoCombine
        """
        frames = max(9, int(duration_seconds * 24))
        # LTX requiere length divisible por 8 + 1 (ej: 9, 17, 25, 33, 41, 49...)
        frames = ((frames - 1) // 8) * 8 + 1
        # Dimensiones divisibles por 32 (step del EmptyLTXVLatentVideo)
        width = max(64, (width // 32) * 32)
        height = max(64, (height // 32) * 32)

        negative_prompt = (
            "worst quality, inconsistent motion, blurry, jittery, distorted, "
            "watermark, text, logo, deformed, low resolution"
        )
        ltx_model = os.getenv("COMFYUI_LTX_MODEL", "ltxv-2b-0.9.8-distilled-fp8.safetensors")
        t5_model = os.getenv("LTX_T5_ENCODER", "t5xxl_fp8_e4m3fn.safetensors")

        workflow = {
            "0": {
                "inputs": {"clip_name": t5_model, "type": "ltxv"},
                "class_type": "CLIPLoader",
            },
            "1": {
                "inputs": {"ckpt_name": ltx_model},
                "class_type": "CheckpointLoaderSimple",
            },
            "2": {
                "inputs": {"text": prompt, "clip": ["0", 0]},
                "class_type": "CLIPTextEncode",
            },
            "3": {
                "inputs": {"text": negative_prompt, "clip": ["0", 0]},
                "class_type": "CLIPTextEncode",
            },
            "4": {
                "inputs": {
                    "width": width,
                    "height": height,
                    "length": frames,
                    "batch_size": 1,
                },
                "class_type": "EmptyLTXVLatentVideo",
            },
            "5": {
                "inputs": {
                    "seed": random.randint(1, 1_000_000),
                    "steps": 20,
                    "cfg": 3.0,
                    "sampler_name": "euler",
                    "scheduler": "normal",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
                "class_type": "KSampler",
            },
            "6": {
                "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
                "class_type": "VAEDecode",
            },
            "7": {
                "inputs": {
                    "images": ["6", 0],
                    "frame_rate": 24,
                    "loop_count": 0,
                    "filename_prefix": f"{task_id}_broll_ltx",
                    "format": "video/h264-mp4",
                    "pix_fmt": "yuv420p",
                    "crf": 20,
                    "save_metadata": False,
                    "save_output": True,
                    "pingpong": False,
                },
                "class_type": "VHS_VideoCombine",
            },
        }
        return await self._execute(workflow, task_id, "mp4")

    async def add_broll_transition(self, main_clip: str, task_id: str,
                                   broll_clip: Optional[str] = None,
                                   transition_type: str = "fade",
                                   duration: float = 1.0) -> str:
        """
        Concatena main_clip + broll_clip con una transición xfade usando
        FFmpeg directamente. ComfyUI no dispone de un nodo nativo de
        concat con transición (VHS_VideoConcat/VHS_SaveVideo no existen
        en la instalación actual), así que se hace en el worker.

        Si no se proporciona broll_clip se genera uno con LTX.
        """
        # Generar broll con LTX si no viene dado
        if not broll_clip:
            broll_prompt = (
                f"cinematic B-roll footage, {task_id}, professional quality, "
                "smooth motion, 9:16 vertical"
            )
            broll_clip = await self.generate_broll_with_ltx(
                broll_prompt, task_id, duration_seconds=3.0
            )

        main_p = Path(main_clip)
        broll_p = Path(broll_clip)
        if not main_p.exists():
            raise FileNotFoundError(f"main_clip no existe: {main_clip}")
        if not broll_p.exists():
            raise FileNotFoundError(f"broll_clip no existe: {broll_clip}")

        out_dir = Path(os.getenv("COMFYUI_LOCAL_OUTPUT_DIR", "/app/temp/uploads/comfy_out"))
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{task_id}_transition.mp4"

        # Duración del clip principal (para calcular offset del xfade)
        try:
            probe = await asyncio.create_subprocess_exec(
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(main_p),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await probe.communicate()
            main_dur = float(stdout.decode().strip() or 0.0)
        except Exception as exc:
            logger.warning(f"[broll_transition] ffprobe falló: {exc}")
            main_dur = 0.0

        xfade = transition_type if transition_type in {
            "fade", "wipeleft", "wiperight", "slideleft", "slideright",
            "circleopen", "circleclose", "dissolve", "radial",
        } else "fade"
        offset = max(0.0, main_dur - duration)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(main_p),
            "-i", str(broll_p),
            "-filter_complex",
            (
                f"[0:v][1:v]xfade=transition={xfade}:duration={duration}:offset={offset}[v];"
                f"[0:a][1:a]acrossfade=d={duration}[a]"
            ),
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ]

        logger.info(f"[broll_transition] ffmpeg xfade={xfade} offset={offset:.2f}s -> {out_path}")
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            # Fallback sin audio (algunos brolls LTX no traen pista de audio)
            logger.warning(
                f"[broll_transition] ffmpeg con audio falló ({proc.returncode}): "
                f"{stderr.decode(errors='ignore')[-300:]}; reintentando solo video"
            )
            cmd_v = [
                "ffmpeg", "-y", "-i", str(main_p), "-i", str(broll_p),
                "-filter_complex",
                f"[0:v][1:v]xfade=transition={xfade}:duration={duration}:offset={offset}[v]",
                "-map", "[v]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                "-an",
                str(out_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd_v, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _o, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg xfade fallo: {stderr.decode(errors='ignore')[-500:]}"
                )
        return str(out_path)
    
    async def _execute(self, workflow: Dict[str, Any], task_id: str,
                       ext: str) -> str:
        """
        Ejecuta un workflow en ComfyUI, espera su finalización, descarga el
        archivo de salida real vía /view, y devuelve una ruta local legible
        por el worker.

        - Resuelve el filename real desde history[prompt_id]['outputs'] en
          lugar de asumir un path hardcodeado (los workflows usan
          filename_prefix distintos al task_id, ej. `{task_id}_mask_00001.mp4`).
        - Descarga el binario por HTTP para no depender de mounts compartidos
          entre el contenedor comfyui y el worker.
        """
        timeout_s = int(os.getenv("COMFYUI_TIMEOUT", "600"))
        local_out_dir = Path(os.getenv("COMFYUI_LOCAL_OUTPUT_DIR", "/app/temp/uploads/comfy_out"))
        local_out_dir.mkdir(parents=True, exist_ok=True)

        # 1) Enviar workflow
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.url}/prompt", json={"prompt": workflow}) as resp:
                if resp.status != 200:
                    raise Exception(f"Error enviando workflow: {await resp.text()}")
                data = await resp.json()
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    raise Exception(f"No prompt_id in response: {data}")

        logger.info(f"[ComfyUI] prompt_id={prompt_id} task={task_id}")

        # 2) Poll history
        max_attempts = max(1, timeout_s // 2)
        outputs: Dict[str, Any] = {}
        status: Dict[str, Any] = {}
        for _ in range(max_attempts):
            await asyncio.sleep(2)
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.url}/history/{prompt_id}") as resp:
                    if resp.status != 200:
                        continue
                    hist = await resp.json()
            entry = hist.get(prompt_id)
            if not entry:
                continue
            status = entry.get("status", {}) or {}
            if status.get("status_str") == "error":
                msgs = status.get("messages", [])
                raise Exception(f"ComfyUI workflow error ({task_id}): {msgs}")
            if status.get("completed"):
                outputs = entry.get("outputs", {}) or {}
                break
        else:
            raise TimeoutError(f"Timeout esperando ComfyUI ({task_id})")

        # 3) Encontrar el primer archivo en outputs
        file_entry = self._pick_output_file(outputs, ext)
        if not file_entry:
            raise Exception(f"No output file in history for {task_id}: {list(outputs.keys())}")
        filename = file_entry["filename"]
        subfolder = file_entry.get("subfolder", "") or ""
        ftype = file_entry.get("type", "output") or "output"

        # 4) Descargar vía /view
        params = {"filename": filename, "subfolder": subfolder, "type": ftype}
        local_path = local_out_dir / f"{task_id}_{filename}"
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{self.url}/view", params=params) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise Exception(f"ComfyUI /view {resp.status}: {body[:200]}")
                data_bytes = await resp.read()
        local_path.write_bytes(data_bytes)
        logger.info(f"[ComfyUI] ✅ Downloaded {filename} -> {local_path} ({len(data_bytes)} bytes)")
        return str(local_path)

    @staticmethod
    def _pick_output_file(outputs: Dict[str, Any], preferred_ext: str) -> Optional[Dict[str, Any]]:
        """
        Busca entre los nodos del history el primer archivo producido.
        VHS_VideoCombine reporta en 'gifs'; SaveImage en 'images'; otros
        guardan listados bajo 'videos'/'files' según versión del nodo.
        """
        candidates = []
        for _node_id, node_out in outputs.items():
            if not isinstance(node_out, dict):
                continue
            for key in ("gifs", "videos", "images", "files"):
                items = node_out.get(key)
                if not isinstance(items, list):
                    continue
                for it in items:
                    if isinstance(it, dict) and it.get("filename"):
                        candidates.append(it)
        if not candidates:
            return None
        pref = f".{preferred_ext.lower().lstrip('.')}"
        for c in candidates:
            if c["filename"].lower().endswith(pref):
                return c
        return candidates[0]
    
    async def health_check(self) -> Dict[str, Any]:
        """Verificar estado de ComfyUI"""
        try:
            async with aiohttp.ClientSession() as session:
                # Check system stats
                async with session.get(
                    f"{self.url}/system_stats",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        system_data = await resp.json()

                        # Check available models in CheckpointLoaderSimple
                        try:
                            async with session.get(
                                f"{self.url}/object_info/CheckpointLoaderSimple",
                                timeout=aiohttp.ClientTimeout(total=5)
                            ) as model_resp:
                                if model_resp.status == 200:
                                    model_info = await model_resp.json()
                                    ckpt_list = model_info.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
                                    logger.info(f"Available CheckpointLoaderSimple models: {ckpt_list}")
                        except Exception as e:
                            logger.warning(f"Could not fetch CheckpointLoaderSimple models: {e}")

                        return {"status": "ok", "data": system_data}
                    return {"status": "error", "code": resp.status}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# Instancia global
comfyui_orchestrator = ComfyUIOrchestrator()


async def test_comfyui_connection():
    """Test rápido de conexión"""
    orch = ComfyUIOrchestrator()
    health = await orch.health_check()
    print(f"Health Check: {health}")
    return health.get("status") == "ok"


if __name__ == "__main__":
    # Test de conexión
    asyncio.run(test_comfyui_connection())
